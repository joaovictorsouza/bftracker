"""Configurações editáveis pela interface (segredos cifrados no banco), com fallback
para variáveis de ambiente."""

from __future__ import annotations

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting

SECRET_KEYS = {
    "smtp_password", "waha_api_key", "evolution_api_key", "meta_wa_token", "ml_client_secret",
    "ml_access_token", "ml_refresh_token", "ml_access_cache", "vapid_private_key",
    "whatsapp_webhook_url", "x_bearer_token", "x_api_secret", "x_bearer_cache",
    "serper_api_key", "brave_api_key", "imap_password",
}
EDITABLE_KEYS = (
    "public_url",
    "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_security",
    "whatsapp_provider", "waha_url", "waha_api_key", "waha_session",
    "evolution_url", "evolution_api_key", "evolution_instance",
    "meta_wa_token", "meta_wa_phone_id", "meta_wa_template", "meta_wa_template_lang",
    "whatsapp_webhook_url",
    "x_bearer_token", "x_api_key", "x_api_secret", "x_accounts", "x_rss_search_url",
    "serper_api_key", "brave_api_key",
    "imap_host", "imap_port", "imap_user", "imap_password", "imap_folder",
    "ml_client_id", "ml_client_secret", "ml_access_token",
)


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"bftracker-settings:" + get_settings().secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def stored(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    if row is None:
        return None
    if not row.secret:
        return row.value
    try:
        return _fernet().decrypt(row.value.encode()).decode()
    except InvalidToken:
        return None  # SECRET_KEY mudou: o segredo precisa ser informado de novo


def get_value(db: Session, key: str) -> str:
    value = stored(db, key)
    if value:
        return value
    return str(getattr(get_settings(), key, "") or "")


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if value == "":
        if row is not None:
            db.delete(row)
        return
    secret = key in SECRET_KEYS
    data = _fernet().encrypt(value.encode()).decode() if secret else value
    if row is None:
        db.add(AppSetting(key=key, value=data, secret=secret))
    else:
        row.value, row.secret = data, secret
    db.flush()


def get_json(db: Session, key: str, default):
    value = stored(db, key)
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


def set_json(db: Session, key: str, value) -> None:
    set_value(db, key, json.dumps(value, ensure_ascii=False))
