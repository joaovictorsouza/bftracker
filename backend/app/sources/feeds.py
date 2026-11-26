"""Fontes contínuas de ofertas e cupons: sites de tecnologia (RSS), canais públicos do
Telegram, Promobit e o fórum de promoções do hardMOB."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime
from urllib.parse import urljoin

import feedparser
from selectolax.parser import HTMLParser

from ..core import stores
from ..core.dealtext import looks_like_deal
from ..core.text import clip, parse_brl
from .base import FeedSource, Fetcher, FoundCoupon, FoundDeal, SourceError
from .htmlutil import next_data

RSS_FEEDS: dict[str, tuple[str, str]] = {
    "tudocelular": ("TudoCelular", "https://www.tudocelular.com/feed/"),
    "canaltech": ("Canaltech", "https://canaltech.com.br/rss/"),
    "tecnoblog": ("Tecnoblog", "https://tecnoblog.net/feed/"),
    "adrenaline": ("Adrenaline", "https://www.adrenaline.com.br/feed/"),
    "mundoconectado": ("Mundo Conectado", "https://mundoconectado.com.br/feed/"),
    "meups": ("MeuPlayStation", "https://meups.com.br/feed/"),
}

# canal -> nome (todos com prévia pública em https://t.me/s/<canal>)
TELEGRAM_CHANNELS: dict[str, str] = {
    "pelandobr": "Pelando",
    "pechinchou": "Pechinchou",
    "nerdofertas": "Nerd Ofertas",
    "achadosdotb": "Achados do Tecnoblog",
    "tudocelular": "TudoCelular (Telegram)",
    "canaltechofertas": "Baita Compra Tech",
    "ofertasadrenaline": "Ofertas Adrenaline",
    "BenchPromos": "Bench Promos",
    "seleofertas": "Ofertas Seletronic",
    "promotop": "PromoTop",
    "pcdofafapromo": "PC do Fafa Promoções",
    "ofertaskabum": "KaBuM! (Telegram)",
}


def _plain(html_text: str) -> str:
    if not html_text:
        return ""
    tree = HTMLParser(html_text.replace("<br", "\n<br").replace("</p>", "</p>\n"))
    body = tree.body
    return re.sub(r"[ \t]+", " ", body.text(separator="") if body else "").strip()


class RssFeed(FeedSource):
    interval_seconds = 240

    def __init__(self, key: str, name: str, url: str, guard: bool = False):
        self.key = f"rss:{key}"
        self.name = name
        self.url = url
        self.guard = guard

    async def fetch(self, fetcher: Fetcher):
        response = await fetcher.request("GET", self.url, guard=self.guard)
        return self.parse(response.content), []

    def parse(self, content: bytes) -> list[FoundDeal]:
        parsed = feedparser.parse(content)
        if parsed.bozo and not parsed.entries:
            raise SourceError(f"{self.name}: feed ilegível")
        out = []
        for entry in parsed.entries:
            title = " ".join(entry.get("title", "").split())
            categories = [t.get("term", "") for t in entry.get("tags", [])]
            if not title or not looks_like_deal(title, categories):
                continue
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            summary = entry.get("summary", "")
            image = ""
            media = entry.get("media_content") or entry.get("media_thumbnail") or []
            if media:
                image = media[0].get("url", "")
            if not image and (m := re.search(r'<img[^>]+src="(https://[^"]+)"', summary)):
                image = m.group(1)
            out.append(
                FoundDeal(
                    source=self.key,
                    source_name=self.name,
                    external_id=entry.get("id") or entry.get("link", title),
                    title=title,
                    url=entry.get("link", ""),
                    description=clip(_plain(summary), 600),
                    image=image,
                    published_at=datetime.fromtimestamp(calendar.timegm(stamp), UTC)
                    if stamp else None,
                )
            )
        return out


class TelegramChannel(FeedSource):
    interval_seconds = 75

    def __init__(self, channel: str, name: str = ""):
        self.channel = channel
        self.key = f"tg:{channel.lower()}"
        self.name = name or f"@{channel}"

    async def fetch(self, fetcher: Fetcher):
        page = await fetcher.get_text(f"https://t.me/s/{self.channel}")
        return self.parse(page), []

    def parse(self, page: str) -> list[FoundDeal]:
        tree = HTMLParser(page.replace("<br/>", "\n").replace("<br>", "\n"))
        messages = tree.css("div.tgme_widget_message[data-post]")
        if not messages:
            raise SourceError(f"Canal @{self.channel} sem prévia pública")
        out = []
        for message in messages:
            body = message.css_first("div.tgme_widget_message_text.js-message_text")
            if not body:
                continue
            text = body.text(separator="").replace("\xa0", " ").strip()
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            if not lines:
                continue
            links = [
                a.attributes.get("href", "")
                for a in body.css("a")
                if str(a.attributes.get("href", "")).startswith("http")
            ]
            for button in message.css("a.tgme_widget_message_inline_button"):
                links.append(button.attributes.get("href", ""))
            link = next((u for u in links if "t.me/" not in u), "")
            if not link and "R$" not in text and "cupom" not in text.lower():
                continue  # conversa ou aviso, não é oferta
            title = lines[0]
            if len(title) < 25 and len(lines) > 1:
                title = f"{title} — {lines[1]}"
            code = [c.text(strip=True) for c in body.css("code")]
            coupon = next((c for c in code if re.fullmatch(r"[A-Za-z0-9_\-]{4,25}", c)), "")
            if "cupom" not in text.lower():
                coupon = ""
            photo = message.css_first("a.tgme_widget_message_photo_wrap")
            image = ""
            if photo and (m := re.search(r"url\('([^']+)'\)", photo.attributes.get("style", ""))):
                image = m.group(1)
            stamp = message.css_first("a.tgme_widget_message_date time")
            published = None
            if stamp and stamp.attributes.get("datetime"):
                published = datetime.fromisoformat(stamp.attributes["datetime"])
            post = message.attributes["data-post"]
            out.append(
                FoundDeal(
                    source=self.key,
                    source_name=self.name,
                    external_id=post,
                    title=clip(title, 220),
                    url=f"https://t.me/{post}",
                    link=link,
                    description=clip("\n".join(lines), 900),
                    image=image,
                    coupon=coupon,
                    published_at=published,
                )
            )
        return out


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value))
    except ValueError:
        return None


class Promobit(FeedSource):
    """Ofertas verificadas e cupons por loja publicados no Promobit."""

    interval_seconds = 180
    base = "https://www.promobit.com.br"

    def __init__(self, key: str, name: str, path: str):
        self.key = f"promobit:{key}"
        self.name = name
        self.path = path

    async def fetch(self, fetcher: Fetcher):
        page = await fetcher.get_text(self.base + self.path)
        return self.parse(page)

    def parse(self, page: str):
        props = next_data(page).get("props", {}).get("pageProps", {})
        offers: list[dict] = []
        for key in ("serverOffers", "serverFeaturedOffers", "serverTimeline"):
            block = props.get(key)
            if isinstance(block, dict):
                offers.extend(block.get("offers") or [])
            elif isinstance(block, list):
                offers.extend(block)
        deals: dict[str, FoundDeal] = {}
        for raw in offers:
            if not isinstance(raw, dict) or not raw.get("offerId") or not raw.get("offerTitle"):
                continue
            kind = raw.get("offerPriceType")
            price = parse_brl(raw.get("offerPrice"))
            old = parse_brl(raw.get("offerOldPrice"))
            if kind == "COUPON" or (price is not None and price <= 0.01):
                price = None
            if old is not None and (price is None or old <= price):
                old = None
            photo = raw.get("offerPhoto") or ""
            deals[str(raw["offerId"])] = FoundDeal(
                source="promobit",
                source_name="Promobit",
                external_id=str(raw["offerId"]),
                title=raw["offerTitle"],
                url=f"{self.base}/oferta/{raw.get('offerSlug', raw['offerId'])}/",
                image=f"https://i.promobit.com.br/268{photo}" if photo.startswith("/") else photo,
                store=raw.get("storeName") or "",
                price=price,
                old_price=old,
                coupon=raw.get("offerCoupon") or "",
                category=raw.get("categorySlug") or "",
                published_at=_iso(raw.get("offerPublished")),
                is_coupon=bool(raw.get("offerCoupon")) or kind == "COUPON",
                description=" ".join(
                    t.get("name", "") for t in raw.get("offerTags") or [] if isinstance(t, dict)
                ),
            )
        raw_coupons: list[dict] = list(props.get("couponsByStore") or [])
        for key in ("serverCoupons",):
            block = props.get(key)
            if isinstance(block, dict):
                raw_coupons.extend(block.get("coupons") or [])
            elif isinstance(block, list):
                raw_coupons.extend(block)
        coupons: dict[str, FoundCoupon] = {}
        for raw in raw_coupons:
            title = raw.get("couponTitle")
            store = raw.get("storeName")
            if not title or not store:
                continue
            code = str(raw.get("couponCode") or "")
            if not re.fullmatch(r"[A-Za-z0-9_\-]{3,30}", code):
                code = ""
            path = raw.get("couponUrl") or ""
            conditions = _plain(str(raw.get("couponInstructions") or ""))
            tags = raw.get("couponTag") or []
            if tags:
                conditions = f"{' · '.join(map(str, tags))}\n{conditions}".strip()
            coupons[str(raw.get("couponId"))] = FoundCoupon(
                source="promobit",
                store=store,
                title=title,
                code=code,
                discount=str(raw.get("couponDiscount") or ""),
                conditions=clip(conditions, 600),
                url=urljoin(self.base, path) if path else self.base + self.path,
                expires_at=_iso(raw.get("couponUntil")),
                is_flash="relâmpago" in str(title).lower(),
            )
        return list(deals.values()), list(coupons.values())


PROMOBIT_PAGES: list[tuple[str, str, str]] = [
    ("home", "Promobit · destaques", "/"),
    ("games", "Promobit · games", "/promocoes/games/"),
    ("celulares", "Promobit · celulares", "/promocoes/smartphones-tablets-e-telefones/"),
    ("informatica", "Promobit · informática", "/promocoes/informatica/"),
    ("amazon", "Promobit · Amazon", "/promocoes/loja/amazon/"),
    ("mercadolivre", "Promobit · Mercado Livre", "/promocoes/loja/mercado-livre/"),
    ("magalu", "Promobit · Magalu", "/promocoes/loja/magazine-luiza/"),
    ("kabum", "Promobit · KaBuM!", "/promocoes/loja/kabum/"),
    ("shopee", "Promobit · Shopee", "/promocoes/loja/shopee/"),
    ("aliexpress", "Promobit · AliExpress", "/promocoes/loja/aliexpress/"),
    ("casasbahia", "Promobit · Casas Bahia", "/promocoes/loja/casas-bahia/"),
]


class Hardmob(FeedSource):
    key = "hardmob"
    name = "hardMOB Promoções"
    interval_seconds = 150
    url = "https://www.hardmob.com.br/forums/407-Promocoes"

    async def fetch(self, fetcher: Fetcher):
        response = await fetcher.request("GET", self.url)
        return self.parse(response.content.decode("cp1252", errors="replace")), []

    def parse(self, page: str) -> list[FoundDeal]:
        tree = HTMLParser(page)
        rows = tree.css("li.threadbit")
        if not rows:
            raise SourceError("hardMOB: lista de tópicos não encontrada")
        out = []
        for row in rows:
            if "sticky" in (row.css_first("div").attributes.get("class") or "").split():
                continue
            link = row.css_first("a.title")
            if not link or "threadbit hot sticky" in row.attributes.get("class", ""):
                continue
            title = link.text(strip=True)
            href = re.sub(r"\?s=\w+", "", link.attributes.get("href", ""))
            thread = re.search(r"threads/(\d+)", href)
            if not thread or not re.search(r"R\$|cupom|%|gr[áa]tis", title, re.I):
                continue
            info = row.css_first("div.threadinfo")
            description = info.attributes.get("title", "") if info else ""
            shop = re.search(r"https?://(?!(?:www\.)?hardmob)\S+", description)
            out.append(
                FoundDeal(
                    source=self.key,
                    source_name=self.name,
                    external_id=thread.group(1),
                    title=title,
                    url=urljoin("https://www.hardmob.com.br/", href),
                    link=shop.group(0) if shop else "",
                    description=clip(description, 500),
                    store=stores.find_in_text(title).name if stores.find_in_text(title) else "",
                )
            )
        return out
