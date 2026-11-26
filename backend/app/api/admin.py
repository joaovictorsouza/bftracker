from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.appsettings import (
    EDITABLE_KEYS,
    SECRET_KEYS,
    get_json,
    get_value,
    set_json,
    set_value,
    stored,
)
from ..core.engine import reset_offers
from ..core.radar import default_interests
from ..core.sourcestate import get_status
from ..core.text import slug
from ..db import get_db
from ..models import (
    Interest,
    Notification,
    PushSubscription,
    RunRequest,
    SourceStatus,
    User,
    Watch,
)
from ..notify.whatsapp import PROVIDERS
from ..schemas import CustomSourceIn, SettingsIn, ToggleIn, UserIn
from ..security import admin_user, hash_password
from ..sources.base import SourceError, assert_public_url
from ..sources.registry import feed_sources, store_sources
from .auth import user_dict

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])

_CUSTOM_KEYS = {"telegram": "custom_telegram", "rss": "custom_rss", "vtex": "custom_vtex"}


@router.get("/settings")
def read_settings(db: Session = Depends(get_db)):
    values, configured = {}, {}
    for key in EDITABLE_KEYS:
        value = get_value(db, key)
        configured[key] = bool(value)
        # segredos nunca voltam para o navegador
        values[key] = "" if key in SECRET_KEYS else value
    return {
        "values": values,
        "configured": configured,
        "overridden": [k for k in EDITABLE_KEYS if stored(db, k)],
        "secrets": sorted(SECRET_KEYS & set(EDITABLE_KEYS)),
    }


@router.put("/settings")
def write_settings(data: SettingsIn, db: Session = Depends(get_db)):
    """`null` mantém o valor atual; texto vazio volta ao padrão do ambiente."""
    for key, value in data.values.items():
        if key not in EDITABLE_KEYS:
            raise HTTPException(422, f"Configuração desconhecida: {key}")
        if value is None:
            continue
        value = value.strip()
        if len(value) > 1000:
            raise HTTPException(422, f"Valor longo demais em {key}")
        if key == "smtp_port" and value and not value.isdigit():
            raise HTTPException(422, "A porta SMTP deve ser um número")
        if key == "whatsapp_provider" and value and value not in PROVIDERS:
            raise HTTPException(422, "Provedor de WhatsApp desconhecido")
        if key.endswith("_url") and value and not re.match(r"https?://", value):
            raise HTTPException(422, f"{key} deve começar com http:// ou https://")
        set_value(db, key, value)
    db.commit()
    return read_settings(db)


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    catalog = [(s.key, s.name, "store", s.covers, 0) for s in store_sources(db)]
    catalog += [(s.key, s.name, "feed", "", s.interval_seconds) for s in feed_sources(db)]
    out = []
    for key, name, kind, covers, interval in catalog:
        status = db.get(SourceStatus, key)
        out.append(
            {
                "key": key, "name": name, "kind": kind, "covers": covers,
                "interval_seconds": interval,
                "enabled": status.enabled if status else True,
                "state": status.state if status else "unknown",
                "message": status.message if status else "",
                "last_ok_at": status.last_ok_at if status else None,
                "last_run_at": status.last_run_at if status else None,
                "blocked_until": status.blocked_until if status else None,
                "last_items": status.last_items if status else 0,
            }
        )
    custom = [
        {"kind": kind, **entry}
        for kind, key in _CUSTOM_KEYS.items()
        for entry in get_json(db, key, [])
    ]
    return {"sources": out, "custom": custom}


def _find(db: Session, key: str):
    for source in store_sources(db):
        if source.key == key:
            return source.name, "store"
    for source in feed_sources(db):
        if source.key == key:
            return source.name, "feed"
    raise HTTPException(404, "Fonte não encontrada")


@router.put("/sources/{key:path}/enabled")
def toggle_source(key: str, data: ToggleIn, db: Session = Depends(get_db)):
    name, kind = _find(db, key)
    status = get_status(db, key, name, kind)
    status.enabled = data.enabled
    if data.enabled:
        status.blocked_until, status.failures = None, 0
    db.commit()
    return {"ok": True}


@router.post("/sources/{key:path}/run")
def run_source(key: str, db: Session = Depends(get_db)):
    name, kind = _find(db, key)
    status = get_status(db, key, name, kind)
    status.blocked_until = None
    if kind == "feed":
        db.add(RunRequest(kind="source", target=key))
    db.commit()
    return {"ok": True}


