"""Busca Web / Shopping opcional (Serper.dev ou Brave Search API).

Permite acompanhar automaticamente **Mercado Livre (sem a API oficial de 10 dias)**, **OLX**,
**Magazine Luiza**, **Casas Bahia**, **Shopee**, **Pichau**, **Terabyte**, **HardMob** e **X**
usando APIs oficiais de busca com cota gratuita imediata.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

from ..core import dealtext, matching, stores
from ..core.appsettings import get_value
from ..core.text import normalize, parse_brl, short_hash, slug
from ..db import session_scope
from .base import Fetcher, FoundOffer, NotConfigured, SearchParams, SourceError, StoreSource
from .olx import STATES


def _external_id_for(url: str, fallback: str = "") -> str:
    if m := re.search(r"item_id[:=]+(MLB\d+)", url):
        return m.group(1)
    if m := re.search(r"/(MLB)-?(\d{6,})", url):
        return "".join(m.groups())
    if m := re.search(r"-(\d{6,})(?:\?|$|/)", url):
        return m.group(1)
    if fallback:
        return str(fallback)
    parts = urlsplit(url)
    return short_hash(f"{parts.hostname}{parts.path}")


class WebSearchStore(StoreSource):
    key = "websearch"
    name = "Busca Web / Shopping (ML, OLX e lojas)"
    covers = "Mercado Livre (sem API oficial), OLX, Magalu, Casas Bahia, Shopee e outras"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        with session_scope() as db:
            serper_key = get_value(db, "serper_api_key").strip()
            brave_key = get_value(db, "brave_api_key").strip()

        if not serper_key and not brave_key:
            raise NotConfigured(
                "Opcional: informe SERPER_API_KEY (ou BRAVE_API_KEY) em Configurações → "
                "Integrações para busca direta no Google Shopping / OLX / ML sem API do ML"
            )

        found: dict[tuple[str, str], FoundOffer] = {}
        if serper_key:
            for offer in await self._search_serper(fetcher, serper_key, params):
                found[(offer.store_key, offer.external_id)] = offer
        if brave_key and not found:
            for offer in await self._search_brave(fetcher, brave_key, params):
                found[(offer.store_key, offer.external_id)] = offer
        return list(found.values())

    async def _search_serper(
        self, fetcher: Fetcher, api_key: str, params: SearchParams
    ) -> list[FoundOffer]:
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        resp = await fetcher.request(
            "POST",
            "https://google.serper.dev/shopping",
            headers=headers,
            json={"q": params.query, "gl": "br", "hl": "pt-br", "num": 40},
        )
        data = resp.json()
        out = self.parse_serper_shopping(data, params)

        if params.include_used:
            uf = params.used_state.lower()
            site = f"site:olx.com.br/estado-{uf}" if uf in STATES else "site:olx.com.br"
            region = f' "{params.used_region}"' if params.used_region else ""
            q = f'{params.query}{region} {site} "R$"'
            try:
                web_resp = await fetcher.request(
                    "POST",
                    "https://google.serper.dev/search",
                    headers=headers,
                    json={"q": q, "gl": "br", "hl": "pt-br", "tbs": "qdr:w", "num": 20},
                )
                out.extend(self.parse_web_results(web_resp.json().get("organic") or [], params))
            except SourceError:
                pass
        return out

    def parse_serper_shopping(self, data: dict, params: SearchParams) -> list[FoundOffer]:
        if not isinstance(data, dict):
            raise SourceError("Serper: formato inesperado")
        items = data.get("shopping") or []
        out: list[FoundOffer] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = " ".join(str(raw.get("title") or "").split())
            url = stores.unwrap_url(str(raw.get("link") or "").strip())
            price = parse_brl(raw.get("price"))
            if not title or not url or not price or not params.relevant(title):
                continue
            merchant = str(raw.get("source") or "").strip()
            store_key, store = stores.identify(merchant, url)
            second_hand = str(raw.get("secondHandCondition") or "").lower()
            condition = "new"
            if "recond" in second_hand or "refurb" in second_hand:
                condition = "refurbished"
            elif second_hand or store_key == "olx":
                condition = "used"
            else:
                condition = matching.detect_condition(title, "new")
            if condition != "new" and not params.include_used:
                continue
            delivery = str(raw.get("delivery") or "").lower()
            free_ship = True if ("grátis" in delivery or "gratis" in delivery) else None
            ext = _external_id_for(url, str(raw.get("productId") or ""))
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=ext,
                    store=store,
                    store_key=store_key,
                    title=title,
                    url=url,
                    price=price,
                    image=str(raw.get("imageUrl") or ""),
                    free_shipping=free_ship,
                    marketplace=store_key in {"mercadolivre", "olx", "shopee", "aliexpress"},
                    condition=condition,
                )
            )
        return out

    async def _search_brave(
        self, fetcher: Fetcher, api_key: str, params: SearchParams
    ) -> list[FoundOffer]:
        sites = ["site:mercadolivre.com.br", "site:produto.mercadolivre.com.br"]
        if params.include_used:
            sites.append("site:olx.com.br")
        q = f'{params.query} ({" OR ".join(sites)}) "R$"'
        data = await fetcher.get_json(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": q, "country": "BR", "search_lang": "pt-br", "count": 20},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
        )
        results = ((data.get("web") or {}).get("results")) if isinstance(data, dict) else []
        return self.parse_web_results(results or [], params)

    def parse_web_results(self, rows: list[dict], params: SearchParams) -> list[FoundOffer]:
        region_slug = slug(params.used_region)
        region_norm = normalize(params.used_region)
        out: list[FoundOffer] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = stores.unwrap_url(str(row.get("link") or row.get("url") or "").strip())
            raw_title = " ".join(str(row.get("title") or "").split())
            title = re.sub(r"\s*[|\-–]\s*(OLX|Mercado Livre).*$", "", raw_title, flags=re.I)
            snippet = " ".join(
                str(row.get("snippet") or row.get("description") or "").split()
            )
            if not url or not title or not params.relevant(title):
                continue
            # ignora páginas genéricas de busca
            if any(p in url for p in ("lista.mercadolivre.com.br", "?q=")):
                continue
            price, old = dealtext.find_prices(f"{raw_title}\n{snippet}")
            if not price:
                continue
            store_key, store = stores.identify("", url)
            if store_key == "olx":
                condition = "used"
                if region_slug and region_slug not in url and region_norm not in normalize(snippet):
                    continue
            else:
                condition = matching.detect_condition(title, "new")
            if condition != "new" and not params.include_used:
                continue
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=_external_id_for(url),
                    store=store,
                    store_key=store_key,
                    title=title,
                    url=url,
                    price=price,
                    original_price=old,
                    marketplace=store_key in {"mercadolivre", "olx", "shopee"},
                    condition=condition,
                )
            )
        return out


def test_websearch_sync(db, query: str = "PS5") -> dict:
    criteria = matching.Criteria(query)
    params = SearchParams(
        query=query,
        include_used=True,
        is_relevant=lambda t: matching.matches(t, criteria),
    )

    async def _run():
        async with Fetcher(min_delay=0.2) as fetcher:
            offers = await WebSearchStore().search(fetcher, params)
            by_store: dict[str, int] = {}
            for o in offers:
                by_store[o.store] = by_store.get(o.store, 0) + 1
            return {"ok": True, "count": len(offers), "stores": by_store}

    return asyncio.run(_run())
