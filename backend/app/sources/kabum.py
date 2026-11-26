"""API pública de catálogo do KaBuM!"""

from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

from ..core.text import parse_brl
from .base import Fetcher, FoundOffer, SearchParams, SourceError, StoreSource

API = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products"


class Kabum(StoreSource):
    key = "kabum"
    name = "KaBuM!"
    covers = "KaBuM!"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        data = await fetcher.get_json(
            f"{API}?query={quote_plus(params.query)}&page_number=1&page_size=60"
        )
        return self.parse(data, params)

    def parse(self, data: dict, params: SearchParams, now: float | None = None) -> list[FoundOffer]:
        if not isinstance(data, dict) or "data" not in data:
            raise SourceError("KaBuM!: formato inesperado")
        now = now or time.time()
        out: list[FoundOffer] = []
        for item in data["data"]:
            attr = item.get("attributes") or {}
            title = attr.get("title") or ""
            if not attr.get("available") or not params.relevant(title):
                continue
            price = parse_brl(attr.get("price_with_discount")) or parse_brl(attr.get("price"))
            card = parse_brl(attr.get("price"))
            coupon = ""
            offer = attr.get("offer") or {}
            if offer and offer.get("starts_at", 0) <= now <= offer.get("ends_at", 0):
                price = parse_brl(offer.get("price_with_discount")) or price
                card = parse_brl(offer.get("price")) or card
                coupon = f"Oferta relâmpago: {offer.get('name', '')}".strip()
            if not price:
                continue
            inst = re.search(r"(\d+)x de R\$\s*([\d.,]+)", attr.get("max_installment") or "")
            marketplace = attr.get("marketplace") or {}
            seller = marketplace.get("seller_name", "") if attr.get("is_marketplace") else ""
            photos = attr.get("images") or (attr.get("photos") or {}).get("m") or []
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=str(item.get("id")),
                    store="KaBuM!",
                    store_key="kabum",
                    title=title,
                    url=f"https://www.kabum.com.br/produto/{item.get('id')}/"
                    f"{attr.get('product_link', '')}",
                    price=price,
                    card_price=card,
                    original_price=parse_brl(attr.get("old_price")),
                    installments=int(inst.group(1)) if inst else None,
                    installment_value=parse_brl(inst.group(2)) if inst else None,
                    interest_free=True if inst else None,
                    pix=bool(card and price < card),
                    free_shipping=bool(attr.get("has_free_shipping")),
                    seller=seller,
                    marketplace=bool(attr.get("is_marketplace")),
                    image=photos[0] if photos else "",
                    coupon=coupon,
                    condition="used" if attr.get("is_openbox") else "new",
                )
            )
        return out