@router.post("/custom-sources", status_code=201)
def add_source(data: CustomSourceIn, db: Session = Depends(get_db)):
    store_key = _CUSTOM_KEYS[data.kind]
    entries = get_json(db, store_key, [])
    if len(entries) >= 40:
        raise HTTPException(400, "Limite de fontes personalizadas atingido")
    value = data.value.strip()
    if data.kind == "telegram":
        channel = re.sub(r"^(https?://)?(t\.me/)?(s/)?@?", "", value).strip("/")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,40}", channel):
            raise HTTPException(422, "Informe o nome público do canal (ex.: pelandobr)")
        if any(e["channel"].lower() == channel.lower() for e in entries):
            raise HTTPException(409, "Canal já cadastrado")
        entry = {"key": f"tg:{channel.lower()}", "channel": channel,
                 "name": data.name.strip() or f"@{channel}"}
    else:
        try:
            assert_public_url(value)
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc
        key = slug(data.name or re.sub(r"https?://(www\.)?", "", value), 30)
        if not key or any(e["key"] == key for e in entries):
            raise HTTPException(409, "Dê um nome diferente a essa fonte")
        entry = {"key": key, "name": data.name.strip() or key, "url": value.rstrip("/")
                 if data.kind == "vtex" else value}
    entries.append(entry)
    set_json(db, store_key, entries)
    db.commit()
    return entry


@router.delete("/custom-sources/{kind}/{key:path}")
def remove_source(kind: str, key: str, db: Session = Depends(get_db)):
    if kind not in _CUSTOM_KEYS:
        raise HTTPException(404, "Tipo desconhecido")
    entries = get_json(db, _CUSTOM_KEYS[kind], [])
    remaining = [e for e in entries if e["key"] != key]
    if len(remaining) == len(entries):
        raise HTTPException(404, "Fonte não encontrada")
    if remaining:
        set_json(db, _CUSTOM_KEYS[kind], remaining)
    else:
        set_value(db, _CUSTOM_KEYS[kind], "")
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    return [user_dict(u) | {"callmebot_key": ""} for u in db.scalars(
        select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(data: UserIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username.ilike(data.username.replace("_", r"\_"),
                                                        escape="\\"))):
        raise HTTPException(409, "Usuário já existe")
    user = User(username=data.username, password_hash=hash_password(data.password),
                is_admin=data.is_admin, prefs={})
    db.add(user)
    db.flush()
    default_interests(db, user)
    db.commit()
    return user_dict(user)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, me: User = Depends(admin_user), db: Session = Depends(get_db)):
    if user_id == me.id:
        raise HTTPException(400, "Você não pode excluir a própria conta")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Usuário não encontrado")
    for watch in db.scalars(select(Watch).where(Watch.user_id == user.id)):
        reset_offers(db, watch)
        db.delete(watch)
    for model in (Interest, PushSubscription):
        for row in db.scalars(select(model).where(model.user_id == user.id)):
            db.delete(row)
    for row in db.scalars(select(Notification).where(Notification.user_id == user.id)):
        db.delete(row)
    db.flush()
    db.delete(user)
    db.commit()
    return {"ok": True}


def _waha(db: Session, method: str, path: str, **kwargs) -> httpx.Response:
    base = get_value(db, "waha_url").rstrip("/")
    headers = {"X-Api-Key": get_value(db, "waha_api_key")} if get_value(db, "waha_api_key") else {}
    try:
        return httpx.request(method, base + path, headers=headers, timeout=20, **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(
            502, "Servidor WhatsApp (WAHA) inacessível. Suba com o perfil 'whatsapp'."
        ) from exc


@router.get("/whatsapp/status")
def whatsapp_status(db: Session = Depends(get_db)):
    session = get_value(db, "waha_session") or "default"
    response = _waha(db, "GET", f"/api/sessions/{session}")
    if response.status_code == 404:
        return {"status": "STOPPED"}
    if response.status_code in (401, 403):
        raise HTTPException(502, "WAHA recusou a chave de API (WAHA_API_KEY)")
    if response.status_code >= 400:
        raise HTTPException(502, f"WAHA respondeu HTTP {response.status_code}")
    body = response.json()
    return {"status": body.get("status"), "me": (body.get("me") or {}).get("id")}


@router.post("/whatsapp/start")
def whatsapp_start(db: Session = Depends(get_db)):
    session = get_value(db, "waha_session") or "default"
    current = _waha(db, "GET", f"/api/sessions/{session}")
    if current.status_code == 404:
        response = _waha(db, "POST", "/api/sessions", json={"name": session, "start": True})
    elif current.status_code < 300 and current.json().get("status") == "FAILED":
        response = _waha(db, "POST", f"/api/sessions/{session}/restart")
    else:
        response = _waha(db, "POST", f"/api/sessions/{session}/start")
    if response.status_code >= 400:
        raise HTTPException(502, f"WAHA: {response.text[:200]}")
    return {"ok": True}


@router.get("/whatsapp/qr")
def whatsapp_qr(db: Session = Depends(get_db)):
    session = get_value(db, "waha_session") or "default"
    response = _waha(db, "GET", f"/api/{session}/auth/qr", params={"format": "image"})
    if response.status_code >= 400:
        raise HTTPException(409, "QR Code ainda não disponível")
    return Response(
        response.content, media_type=response.headers.get("content-type", "image/png"),
        headers={"Cache-Control": "no-store"},
    )
