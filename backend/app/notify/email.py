from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

from sqlalchemy.orm import Session

from ..core.appsettings import get_value
from ..models import User
from .common import ChannelError, Message, app_link


def is_configured(db: Session) -> bool:
    return bool(get_value(db, "smtp_host"))


def render_html(db: Session, messages: list[Message]) -> str:
    cards = []
    for msg in messages:
        image = (
            f'<img src="{escape(msg.image)}" alt="" width="96" '
            'style="border-radius:12px;background:#fff;float:right;margin:0 0 8px 12px">'
            if msg.image.startswith("https://") else ""
        )
        store = (
            f'<a href="{escape(msg.url)}" style="display:inline-block;background:#7c3aed;'
            'color:#fff;text-decoration:none;padding:10px 18px;border-radius:10px;'
            'font-weight:600;margin-right:8px">Ver oferta</a>'
            if msg.url.startswith("http") else ""
        )
        badge = "🔥 " if msg.priority >= 3 else ""
        cards.append(
            f'<div style="background:#171a2b;border:1px solid #2a2f4a;border-radius:16px;'
            f'padding:20px;margin-bottom:14px">{image}'
            f'<h2 style="margin:0 0 8px;font-size:17px;color:#fff">{badge}{escape(msg.title)}</h2>'
            f'<p style="margin:0 0 16px;color:#c3c8e0;font-size:14px;line-height:1.55;'
            f'white-space:pre-line">{escape(msg.body)}</p>{store}'
            f'<a href="{escape(app_link(db, msg.path))}" style="color:#a78bfa;font-size:14px">'
            "Abrir no BFTracker</a></div>"
        )
    return (
        '<!doctype html><html lang="pt-BR"><body style="margin:0;background:#0b0d17;'
        'font-family:Arial,Helvetica,sans-serif;padding:24px">'
        '<div style="max-width:600px;margin:0 auto">'
        '<p style="color:#a78bfa;font-weight:700;font-size:20px;margin:0 0 18px">BFTracker</p>'
        + "".join(cards)
        + '<p style="color:#6b7194;font-size:12px">Confira preço, vendedor e condições na loja '
        "antes de comprar. Ajuste os avisos em Configurações.</p></div></body></html>"
    )


def build(db: Session, to: str, messages: list[Message]) -> EmailMessage:
    sender = get_value(db, "smtp_from") or get_value(db, "smtp_user")
    if not sender:
        raise ChannelError("Informe o remetente (SMTP From) em Configurações")
    mail = EmailMessage()
    subject = messages[0].title
    if len(messages) > 1:
        subject = f"{len(messages)} novidades: {subject}"
    mail["Subject"] = " ".join(subject.split())[:180]
    mail["From"] = sender if "<" in sender else f"BFTracker <{sender}>"
    mail["To"] = to
    mail["Date"] = formatdate(localtime=True)
    mail["Message-ID"] = make_msgid(domain="bftracker")
    plain = "\n\n".join(
        f"{m.title}\n{m.body}\n{m.url or app_link(db, m.path)}" for m in messages
    )
    mail.set_content(plain)
    mail.add_alternative(render_html(db, messages), subtype="html")
    return mail


def send(db: Session, user: User, messages: list[Message]) -> None:
    host = get_value(db, "smtp_host")
    if not host:
        raise ChannelError("SMTP não configurado")
    if not user.email:
        raise ChannelError("Usuário sem e-mail")
    mail = build(db, user.email, messages)
    port = int(get_value(db, "smtp_port") or 587)
    security = (get_value(db, "smtp_security") or "starttls").lower()
    username, password = get_value(db, "smtp_user"), get_value(db, "smtp_password")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=20)
        with client:
            if security == "starttls":
                client.starttls(context=context)
            if username:
                client.login(username, password)
            client.send_message(mail)
    except (OSError, smtplib.SMTPException, UnicodeError) as exc:
        raise ChannelError(f"Falha no envio de e-mail: {exc}") from exc
