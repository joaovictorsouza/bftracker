"""Mercado Livre pela API oficial (catálogo e ofertas por produto, novos e usados).

Desde 2025 o Mercado Livre exige autenticação na API e costuma barrar acesso
automatizado ao site. Crie um aplicativo em developers.mercadolivre.com.br e informe
Client ID e Client Secret em Configurações. Sem credenciais, as ofertas do Mercado
Livre continuam chegando pelos comparadores e pelos canais de promoções.
"""

from __future__ import annotations

import time
from urllib.parse import quote_plus

from ..core.text import parse_brl
from .base import Fetcher, FoundOffer, NotConfigured, SearchParams, SourceError, StoreSource

API = "https://api.mercadolibre.com"


class MercadoLivre(StoreSource):
    key = "mercadolivre"
    name = "Mercado Livre (API)"
    covers = "Mercado Livre"
    max_products = 8

    def __init__(self, client_id: str = "", client_secret: str = "", access_token: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self._token: tuple[str, float] | None = None

    async def _auth(self, fetcher: Fetcher) -> dict:
        if self.client_id and self.client_secret:
            if not self._token or self._token[1] < time.time():
                response = await fetcher.request(
                    "POST",
                    f"{API}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                )
                body = response.json()
                token = body.get("access_token")
                if not token:
                    raise SourceError("Mercado Livre não devolveu token de acesso")
                self._token = (token, time.time() + int(body.get("expires_in", 3600)) - 120)
            return {"Authorization": f"Bearer {self._token[0]}"}
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        raise NotConfigured(
            "Informe as credenciais da API do Mercado Livre em Configurações para busca direta"
        )

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        headers = await self._auth(fetcher)
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
