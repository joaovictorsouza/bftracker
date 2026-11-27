"""Gatry: comunidade brasileira de promoções e cupons (API pública /v1/ permitida no robots.txt).

Traz ofertas verificadas pela comunidade em Mercado Livre, Amazon, Magazine Luiza, KaBuM!,
Shopee, AliExpress, Fast Shop e outras lojas — tanto na busca por produto quanto no radar.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote_plus

from ..core import dealtext, matching, stores
from ..core.text import clip
from .base import (
    FeedSource,
    Fetcher,
    FoundCoupon,
    FoundDeal,
    FoundOffer,
    SearchParams,
    SourceError,
    StoreSource,
)

BASE = "https://gatry.com"
CDN = "https://d3h0muvr7057ky.cloudfront.net"


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _image(raw: dict) -> str:
    keys = raw.get("image_keys") or []
    if keys and isinstance(keys[0], str):
        key = keys[0].lstrip("/")
        return key if key.startswith("http") else f"{CDN}/{key}"
    return ""


def _coupon_of(raw: dict) -> str:
    code = str(raw.get("code") or "").strip()
    if code and re.fullmatch(r"[A-Za-z0-9_\-]{3,30}", code):
        return code
    extra = f"{raw.get('description') or ''}\n{raw.get('last_comment_body') or ''}"
    return dealtext.find_coupon(extra)


def _store_of(raw: dict, link: str) -> tuple[str, str]:
    name = str(raw.get("store_name") or "").strip()
    domain = str(raw.get("store_domain") or "").strip()
    hint_url = link or (f"https://{domain}" if domain else "")
    return stores.identify(name, hint_url)


class GatrySearch(StoreSource):
    """Busca ofertas recentes aprovadas na comunidade do Gatry para um produto monitorado."""

    key = "gatry"
    name = "Gatry (comunidade)"
    covers = "Mercado Livre, Amazon, Magalu, KaBuM!, Shopee, AliExpress e outras"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        data = await fetcher.get_json(
            f"{BASE}/v1/promotions?q={quote_plus(params.query)}&limit=40"
        )
        return self.parse(data, params)

    def parse(self, data: dict, params: SearchParams) -> list[FoundOffer]:
        if not isinstance(data, dict) or not isinstance(data.get("promotions"), list):
            raise SourceError("Gatry: formato inesperado")
        out: list[FoundOffer] = []
        for raw in data["promotions"]:
            if not isinstance(raw, dict) or raw.get("status") not in (None, "active"):
                continue
            if raw.get("kind") == "coupon":
                continue
            title = " ".join(str(raw.get("title") or "").split())
            cents = raw.get("price_cents")
            if not title or not isinstance(cents, (int, float)) or cents <= 0:
                continue
            if not params.relevant(title):
                continue
            price = round(float(cents) / 100.0, 2)
            old_cents = raw.get("old_price_cents")
            original = (
                round(float(old_cents) / 100.0, 2)
                if isinstance(old_cents, (int, float)) and old_cents > cents
                else None
            )
            raw_url = str(raw.get("url") or "").strip()
            clean_url = stores.unwrap_url(raw_url)
            slug = str(raw.get("slug") or raw.get("id") or "")
            gatry_url = f"{BASE}/promocoes/{raw.get('id')}/{slug}".rstrip("/")
            store_key, store = _store_of(raw, clean_url)
            condition = matching.detect_condition(title, "new")
            if condition != "new" and not params.include_used:
                continue
            coupon = _coupon_of(raw)
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=str(raw.get("id") or slug),
                    store=store,
                    store_key=store_key,
                    title=title,
                    url=clean_url or gatry_url,
                    price=price,
                    original_price=original,
                    free_shipping=True if raw.get("free_shipping") else None,
                    coupon=coupon,
                    image=_image(raw),
                    marketplace=store_key in {"mercadolivre", "shopee", "aliexpress", "olx"},
                    condition=condition,
                )
            )
        return out


class GatryFeed(FeedSource):
    """Feed contínuo de promoções e cupons publicados no Gatry."""

    key = "gatry:feed"
    name = "Gatry · promoções e cupons"
    interval_seconds = 120

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        promos = await fetcher.get_json(f"{BASE}/v1/promotions?limit=40")
        coupons_data = await fetcher.get_json(f"{BASE}/v1/promotions?kind=coupon&limit=40")
        return self.parse(promos, coupons_data)

    def parse(
        self, promos_data: dict, coupons_data: dict | None = None
    ) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        if not isinstance(promos_data, dict) or not isinstance(promos_data.get("promotions"), list):
            raise SourceError("Gatry: formato inesperado")
        combined = list(promos_data["promotions"])
        if isinstance(coupons_data, dict) and isinstance(coupons_data.get("promotions"), list):
            combined.extend(coupons_data["promotions"])

        deals: dict[str, FoundDeal] = {}
        coupons: dict[str, FoundCoupon] = {}
        for raw in combined:
            if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title"):
                continue
            if raw.get("status") not in (None, "active"):
                continue
            ident = str(raw["id"])
            title = " ".join(str(raw["title"]).split())
            kind = raw.get("kind") or "promotion"
            raw_url = str(raw.get("url") or "").strip()
            link = stores.unwrap_url(raw_url)
            store_key, store = _store_of(raw, link)
            coupon_code = _coupon_of(raw)
            published = _iso(raw.get("approved_at") or raw.get("created_at"))
            slug = str(raw.get("slug") or ident)
            section = "cupons" if kind == "coupon" else "promocoes"
            page_url = f"{BASE}/{section}/{ident}/{slug}".rstrip("/")
            desc_parts = [
                str(raw.get("description") or "").strip(),
                str(raw.get("last_comment_body") or "").strip(),
            ]
            description = clip("\n".join(p for p in desc_parts if p), 700)

            cents = raw.get("price_cents")
            price = (
                round(float(cents) / 100.0, 2)
                if isinstance(cents, (int, float)) and cents > 1 and kind != "coupon"
                else None
            )
            old_cents = raw.get("old_price_cents")
            old_price = (
                round(float(old_cents) / 100.0, 2)
                if price and isinstance(old_cents, (int, float)) and old_cents > cents
                else None
            )

            deals[ident] = FoundDeal(
                source="gatry",
                source_name="Gatry",
                external_id=ident,
                title=title,
                url=page_url,
                link=link,
                description=description,
                image=_image(raw),
                store=store,
                price=price,
                old_price=old_price,
                coupon=coupon_code,
                published_at=published,
                is_coupon=kind == "coupon" or bool(coupon_code),
            )

            if kind == "coupon" or coupon_code:
                discount = str(raw.get("discount_text") or "").strip()
                if not discount and (m := re.search(r"(\d{1,2}\s?%\s*OFF|R\$\s*[\d.,]+\s*OFF)", title, re.I)):
                    discount = m.group(1)
                coupons[ident] = FoundCoupon(
                    source="gatry",
                    store=store,
                    title=title,
                    code=coupon_code,
                    discount=discount,
                    conditions=description,
                    url=link or page_url,
                    expires_at=_iso(raw.get("valid_until")),
                    is_flash="relâmpago" in title.lower() or "corre" in title.lower(),
                )
        return list(deals.values()), list(coupons.values())
