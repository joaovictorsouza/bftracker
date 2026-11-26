"""Canais testados de ponta a ponta contra servidores locais: o push é recebido e
decifrado, o e-mail passa por um SMTP de verdade e o WhatsApp bate na API esperada."""

import base64
import json
import os
import socketserver
import threading
from datetime import datetime
from email import message_from_string, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.core.appsettings import set_value, stored
from app.models import AppSetting, Delivery, PushSubscription, utcnow
from app.notify import whatsapp
from app.notify.common import ChannelError, Message
from app.notify.dispatch import deliver_pending, notify, quiet_until


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def http_server():
    calls: list[dict] = []
    status = {"code": 201}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            calls.append({"method": "POST", "path": self.path, "headers": dict(self.headers),
                          "body": body})
            self.send_response(status["code"])
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self):
            calls.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"numberExists": true, "chatId": "551187654321@c.us"}')

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", calls, status
    server.shutdown()


@pytest.fixture
def smtp_server():
    inbox: list[str] = []

    class Smtp(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 teste\r\n")
            while line := self.rfile.readline():
                command = line[:4].upper()
                if command == b"DATA":
                    self.wfile.write(b"354 ok\r\n")
                    data = []
                    while (row := self.rfile.readline()) not in (b".\r\n", b""):
                        data.append(row.decode())
                    inbox.append("".join(data))
                    self.wfile.write(b"250 ok\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Smtp)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], inbox
    server.shutdown()


def subscribe(session, user, endpoint):
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    session.add(PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=b64(public),
                                 auth=b64(auth)))
    session.commit()
    return private, auth


def send(session, user, key="k1", priority=2, title="⬇️ PS5 caiu 10%"):
    item = notify(session, user, kind="price_drop", title=title, body="R$ 4.000 na KaBuM!",
                  dedupe_key=key, priority=priority, url="https://loja.example/p")
    session.commit()
    return item


def test_web_push_is_encrypted_and_signed(session, user, http_server):
    base, calls, _ = http_server
    private, auth = subscribe(session, user, f"{base}/push/abc")
    assert send(session, user)
    assert deliver_pending(session) == {"sent": 1, "failed": 0}
    [call] = calls
    headers = {k.lower(): v for k, v in call["headers"].items()}
    assert headers["authorization"].startswith("vapid t=")
    assert headers["content-encoding"] == "aes128gcm"
    payload = json.loads(
        http_ece.decrypt(call["body"], private_key=private, auth_secret=auth, version="aes128gcm")
    )
    assert payload["title"] == "⬇️ PS5 caiu 10%" and payload["url"] == "https://loja.example/p"


def test_expired_subscription_is_removed(session, user, http_server):
    base, _, status = http_server
    status["code"] = 410
    subscribe(session, user, f"{base}/push/velho")
    send(session, user)
    assert deliver_pending(session)["failed"] == 1
    assert session.scalar(select(PushSubscription)) is None


def test_email_digest_over_smtp(session, user, smtp_server):
    port, inbox = smtp_server
    for key, value in {"smtp_host": "127.0.0.1", "smtp_port": str(port), "smtp_security": "none",
                       "smtp_from": "alertas@example.com"}.items():
        set_value(session, key, value)
    user.email = "pessoa@example.com"
    session.commit()
    send(session, user, "a", title="Oferta <um>")
    send(session, user, "b", title="Oferta dois")
    assert deliver_pending(session) == {"sent": 2, "failed": 0}
    [raw] = inbox
    mail = message_from_string(raw, policy=policy.default)
    assert mail["To"] == "pessoa@example.com" and mail["Subject"].startswith("2 novidades")
    body = mail.get_body(("html",)).get_content()
    assert "Oferta &lt;um&gt;" in body and "https://loja.example/p" in body


def test_failures_retry_then_give_up(session, user):
    for key, value in {"smtp_host": "127.0.0.1", "smtp_port": "9", "smtp_security": "none",
                       "smtp_from": "a@example.com"}.items():
        set_value(session, key, value)
    user.email = "p@example.com"
    session.commit()
    send(session, user)
    for attempt in range(1, 6):
        assert deliver_pending(session)["failed"] == 1
        row = session.scalar(select(Delivery))
        assert row.attempts == attempt and row.error
        row.next_attempt_at = utcnow()
        session.commit()
    assert session.scalar(select(Delivery)).status == "failed"
    assert deliver_pending(session) == {"sent": 0, "failed": 0}


def test_priority_threshold_dedupe_and_channels(session, user):
    set_value(session, "smtp_host", "smtp.example.com")
    user.email = "p@example.com"
    session.commit()
    low = send(session, user, "low", priority=1)
    assert low.deliveries == [], "e-mail só recebe a partir de 'importante'"
    assert [d.channel for d in send(session, user, "normal").deliveries] == ["email"]
    assert send(session, user, "normal") is None


@pytest.mark.parametrize(
    "hour,expected", [(23, True), (3, True), (6, True), (7, False), (12, False)]
)
def test_quiet_hours_cross_midnight(hour, expected):
    prefs = {"quiet_start": "22:00", "quiet_end": "07:00"}
    now = datetime(2026, 11, 25, hour, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    until = quiet_until(prefs, now)
    assert (until is not None) is expected
    if until:
        assert until > now and until.astimezone(ZoneInfo("America/Sao_Paulo")).hour == 7


def test_quiet_hours_hold_normal_but_not_urgent(session, user):
    set_value(session, "smtp_host", "smtp.example.com")
    user.email = "p@example.com"
    user.prefs = {"quiet_start": "00:00", "quiet_end": "23:59"}
    session.commit()
    held = send(session, user, "n")
    urgent = send(session, user, "u", priority=3)
    if quiet_until(user.prefs):  # fora do último minuto do dia
        assert held.deliveries[0].next_attempt_at > utcnow()
    assert urgent.deliveries[0].next_attempt_at <= utcnow()


def configure(session, **values):
    for key, value in values.items():
        set_value(session, key, value)
    session.commit()


def test_whatsapp_waha(session, user, http_server):
    base, calls, _ = http_server
    configure(session, whatsapp_provider="waha", waha_url=base, waha_api_key="segredo")
    user.whatsapp = "(11) 98765-4321"
    whatsapp.send(session, user, [Message(title="Queda", body="R$ 10", url="https://x.example")])
    assert "check-exists" in calls[0]["path"] and "5511987654321" in calls[0]["path"]
    sent = json.loads(calls[1]["body"])
    assert calls[1]["path"] == "/api/sendText"
    assert sent["chatId"] == "551187654321@c.us" and "*Queda*" in sent["text"]
    assert calls[1]["headers"]["X-Api-Key"] == "segredo"


def test_whatsapp_evolution_and_webhook(session, user, http_server):
    base, calls, _ = http_server
    user.whatsapp = "+55 11 98765-4321"
    configure(session, whatsapp_provider="evolution", evolution_url=base,
              evolution_api_key="k", evolution_instance="casa")
    whatsapp.send_text(session, user, "oi")
    assert calls[-1]["path"] == "/message/sendText/casa"
    assert json.loads(calls[-1]["body"]) == {"number": "5511987654321", "text": "oi"}
    configure(session, whatsapp_provider="webhook", whatsapp_webhook_url=f"{base}/hook")
    whatsapp.send_text(session, user, "oi")
    assert json.loads(calls[-1]["body"])["phone"] == "5511987654321"


@pytest.mark.parametrize("provider", ["meta", "callmebot"])
def test_whatsapp_cloud_providers(session, user, monkeypatch, provider):
    seen = {}

    def fake(method, url, **kwargs):
        import httpx

        seen.update(method=method, url=url, **kwargs)
        return httpx.Response(200, text="Message queued")

    monkeypatch.setattr(whatsapp.httpx, "request", fake)
    user.whatsapp, user.callmebot_key = "11987654321", "123"
    configure(session, whatsapp_provider=provider, meta_wa_token="t", meta_wa_phone_id="42")
    whatsapp.send_text(session, user, "oi")
    if provider == "meta":
        assert seen["url"].endswith("/42/messages") and seen["json"]["text"]["body"] == "oi"
    else:
        assert seen["params"] == {"phone": "+5511987654321", "text": "oi", "apikey": "123"}


def test_whatsapp_not_configured(session, user):
    user.whatsapp = "11987654321"
    with pytest.raises(ChannelError):
        whatsapp.send_text(session, user, "oi")


def test_secrets_are_encrypted_at_rest(session):
    configure(session, smtp_password="super-secreta")
    row = session.get(AppSetting, "smtp_password")
    assert row.secret and "super-secreta" not in row.value
    assert stored(session, "smtp_password") == "super-secreta"
