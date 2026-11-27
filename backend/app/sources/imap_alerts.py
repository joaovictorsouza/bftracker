"""Leitor opcional de alertas por e-mail via IMAP (somente leitura, sem marcar como lido).

Transforma notificações oficiais enviadas por e-mail — buscas salvas da **OLX**, assinatura
do fórum **hardMOB Promoções**, alertas do **Mercado Livre**, **Google Alerts**, **Pelando**
e **X (Twitter)** — em ofertas nos seus monitorados e avisos imediatos no WhatsApp/Push.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from ..core import dealtext, stores
from ..core.appsettings import get_json, get_value, set_json
from ..core.text import clip, parse_brl, short_hash
from ..db import session_scope
from .base import FeedSource, Fetcher, FoundCoupon, FoundDeal, NotConfigured, SourceError

ALERT_DOMAINS: dict[str, tuple[str, str]] = {
    "olx.com.br": ("imap:olx", "OLX (alerta e-mail)"),
    "hardmob.com.br": ("imap:hardmob", "hardMOB Promoções"),
    "mercadolivre.com": ("imap:mercadolivre", "Mercado Livre (alerta e-mail)"),
    "mercadolibre.com": ("imap:mercadolivre", "Mercado Livre (alerta e-mail)"),
    "google.com": ("imap:google", "Google Alertas"),
    "pelando.com.br": ("imap:pelando", "Pelando (e-mail)"),
    "promobit.com.br": ("imap:promobit", "Promobit (e-mail)"),
    "x.com": ("x_twitter", "X (e-mail)"),
    "twitter.com": ("x_twitter", "X (e-mail)"),
}

_SKIP_LINK_WORDS = (
    "unsubscribe", "descadastr", "cancelar", "preferencia", "preferences",
    "privacidade", "privacy", "ajuda.", "help.", "suporte", "login", "conta",
)


def _decode_str(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return " ".join("".join(parts).split())


def _sender_source(from_header: str) -> tuple[str, str] | None:
    lower = from_header.lower()
    for domain, info in ALERT_DOMAINS.items():
        if domain in lower:
            return info
    return None


def _extract_bodies(msg: Message) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                plain_parts.append(decoded)
            elif ctype == "text/html":
                html_parts.append(decoded)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(decoded)
            else:
                plain_parts.append(decoded)
    return "\n".join(plain_parts), "\n".join(html_parts)


def _good_link(url: str) -> bool:
    if not url.startswith(("https://", "http://")):
        return False
    lower = url.lower()
    if any(w in lower for w in _SKIP_LINK_WORDS):
        return False
    if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".css")):
        return False
    return True


def parse_alert_email(raw_bytes: bytes) -> list[FoundDeal]:
    """Extrai uma ou mais ofertas de uma mensagem MIME de alerta."""
    msg = email.message_from_bytes(raw_bytes)
    sender = _decode_str(msg.get("From"))
    matched_sender = _sender_source(sender)
    if matched_sender is None:
        return []
    source_key, source_name = matched_sender
    subject = _decode_str(msg.get("Subject"))
    msg_id = _decode_str(msg.get("Message-ID")) or short_hash(sender, subject)

    published = None
    if date_hdr := msg.get("Date"):
        try:
            dt = parsedate_to_datetime(date_hdr)
            published = dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            published = None

    plain, html = _extract_bodies(msg)
    deals: list[FoundDeal] = []

    # 1) E-mails de busca salva da OLX costumam trazer vários anúncios na mesma mensagem
    if source_key == "imap:olx" and html:
        tree = HTMLParser(html)
        seen_urls: set[str] = set()
        for a in tree.css("a[href*='olx.com.br']"):
            href = stores.unwrap_url(a.attributes.get("href") or "")
            if not _good_link(href) or not re.search(r"-\d{6,}", href) or href in seen_urls:
                continue
            card_node = a.parent
            for _ in range(3):
                if card_node and len(card_node.text(strip=True)) < 25 and card_node.parent:
                    card_node = card_node.parent
            context = card_node.text(separator=" ", strip=True) if card_node else a.text(strip=True)
            title = a.text(strip=True) or context
            title = re.sub(r"R\$\s*[\d.,]+.*", "", title).strip() or subject
            price, _ = dealtext.find_prices(context)
            if not price or len(title) < 3:
                continue
            seen_urls.add(href)
            ad_match = re.search(r"-(\d{6,})", href)
            ident = ad_match.group(1) if ad_match else short_hash(href)
            deals.append(
                FoundDeal(
                    source=source_key,
                    source_name=source_name,
                    external_id=ident,
                    title=clip(title, 240),
                    url=href,
                    link=href,
                    description=clip(context, 500),
                    store="OLX",
                    price=price,
                    published_at=published,
                )
            )
        if deals:
            return deals

    # 2) Caso geral: hardMOB (vBulletin), Google Alerts, Mercado Livre, X, Pelando…
    links: list[str] = []
    if html:
        tree = HTMLParser(html)
        for a in tree.css("a[href]"):
            href = stores.unwrap_url(a.attributes.get("href") or "")
            if "google.com/url?" in href:
                if m := re.search(r"[?&](?:q|url)=([^&]+)", href):
                    from urllib.parse import unquote

                    href = stores.unwrap_url(unquote(m.group(1)))
            if _good_link(href):
                links.append(href)
        body_text = tree.body.text(separator="\n", strip=True) if tree.body else plain
    else:
        body_text = plain
        for m in re.finditer(r"https?://[^\s<>\"')]+", plain):
            href = stores.unwrap_url(m.group(0))
            if _good_link(href):
                links.append(href)

    clean_subject = re.sub(
        r"^(?:\[[^\]]+\]\s*|Novo tópico[^:]*:\s*|Google Alert\s*[-–:]\s*)",
        "",
        subject,
        flags=re.I,
    ).strip()
    full_text = f"{clean_subject}\n{body_text}".strip()
    if not full_text:
        return []

    primary_url = links[0] if links else ""
    store_link = next(
        (
            u
            for u in links
            if stores.find_by_url(u) is not None and "hardmob.com.br" not in u.lower()
        ),
        primary_url,
    )
    if not primary_url:
        return []

    price, old_price = dealtext.find_prices(full_text)
    coupon = dealtext.find_coupon(full_text)
    store_obj = (
        (stores.find_by_url(store_link) if store_link else None)
        or stores.find_in_text(clean_subject)
        or stores.find_in_text(body_text[:500])
    )
    if source_key == "imap:olx" and not store_obj:
        store_name = "OLX"
    elif source_key == "imap:mercadolivre" and not store_obj:
        store_name = "Mercado Livre"
    else:
        store_name = store_obj.name if store_obj else ""

    deals.append(
        FoundDeal(
            source=source_key,
            source_name=source_name,
            external_id=short_hash(msg_id, primary_url),
            title=clip(clean_subject or body_text.splitlines()[0], 250),
            url=primary_url,
            link=store_link if store_link != primary_url else primary_url,
            description=clip(body_text, 800),
            store=store_name,
            price=price,
            old_price=old_price,
            coupon=coupon,
            published_at=published,
            is_coupon=bool(coupon) and price is None,
        )
    )
    return deals


def _poll_imap_sync(check_only: bool = False) -> tuple[list[FoundDeal], dict]:
    with session_scope() as db:
        host = get_value(db, "imap_host").strip()
        port_raw = get_value(db, "imap_port").strip() or "993"
        user = get_value(db, "imap_user").strip()
        password = get_value(db, "imap_password")
        folder = get_value(db, "imap_folder").strip() or "INBOX"
        cursor = dict(get_json(db, "imap_cursor", {}))

    if not host or not user or not password:
        raise NotConfigured(
            "Opcional: configure servidor, usuário e senha IMAP em Configurações → Integrações "
            "para ler alertas automáticos da OLX, hardMOB, Google Alerts e Mercado Livre"
        )
    port = int(port_raw) if port_raw.isdigit() else 993

    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=20)
    except OSError as exc:
        raise SourceError(f"Não foi possível conectar ao IMAP {host}:{port}: {exc}") from exc

    deals: list[FoundDeal] = []
    try:
        conn.login(user, password)
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise SourceError(f"Pasta IMAP não encontrada: {folder}")
        uidvalidity = ""
        resp_uv = conn.response("UIDVALIDITY")[1]
        if resp_uv and resp_uv[0]:
            uidvalidity = resp_uv[0].decode(errors="ignore") if isinstance(resp_uv[0], bytes) else str(resp_uv[0])

        since_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%d-%b-%Y")
        typ, data = conn.uid("search", None, f"(SINCE {since_date})")
        if typ != "OK":
            return [], {"ok": True, "checked": 0, "deals": 0}
        raw_uids = data[0].split() if data and data[0] else []
        uids = [int(u) for u in raw_uids if u.isdigit()]

        last_uid = int(cursor.get("last_uid") or 0) if cursor.get("uidvalidity") == uidvalidity else 0
        if check_only:
            target_uids = uids[-15:]
        elif last_uid > 0:
            target_uids = [u for u in uids if u > last_uid][-40:]
        else:
            target_uids = uids[-25:]

        max_seen = last_uid
        for uid in target_uids:
            max_seen = max(max_seen, uid)
            ftyp, fdata = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
            if ftyp != "OK" or not fdata:
                continue
            for item in fdata:
                if isinstance(item, tuple) and isinstance(item[1], bytes):
                    deals.extend(parse_alert_email(item[1]))

        if not check_only and uids:
            new_cursor = {"uidvalidity": uidvalidity, "last_uid": max(max_seen, max(uids))}
            if new_cursor != cursor:
                with session_scope() as db:
                    set_json(db, "imap_cursor", new_cursor)
                    db.commit()
        return deals, {"ok": True, "checked": len(target_uids), "deals": len(deals)}
    except imaplib.IMAP4.error as exc:
        raise SourceError(f"Servidor IMAP recusou acesso: {exc}") from exc
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


class ImapAlertsFeed(FeedSource):
    key = "imap:alerts"
    name = "Alertas por E-mail (OLX, hardMOB, ML, Google)"
    interval_seconds = 120

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        deals, _ = await asyncio.to_thread(_poll_imap_sync, False)
        return deals, []


def test_imap_sync(db: Session) -> dict:
    _, info = _poll_imap_sync(check_only=True)
    return info
