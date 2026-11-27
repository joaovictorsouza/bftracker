"""Pelando: ofertas ao vivo da comunidade e páginas públicas de cupons por loja
(incluindo cupons ativos e resgates agendados do Mercado Livre, Amazon, Magalu, Shopee e KaBuM!)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from ..core import dealtext
from ..core.text import clip, parse_brl
from .base import FeedSource, Fetcher, FoundCoupon, FoundDeal, SourceError
from .htmlutil import json_ld

BASE = "https://www.pelando.com.br"

PELANDO_DEAL_PAGES: list[tuple[str, str, str]] = [
    ("recentes", "Pelando · recentes", "/recentes"),
    ("quentes", "Pelando · mais quentes", "/mais-quentes"),
    ("tech", "Pelando · tecnologia", "/c/tech-lover"),
    ("gamer", "Pelando · games", "/c/mundo-gamer"),
]

PELANDO_COUPON_STORES: list[tuple[str, str, str]] = [
    ("mercadolivre", "Pelando · Cupons Mercado Livre", "/cupons-de-descontos/mercado-livre"),
    ("amazon", "Pelando · Cupons Amazon", "/cupons-de-descontos/amazon"),
    ("magalu", "Pelando · Cupons Magalu", "/cupons-de-descontos/magalu"),
    ("shopee", "Pelando · Cupons Shopee", "/cupons-de-descontos/shopee"),
    ("aliexpress", "Pelando · Cupons AliExpress", "/cupons-de-descontos/aliexpress"),
]

_STORE_NAMES = {
    "mercadolivre": "Mercado Livre",
    "amazon": "Amazon",
    "magalu": "Magazine Luiza",
    "shopee": "Shopee",
    "aliexpress": "AliExpress",
}


def _best_image(img_node) -> str:
    if img_node is None:
        return ""
    srcset = img_node.attributes.get("srcset") or ""
    candidates = [
        part.strip().split()[0]
        for part in srcset.split(",")
        if part.strip().startswith("https://")
    ]
    if candidates:
        return candidates[-1]
    src = img_node.attributes.get("src") or ""
    return src if src.startswith("https://") else ""


class PelandoDeals(FeedSource):
    """Ofertas publicadas na comunidade do Pelando."""

    interval_seconds = 105

    def __init__(self, key: str, name: str, path: str):
        self.key = f"pelando:{key}"
        self.name = name
        self.path = path

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        page = await fetcher.get_text(BASE + self.path)
        return self.parse(page), []

    def parse(self, page: str) -> list[FoundDeal]:
        tree = HTMLParser(page)
        cards = tree.css('div[class*="_deal-card_"]')
        if not cards and "pelando" not in page.lower():
            raise SourceError(f"{self.name}: página inesperada")
        deals: dict[str, FoundDeal] = {}
        for card in cards:
            link_node = card.css_first('h3 a[href*="/d/"], a[data-deal-id]')
            if link_node is None:
                continue
            if link_node.attributes.get("data-inactive") == "true":
                continue
            href = link_node.attributes.get("href") or ""
            url = urljoin(BASE, href)
            deal_id = (
                link_node.attributes.get("data-deal-id")
                or href.rstrip("/").rsplit("/", 1)[-1]
            )
            title = " ".join(link_node.text(strip=True).split())
            if not deal_id or not title:
                continue
            stamp = card.css_first('span[class*="_deal-card-stamp_"]')
            price = parse_brl(stamp.text(strip=True)) if stamp else None
            if price is not None and price <= 0.01:
                price = None
            store_link = card.css_first('a[href*="/cupons-de-descontos/"]')
            store = store_link.text(strip=True) if store_link else ""
            if not store:
                store_wrap = card.css_first('div[class*="deal-card-store"]')
                if store_wrap:
                    raw_store = store_wrap.text(separator=" ", strip=True)
                    store = re.sub(r"^[\s|]*vendido por\s*", "", raw_store, flags=re.I).strip()
            coupon_node = card.css_first('[class*="coupon-code"], code')
            coupon = coupon_node.text(strip=True) if coupon_node else dealtext.find_coupon(title)
            if coupon and not re.fullmatch(r"[A-Za-z0-9_\-]{3,28}", coupon):
                coupon = ""
            deals[deal_id] = FoundDeal(
                source="pelando",
                source_name="Pelando",
                external_id=deal_id,
                title=title,
                url=url,
                image=_best_image(card.css_first("img")),
                store=store,
                price=price,
                coupon=coupon,
                is_coupon=bool(coupon) or ("cupom" in title.lower() and price is None),
            )
        return list(deals.values())


class PelandoCoupons(FeedSource):
    """Cupons ativos e resgates relâmpago por loja publicados no Pelando (schema.org/Offer)."""

    interval_seconds = 180

    def __init__(self, store_key: str, name: str, path: str):
        self.store_key = store_key
        self.store_name = _STORE_NAMES.get(store_key, store_key.title())
        self.key = f"pelando:cupons_{store_key}"
        self.name = name
        self.path = path

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        page = await fetcher.get_text(BASE + self.path)
        return self.parse(page)

    def parse(self, page: str) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        if "pelando" not in page.lower():
            raise SourceError(f"{self.name}: página inesperada")
        coupons: dict[str, FoundCoupon] = {}
        deals: dict[str, FoundDeal] = {}
        for node in json_ld(page):
            if node.get("@type") != "Offer":
                continue
            availability = str(node.get("availability") or "")
            if "OutOfStock" in availability:
                continue
            title = " ".join(str(node.get("name") or "").split())
            url = urljoin(BASE, str(node.get("url") or self.path))
            if not title:
                continue
            ident = str(node.get("@id") or url).rsplit("#", 1)[-1]
            description = " ".join(str(node.get("description") or "").split())
            code = dealtext.find_coupon(f"{title}\n{description}")
            discount = ""
            if m := re.search(r"(\d{1,2}\s?%\s*OFF|R\$\s*[\d.,]+\s*OFF)", title, re.I):
                discount = m.group(1)
            lower = title.lower()
            is_flash = any(
                term in lower for term in ("resgate", "relâmpago", "relampago", "só hoje")
            )
            coupons[ident] = FoundCoupon(
                source="pelando",
                store=self.store_name,
                title=title,
                code=code,
                discount=discount,
                conditions=clip(description, 600),
                url=url,
                is_flash=is_flash,
            )
            if is_flash or code:
                deals[ident] = FoundDeal(
                    source="pelando",
                    source_name="Pelando",
                    external_id=f"coupon:{ident}",
                    title=title,
                    url=url,
                    description=clip(description, 600),
                    store=self.store_name,
                    coupon=code,
                    is_coupon=True,
                    is_flash=is_flash,
                )
        return list(deals.values()), list(coupons.values())
