"""Busca na Amazon.com.br (preço, parcelamento e cupom exibido no anúncio)."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from selectolax.parser import HTMLParser

from ..core.text import parse_brl
from .base import Fetcher, FoundOffer, SearchParams, SourceError, StoreSource

_INSTALLMENT_RE = re.compile(
    r"(\d{1,2})x de R\$\s*([\d.,]+)(\s*sem juros)?", re.IGNORECASE
)
_COUPON_RE = re.compile(
    r"((?:economize|aplique|cupom de|desconto de)\s*(?:R\$\s*[\d.,]+|\d{1,2}\s?%)"
    r"[^.|]{0,40}?(?:cupom|código)[^.|]{0,20}|cupom de (?:R\$\s*[\d.,]+|\d{1,2}\s?%)"
    r"(?:\s*(?:off|de desconto))?)",
    re.IGNORECASE,
)


class Amazon(StoreSource):
    key = "amazon"
    name = "Amazon"
    covers = "Amazon.com.br"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        page = await fetcher.get_text(f"https://www.amazon.com.br/s?k={quote_plus(params.query)}")
        return self.parse(page, params)

    def parse(self, page: str, params: SearchParams) -> list[FoundOffer]:
        tree = HTMLParser(page)
        cards = tree.css('div[data-component-type="s-search-result"]')
        if not cards and "s-result" not in page:
            raise SourceError("Amazon: resultados não encontrados na página")
        out: list[FoundOffer] = []
        for card in cards:
            asin = card.attributes.get("data-asin") or ""
            heading = card.css_first("h2")
            price_node = card.css_first("span.a-price:not([data-a-strike]) span.a-offscreen")
            if not asin or not heading or not price_node:
                continue
            spans = [s.text(strip=True) for s in card.css("h2 span")]
            title = max(spans + [heading.text(separator=" ", strip=True)], key=len)
            title = re.sub(r"^Anúncio patrocinado\s*[–-]\s*", "", title)
            price = parse_brl(price_node.text(strip=True))
            if not price or not params.relevant(title):
                continue
            text = " ".join(card.text(separator=" ").split())
            original = card.css_first('span.a-price[data-a-strike="true"] span.a-offscreen')
            inst = _INSTALLMENT_RE.search(text)
            count = int(inst.group(1)) if inst else None
            value = parse_brl(inst.group(2)) if inst else None
            coupon = _COUPON_RE.search(text)
            image = card.css_first("img.s-image")
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=asin,
                    store="Amazon",
                    store_key="amazon",
                    title=title,
                    url=f"https://www.amazon.com.br/dp/{asin}",
                    price=price,
                    original_price=parse_brl(original.text(strip=True)) if original else None,
                    image=(image.attributes.get("src") or "") if image else "",
                    installments=count,
                    installment_value=value,
                    card_price=round(count * value, 2) if count and value else None,
                    interest_free=bool(inst.group(3)) if inst else None,
                    pix=bool(re.search(r"\bno pix\b", text, re.I)),
                    free_shipping=True if re.search(r"frete gr[áa]tis", text, re.I) else None,
                    coupon=" ".join(coupon.group(1).split())[:200] if coupon else "",
                    condition="used" if "/ usado" in text.lower() else "new",
                )
            )
        return out
