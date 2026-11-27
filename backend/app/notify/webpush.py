"""Notificações push no navegador/celular (Web Push com chaves VAPID geradas no
primeiro uso e guardadas no banco)."""

from __future__ import annotations

import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.appsettings import get_value, set_value, stored
from ..models import PushSubscription, User
from .common import ChannelError, Message

log = logging.getLogger(__name__)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def ensure_keys(db: Session) -> tuple[str, str]:
    """Retorna (chave privada DER em base64, chave pública para o navegador)."""
    private, public = stored(db, "vapid_private_key"), stored(db, "vapid_public_key")
    if private and public:
        return private, public
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64(
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = _b64(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    try:
        set_value(db, "vapid_private_key", private)
        set_value(db, "vapid_public_key", public)
        db.commit()
    except IntegrityError:  # API e worker iniciando ao mesmo tempo
        db.rollback()
        return stored(db, "vapid_private_key"), stored(db, "vapid_public_key")
    return private, public


def _subject(db: Session, user: User) -> str:
    settings = get_settings()
    if settings.vapid_subject:
        return settings.vapid_subject.strip()
    email = (settings.admin_email or user.email).strip()
    if email:
        return f"mailto:{email}"
    public = get_value(db, "public_url").strip().rstrip("/")
    if public.startswith("https://"):
        return public
    return "mailto:admin@example.com"


def send(db: Session, user: User, message: Message) -> None:
    private, _ = ensure_keys(db)
    subscriptions = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all()
    if not subscriptions:
        raise ChannelError("Nenhum dispositivo inscrito para push")
    payload = json.dumps(
        {
            "id": message.id,
            "title": message.title,
            "body": message.body[:600],
            "url": message.url,
            "path": message.path,
            "image": message.image,
            "priority": message.priority,
        },
        ensure_ascii=False,
    )
    delivered, errors = 0, []
    vapid = Vapid02.from_string(private)  # RFC 8292 (exigido pela Apple)
    subject = _subject(db, user)
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": subject},
                ttl=6 * 3600,
                headers={"Urgency": "high" if message.priority >= 3 else "normal"},
                timeout=15,
            )
            delivered += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                db.delete(subscription)  # dispositivo cancelou a inscrição
            errors.append(f"HTTP {status}" if status else str(exc)[:200])
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc)[:200])
    db.flush()
    if not delivered:
        raise ChannelError("Push não entregue: " + "; ".join(errors))
