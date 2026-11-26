"""Mercado Livre pela API oficial (catálogo e ofertas por produto, novos e usados).

A API exige uma aplicação aprovada em developers.mercadolivre.com.br e a autorização da
sua conta (botão "Conectar Mercado Livre" nas Configurações). Sem isso, as ofertas do
Mercado Livre continuam chegando pelos comparadores e pelos canais de promoções.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote_plus

from ..core.text import parse_brl
from . import mlauth
from .base import Fetcher, FoundOffer, NotConfigured, SearchParams, SourceError, StoreSource

API = "https://api.mercadolibre.com"

# o refresh token é de uso único: só uma renovação por vez
_refresh_lock = asyncio.Lock()


class MercadoLivre(StoreSource):
    key = "mercadolivre"
    name = "Mercado Livre (API)"
    covers = "Mercado Livre"
    max_products = 8

    def __init__(self, token_provider=mlauth.access_token):
        self.token_provider = token_provider

    async def _auth(self) -> dict:
        async with _refresh_lock:
            try:
                token = await asyncio.to_thread(self.token_provider)
            except mlauth.AuthError as exc:
                raise SourceError(str(exc)) from exc
        if not token:
            raise NotConfigured(
                "Conecte sua conta do Mercado Livre em Configurações para a busca direta"
            )
        return {"Authorization": f"Bearer {token}"}

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        headers = await self._auth()
        data = await fetcher.get_json(
            f"{API}/products/search?status=active&site_id=MLB&limit=20&q="
            f"{quote_plus(params.query)}",
            headers=headers,
        )
        products = [
            p for p in data.get("results", []) if params.relevant(p.get("name") or "")
        ][: self.max_products]
        out: list[FoundOffer] = []
        for product in products:
            try:
                items = await fetcher.get_json(
                    f"{API}/products/{product['id']}/items?limit=20", headers=headers
                )
            except SourceError:
                continue  # produto de catálogo sem anúncios ativos responde 404
            out.extend(self.parse_items(product, items, params))
        return out

    def parse_items(self, product: dict, data: dict, params: SearchParams) -> list[FoundOffer]:
        name = product.get("name") or ""
        pictures = product.get("pictures") or []
        image = pictures[0].get("url", "") if pictures else ""
        out = []
        for item in data.get("results", []):
            price = parse_brl(item.get("price"))
            if not price:
                continue
            condition = "used" if item.get("condition") == "used" else "new"
            if condition == "used" and not params.include_used:
                continue
            item_id = item.get("item_id") or item.get("id")
            if not item_id:
                continue
            state = ((item.get("seller_address") or {}).get("state") or {}).get("name", "")
            out.append(
                FoundOffer(
                    source=self.key,
                    external_id=str(item_id),
                    store="Mercado Livre",
                    store_key="mercadolivre",
                    title=name,
                    match_title=name,
                    url=f"https://www.mercadolivre.com.br/p/{product['id']}"
                    f"?pdp_filters=item_id:{item_id}",
                    price=price,
                    original_price=parse_brl(item.get("original_price")),
                    free_shipping=(item.get("shipping") or {}).get("free_shipping"),
                    seller="Loja oficial" if item.get("official_store_id") else "",
                    marketplace=True,
                    condition=condition,
                    location=state,
                    image=image,
                )
            )
        return out
