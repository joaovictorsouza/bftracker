"""Anúncios de usados na OLX, por estado e região."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlparse

from selectolax.parser import HTMLParser

from ..core.text import normalize, parse_brl, slug
from .base import Fetcher, FoundOffer, SearchParams, SourceError, StoreSource

STATES = (
    "ac al ap am ba ce df es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc sp se to".split()
)


class Olx(StoreSource):
    key = "olx"
    name = "OLX"
    covers = "OLX (usados na sua região)"
    used_only = True
    pages = 2

    def urls(self, params: SearchParams) -> list[str]:
        state = params.used_state.lower()
        base = "https://www.olx.com.br/"
        base += f"estado-{state}" if state in STATES else "brasil"
        query = quote_plus(params.query)
        price = ""
        if params.max_price:
            price += f"&pe={int(params.max_price)}"
        if params.min_price:
            price += f"&ps={int(params.min_price)}"
        # relevância + mais recentes (sf=1) para pegar anúncios novos rapidamente
        urls = [f"{base}?q={query}&sf=1{price}"]
        urls += [f"{base}?q={query}{price}&o={n}" for n in range(1, self.pages)]
        return urls

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        found: dict[str, FoundOffer] = {}
        for url in self.urls(params):
            try:
                page = await fetcher.get_text(url)
            except SourceError:
                if found:
                    break
                raise
            for offer in self.parse(page, params):
                found[offer.external_id] = offer
        return list(found.values())

    def parse(self, page: str, params: SearchParams) -> list[FoundOffer]:
        tree = HTMLParser(page)
        cards = tree.css("section.olx-adcard")
        if not cards and "olx" not in page.lower():
            raise SourceError("OLX: página inesperada")
        region = slug(params.used_region)
        region_text = normalize(params.used_region)
        out: list[FoundOffer] = []
        for card in cards:
            link = card.css_first('a[data-testid="adcard-link"]')
            price_node = card.css_first("h3.olx-adcard__price")
            if not link or not price_node:
                continue
            url = link.attributes.get("href") or ""
            title = link.attributes.get("title") or link.text(strip=True)
            title = re.sub(r"<[^>]+>", " ", title).strip()
            price = parse_brl(price_node.text(strip=True))
            ad_id = re.search(r"-(\d{6,})(?:\?|$)", url)
            if not price or not ad_id or not params.relevant(title):
                continue
            location_node = card.css_first("p.olx-adcard__location")
            location = location_node.text(strip=True) if location_node else ""
            parts = urlparse(url).path.strip("/").split("/")
            ad_region = parts[0] if parts else ""
            if region and region not in ad_region and region_text not in normalize(location):
                continue
            info = card.css_first('[data-testid="adcard-price-info"]')
            inst = re.search(r"(\d{1,2})x de R\$\s*([\d.,]+)", info.text(separator=" ")) \
                if info else None
            image = card.css_first("picture img") or card.css_first("img")
            badges = " ".join(b.text() for b in card.css(".olx-adcard__badges div"))
            seller = card.css_first('[class*="transactionalSellerName"]')
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=ad_id.group(1),
                    store="OLX",
                    store_key="olx",
                    title=title,
                    url=url,
                    price=price,
                    installments=int(inst.group(1)) if inst else None,
                    installment_value=parse_brl(inst.group(2)) if inst else None,
                    free_shipping=True if "Frete grátis" in badges else None,
                    seller=seller.text(strip=True) if seller else "",
                    marketplace=True,
                    image=(image.attributes.get("src") or "") if image else "",
                    condition="used",
                    location=location,
                )
            )
        return out
