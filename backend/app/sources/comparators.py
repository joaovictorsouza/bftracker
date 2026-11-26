"""Zoom e Buscapé: comparadores que listam preços e parcelamento de várias lojas
(Amazon, Magazine Luiza, Casas Bahia, Mercado Livre, Fast Shop etc.)."""

from __future__ import annotations

from urllib.parse import quote_plus, urljoin

from ..core import stores
from ..core.text import parse_brl
from .base import Fetcher, FoundOffer, SearchParams, SourceError, StoreSource
from .htmlutil import find_key, next_data


class Comparator(StoreSource):
    base = ""
    max_products = 6
    covers = "Amazon, Magazine Luiza, Casas Bahia, Mercado Livre, KaBuM!, Fast Shop e outras"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        page = await fetcher.get_text(f"{self.base}/search?q={quote_plus(params.query)}")
        hits = self.parse_hits(page)
        results: list[FoundOffer] = []
        products = []
        for hit in hits:
            name = " ".join(str(hit.get("name") or "").split())
            price = parse_brl(hit.get("price"))
            if not name or not price or not params.relevant(name):
                continue
            if params.min_price and price < params.min_price * 0.9:
                continue
            if hit.get("type") == "product":
                products.append(hit)
            else:
                results.append(self._listing_offer(hit, name, price))
        for hit in products[: self.max_products]:
            try:
                detail = await fetcher.get_text(urljoin(self.base, hit["url"]))
                results.extend(self.parse_product(detail, hit))
            except SourceError:
                if not results:
                    raise
                break
        return results

    def parse_hits(self, page: str) -> list[dict]:
        data = next_data(page)
        hits = find_key(find_key(data, "initialReduxState") or data, "hits")
        if isinstance(hits, dict):
            hits = hits.get("hits")
        if not isinstance(hits, list):
            raise SourceError(f"{self.name}: lista de resultados não encontrada")
        return [h for h in hits if isinstance(h, dict) and h.get("url")]

    def _listing_offer(self, hit: dict, name: str, price: float) -> FoundOffer:
        best = hit.get("bestOffer") or {}
        store_key, store = stores.identify(best.get("merchantName") or self.name)
        inst = hit.get("installments") or {}
        return FoundOffer(
            source=self.key,
            external_id=str(hit.get("objectId") or best.get("id")),
            store=store,
            store_key=store_key,
            title=name,
            url=urljoin(self.base, hit["url"]),
            price=price,
            image=hit.get("image") or "",
            installments=inst.get("amount_months") or None,
            installment_value=parse_brl(inst.get("price")),
            card_price=parse_brl(inst.get("total_value")),
            marketplace=bool(hit.get("marketplace")),
        )

    def parse_product(self, page: str, hit: dict) -> list[FoundOffer]:
        state = find_key(next_data(page), "initialReduxState") or {}
        offer_state = state.get("offers") or {}
        listed = list(offer_state.get("displayOffers") or []) + list(
            offer_state.get("offerList") or []
        )
        product_name = " ".join(str(hit.get("name") or "").split())
        source_id = str(hit.get("sourceId") or "")
        history: list[tuple[str, float]] = []
        price_history = find_key(state.get("priceHistory") or {}, "priceHistory") or {}
        days = (price_history.get(source_id) or {}).get("days") if price_history else None
        for day in days or []:
            value = parse_brl(day.get("price"))
            if value and day.get("date"):
                history.append((str(day["date"])[:10], value))
        url = urljoin(self.base, hit["url"])
        out: dict[str, FoundOffer] = {}
        for raw in listed:
            price = parse_brl(raw.get("price"))
            if not price:
                continue
            merchant = raw.get("sellerName") or raw.get("merchantName") or ""
            store_key, store = stores.identify(merchant)
            external = str(raw.get("id") or f"{source_id}-{store_key}")
            parcels = raw.get("numParcels") or None
            total = parse_brl(raw.get("totalParceledValue"))
            out[external] = FoundOffer(
                source=self.key,
                external_id=external,
                store=store,
                store_key=store_key,
                title=" ".join(str(raw.get("name") or product_name).split()),
                match_title=product_name,
                # a página do comparador mostra todas as lojas e leva ao clique na oferta
                url=url,
                price=price,
                image=raw.get("imageUrl") or hit.get("image") or "",
                card_price=total,
                installments=parcels,
                installment_value=parse_brl(raw.get("parcelValue")),
                # o preço à vista costuma ter desconto no Pix, então um total maior não
                # prova que há juros: só afirmamos "sem juros" quando os valores batem
                interest_free=True if parcels and total and total <= price * 1.005 else None,
                marketplace=bool(raw.get("sellerIsMarketplace")),
                history=history,
            )
            history = []  # o histórico é do produto: basta enviar uma vez
        return list(out.values())


class Zoom(Comparator):
    key = "zoom"
    name = "Zoom"
    base = "https://www.zoom.com.br"


class Buscape(Comparator):
    key = "buscape"
    name = "Buscapé"
    base = "https://www.buscape.com.br"
