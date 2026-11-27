from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..db import get_db, session_scope
from ..models import Deal, Notification, PushSubscription, User, Watch, utcnow
from ..notify import email as email_channel
from ..notify import webpush as push_channel
from ..notify import whatsapp as whatsapp_channel
from ..notify.common import ChannelError, Message
from ..schemas import EndpointIn, PushIn, TestChannelIn
from ..security import current_user, limiter
from ..sources.base import SourceError, assert_public_url

router = APIRouter(prefix="/api", tags=["avisos"])

MAX_DEVICES = 20


def notification_dict(item: Notification, deliveries: bool = True) -> dict:
    data = {
        "id": item.id, "kind": item.kind, "priority": item.priority, "title": item.title,
        "body": item.body, "url": item.url, "path": item.path, "image": item.image,
        "created_at": item.created_at, "read": item.read_at is not None,
    }
    if deliveries:
        data["deliveries"] = [
            {"channel": d.channel, "status": d.status, "error": d.error} for d in item.deliveries
        ]
    return data


@router.get("/notifications")
def list_notifications(
    offset: int = Query(default=0, ge=0), limit: int = Query(default=40, ge=1, le=100),
    user: User = Depends(current_user), db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Notification)
        .options(selectinload(Notification.deliveries))
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    unread = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    return {"items": [notification_dict(r) for r in rows], "unread": unread}


@router.post("/notifications/read")
def mark_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()
    return {"ok": True}


@router.get("/push/key")
def push_key(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _, public = push_channel.ensure_keys(db)
    devices = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
    ).all()
    return {
        "key": public,
        "devices": [
            {"endpoint": d.endpoint, "user_agent": d.user_agent, "created_at": d.created_at}
            for d in devices
        ],
    }


@router.post("/push/subscribe")
def subscribe(
    data: PushIn, request: Request, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:  # o servidor fará requisições a esse endereço: só aceitamos destinos públicos
        assert_public_url(data.endpoint)
    except SourceError as exc:
        raise HTTPException(422, f"Endereço de push inválido: {exc}") from exc
    row = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
    if row is None:
        count = db.scalar(
            select(func.count(PushSubscription.id)).where(PushSubscription.user_id == user.id)
        )
        if count >= MAX_DEVICES:
            raise HTTPException(400, "Limite de dispositivos atingido")
        row = PushSubscription(endpoint=data.endpoint, user_id=user.id, p256dh="", auth="")
        db.add(row)
    row.user_id = user.id
    row.p256dh, row.auth = data.keys.p256dh, data.keys.auth
    row.user_agent = request.headers.get("user-agent", "")[:300]
    db.commit()
    return {"ok": True}


@router.post("/push/unsubscribe")
def unsubscribe(
    data: EndpointIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == data.endpoint, PushSubscription.user_id == user.id
        )
    )
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


@router.post("/channels/test")
def test_channel(
    data: TestChannelIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    key = f"test:{user.id}"
    limiter.check(key)
    limiter.fail(key)  # no máximo alguns testes por janela
    message = Message(
        title="Teste do BFTracker ✅",
        body="Se você recebeu esta mensagem, este canal está funcionando.",
        path="/configuracoes",
    )
    try:
        if data.channel == "push":
            push_channel.send(db, user, message)
        elif data.channel == "email":
            email_channel.send(db, user, [message])
        else:
            whatsapp_channel.send(db, user, [message])
    except ChannelError as exc:
        db.commit()
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"ok": True}


def _snapshot(user_id: int) -> dict:
    with session_scope() as db:
        return {
            "notification": db.scalar(
                select(func.max(Notification.id)).where(Notification.user_id == user_id)
            ) or 0,
            "deal": db.scalar(select(func.max(Deal.id))) or 0,
            "check": str(
                db.scalar(
                    select(func.max(Watch.last_checked_at)).where(Watch.user_id == user_id)
                )
            ),
        }


def _fresh_notifications(user_id: int, after: int) -> list[dict]:
    with session_scope() as db:
        rows = db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.id > after)
            .order_by(Notification.id.desc())
            .limit(5)
        ).all()
        return [notification_dict(r, deliveries=False) for r in reversed(rows)]


@router.get("/events")
async def events(request: Request, user: User = Depends(current_user)):
    """Atualizações em tempo real (Server-Sent Events)."""
    user_id = user.id

    async def stream():
        last = await asyncio.to_thread(_snapshot, user_id)
        yield "retry: 5000\n\n"
        idle = 0
        # a conexão é renovada periodicamente para revalidar a sessão
        for _ in range(400):
            await asyncio.sleep(3)
            if await request.is_disconnected():
                return
            current = await asyncio.to_thread(_snapshot, user_id)
            if current != last:
                payload: dict = {
                    "deals": current["deal"] != last["deal"],
                    "watches": current["check"] != last["check"],
                    "notifications": [],
                }
                if current["notification"] > last["notification"]:
                    payload["notifications"] = await asyncio.to_thread(
                        _fresh_notifications, user_id, last["notification"]
                    )
                last, idle = current, 0
                body = json.dumps(payload, default=str, ensure_ascii=False)
                yield f"event: update\ndata: {body}\n\n"
            else:
                idle += 1
                if idle >= 5:
                    idle = 0
                    yield ": ping\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "CDN-Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
