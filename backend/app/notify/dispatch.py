"""Cria notificações e entrega pelos canais do usuário (push, e-mail, WhatsApp),
com horário de silêncio, agrupamento e novas tentativas."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.text import clip
from ..models import Delivery, Notification, PushSubscription, User, utcnow
from . import email as email_channel
from . import webpush as push_channel
from . import whatsapp as whatsapp_channel
from .common import ChannelError, Message

log = logging.getLogger(__name__)

CHANNELS = ("push", "email", "whatsapp")
MAX_ATTEMPTS = 5

DEFAULT_PREFS = {
    "channels": {"push": True, "email": True, "whatsapp": False},
    # prioridade mínima por canal: 1 = tudo, 2 = normal e urgente, 3 = só urgente
    "min_priority": {"push": 1, "email": 2, "whatsapp": 2},
    "quiet_start": "",
    "quiet_end": "",
    "quiet_allow_urgent": True,
}


def prefs_of(user: User) -> dict:
    prefs = {**DEFAULT_PREFS, **(user.prefs or {})}
    for key in ("channels", "min_priority"):
        prefs[key] = {**DEFAULT_PREFS[key], **((user.prefs or {}).get(key) or {})}
    return prefs


def quiet_until(prefs: dict, now: datetime | None = None) -> datetime | None:
    """Se estiver no horário de silêncio, retorna quando ele termina."""
    start, end = prefs.get("quiet_start"), prefs.get("quiet_end")
    if not start or not end or start == end:
        return None
    local = (now or utcnow()).astimezone(ZoneInfo(get_settings().timezone))
    current = local.strftime("%H:%M")
    inside = start <= current < end if start < end else current >= start or current < end
    if not inside:
        return None
    hour, minute = (int(x) for x in end.split(":"))
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.astimezone(utcnow().tzinfo)


def reachable_channels(db: Session, user: User, priority: int) -> list[str]:
    prefs = prefs_of(user)
    available = {
        "push": db.scalar(
            select(PushSubscription.id).where(PushSubscription.user_id == user.id).limit(1)
        )
        is not None,
        "email": bool(user.email) and email_channel.is_configured(db),
        "whatsapp": bool(user.whatsapp) and whatsapp_channel.is_configured(db, user),
    }
    return [
        channel
        for channel in CHANNELS
        if prefs["channels"].get(channel)
        and available[channel]
        and priority >= int(prefs["min_priority"].get(channel, 1))
    ]


def notify(
    db: Session,
    user: User,
    *,
    kind: str,
    title: str,
    body: str,
    dedupe_key: str,
    priority: int = 2,
    url: str = "",
    path: str = "/",
    image: str = "",
    watch_id: int | None = None,
) -> Notification | None:
    dedupe_key = dedupe_key[:200]
    exists = db.scalar(
        select(Notification.id).where(
            Notification.user_id == user.id, Notification.dedupe_key == dedupe_key
        )
    )
    if exists:
        return None
    item = Notification(
        user_id=user.id,
        kind=kind,
        priority=priority,
        title=clip(title, 200),
        body=body.strip()[:2000],
        url=url,
        path=path,
        image=image,
        watch_id=watch_id,
        dedupe_key=dedupe_key,
    )
    prefs = prefs_of(user)
    until = quiet_until(prefs)
    if until and priority >= 3 and prefs.get("quiet_allow_urgent"):
        until = None
    for channel in reachable_channels(db, user, priority):
        item.deliveries.append(Delivery(channel=channel, next_attempt_at=until or utcnow()))
    db.add(item)
    db.flush()
    return item


def _message(item: Notification) -> Message:
    return Message(
        id=item.id,
        title=item.title,
        body=item.body,
        url=item.url,
        path=item.path,
        image=item.image,
        priority=item.priority,
    )


def deliver_pending(db: Session, limit: int = 200) -> dict[str, int]:
    """Entrega a fila. E-mail e WhatsApp agrupam o que estiver pendente por usuário."""
    now = utcnow()
    rows = db.scalars(
        select(Delivery)
        .where(Delivery.status == "pending", Delivery.next_attempt_at <= now)
        .order_by(Delivery.id)
        .limit(limit)
    ).all()
    groups: dict[tuple[int, str], list[Delivery]] = {}
    for row in rows:
        groups.setdefault((row.notification.user_id, row.channel), []).append(row)

    stats = {"sent": 0, "failed": 0}
    for (user_id, channel), deliveries in groups.items():
        user = db.get(User, user_id)
        if user is None:
            continue
        # mensagens urgentes primeiro
        deliveries.sort(key=lambda d: (-d.notification.priority, d.id))
        if channel == "push":
            batches = [[d] for d in deliveries]
        else:
            size = 20 if channel == "email" else 6
            batches = [deliveries[i : i + size] for i in range(0, len(deliveries), size)]
        for batch in batches:
            messages = [_message(d.notification) for d in batch]
            try:
                if channel == "push":
                    push_channel.send(db, user, messages[0])
                elif channel == "email":
                    email_channel.send(db, user, messages)
                else:
                    whatsapp_channel.send(db, user, messages)
                for delivery in batch:
                    delivery.status, delivery.sent_at, delivery.error = "sent", utcnow(), ""
                    delivery.attempts += 1
                stats["sent"] += len(batch)
            except Exception as exc:  # noqa: BLE001 - um canal não pode derrubar os demais
                if not isinstance(exc, ChannelError):
                    log.exception("Erro inesperado no canal %s", channel)
                for delivery in batch:
                    delivery.attempts += 1
                    delivery.error = str(exc)[:500]
                    if delivery.attempts >= MAX_ATTEMPTS:
                        delivery.status = "failed"
                    else:
                        delivery.next_attempt_at = utcnow() + timedelta(
                            minutes=2 ** delivery.attempts
                        )
                stats["failed"] += len(batch)
            db.commit()
    return stats
