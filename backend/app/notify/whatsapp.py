"""Envio por WhatsApp. Provedores suportados:

* waha      – servidor próprio (perfil "whatsapp" do docker compose), pareado por QR Code
* evolution – Evolution API já existente
* meta      – WhatsApp Cloud API oficial
* callmebot – serviço gratuito para uso pessoal (cada usuário gera sua chave)
* webhook   – POST JSON para a automação que você preferir (n8n, Zapier etc.)
"""

from __future__ import annotations

import re

import httpx
from sqlalchemy.orm import Session

from ..core.appsettings import get_value
from ..models import User
from .common import ChannelError, Message, app_link

PROVIDERS = ("waha", "evolution", "meta", "callmebot", "webhook")


def provider_of(db: Session) -> str:
    return get_value(db, "whatsapp_provider").strip().lower()


def is_configured(db: Session, user: User | None = None) -> bool:
    provider = provider_of(db)
    if provider == "waha":
        return bool(get_value(db, "waha_url"))
    if provider == "evolution":
        return all(
            get_value(db, k)
            for k in ("evolution_url", "evolution_api_key", "evolution_instance")
        )
    if provider == "meta":
        return bool(get_value(db, "meta_wa_token") and get_value(db, "meta_wa_phone_id"))
    if provider == "callmebot":
        return user is None or bool(user.callmebot_key)
    if provider == "webhook":
        return bool(get_value(db, "whatsapp_webhook_url"))
    return False


def normalize_number(number: str) -> str:
    """Só dígitos, com DDI 55 quando vier apenas DDD + número."""
    digits = re.sub(r"\D", "", number or "")
    if len(digits) in (10, 11) and not number.strip().startswith("+"):
        digits = "55" + digits
    return digits


def compose(db: Session, messages: list[Message]) -> str:
    blocks = []
    for msg in messages:
        flame = "🔥 " if msg.priority >= 3 else ""
        link = msg.url or app_link(db, msg.path)
        blocks.append(f"{flame}*{msg.title}*\n{msg.body}\n{link}")
    return "\n\n———\n\n".join(blocks)[:3800]


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        response = httpx.request(method, url, timeout=25, **kwargs)
    except httpx.HTTPError as exc:
        raise ChannelError(f"WhatsApp inacessível: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise ChannelError(
            f"WhatsApp respondeu HTTP {response.status_code}: {response.text[:200]}"
        )
    return response


def send_text(db: Session, user: User, text: str) -> None:
    provider = provider_of(db)
    number = normalize_number(user.whatsapp)
    if not number:
        raise ChannelError("Usuário sem número de WhatsApp")
    if provider == "waha":
        headers = {}
        if key := get_value(db, "waha_api_key"):
            headers["X-Api-Key"] = key
        base = get_value(db, "waha_url").rstrip("/")
        session = get_value(db, "waha_session") or "default"
        chat_id = f"{number}@c.us"
        # contas brasileiras antigas podem usar o número sem o nono dígito
        try:
            found = _request(
                "GET", f"{base}/api/contacts/check-exists",
                params={"phone": number, "session": session}, headers=headers,
            ).json()
            if found.get("numberExists") and found.get("chatId"):
                chat_id = found["chatId"]
        except (ChannelError, ValueError):
            pass
        _request(
            "POST", f"{base}/api/sendText", headers=headers,
            json={"session": session, "chatId": chat_id, "text": text},
        )
    elif provider == "evolution":
        base = get_value(db, "evolution_url").rstrip("/")
        instance = get_value(db, "evolution_instance")
        _request(
            "POST", f"{base}/message/sendText/{instance}",
            headers={"apikey": get_value(db, "evolution_api_key")},
            json={"number": number, "text": text},
        )
    elif provider == "meta":
        token, phone_id = get_value(db, "meta_wa_token"), get_value(db, "meta_wa_phone_id")
        template = get_value(db, "meta_wa_template")
        payload: dict = {"messaging_product": "whatsapp", "to": number}
        if template:
            # modelo aprovado com um único parâmetro de corpo (exigido fora da janela de 24 h)
            flat = " ".join(text.split())[:900]
            payload |= {
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": get_value(db, "meta_wa_template_lang") or "pt_BR"},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": flat}]}
                    ],
                },
            }
        else:
            payload |= {"type": "text", "text": {"body": text, "preview_url": True}}
        _request(
            "POST", f"https://graph.facebook.com/v23.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"}, json=payload,
        )
    elif provider == "callmebot":
        if not user.callmebot_key:
            raise ChannelError("Informe sua chave do CallMeBot no perfil")
        response = _request(
            "GET", "https://api.callmebot.com/whatsapp.php",
            params={"phone": f"+{number}", "text": text[:1500], "apikey": user.callmebot_key},
        )
        if "error" in response.text.lower()[:400]:
            raise ChannelError("CallMeBot recusou a mensagem (confira número e chave)")
    elif provider == "webhook":
        _request(
            "POST", get_value(db, "whatsapp_webhook_url"),
            json={"phone": number, "text": text, "username": user.username},
        )
    else:
        raise ChannelError("Nenhum provedor de WhatsApp configurado")


def send(db: Session, user: User, messages: list[Message]) -> None:
    send_text(db, user, compose(db, messages))
