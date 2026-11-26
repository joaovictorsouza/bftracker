"""Lojas na plataforma VTEX expõem um catálogo JSON público com preço e parcelamento."""

from __future__ import annotations

from urllib.parse import quote

from ..core import stores
from ..core.text import parse_brl
from .base import Fetcher, FoundOffer, SearchParams, SourceError, StoreSource

# chave -> (nome, URL base, condição padrão)
DEFAULT_VTEX: dict[str, tuple[str, str, str]] = {
    "americanas": ("Americanas", "https://www.americanas.com.br", "new"),
    "samsung": ("Samsung", "https://shop.samsung.com/br", "new"),
    "motorola": ("Motorola", "https://www.motorola.com.br", "new"),
    "electrolux": ("Electrolux", "https://loja.electrolux.com.br", "new"),
    "brastemp": ("Brastemp", "https://www.brastemp.com.br", "new"),
    "compracerta": ("Compra Certa", "https://www.compracerta.com.br", "new"),
    "samsclub": ("Sam's Club", "https://www.samsclub.com.br", "new"),
    "webcontinental": ("Webcontinental", "https://www.webcontinental.com.br", "new"),
    "casaevideo": ("Casa & Video", "https://www.casaevideo.com.br", "new"),
    "trocafone": ("Trocafone", "https://www.trocafone.com.br", "refurbished"),
}


class Vtex(StoreSource):
    def __init__(self, key: str, name: str, base: str, condition: str = "new",
                 guard: bool = False):
        self.key = f"vtex:{key}"
        self.store_key = key
        self.name = name
        self.base = base.rstrip("/")
        self.condition = condition
        self.covers = name
        self.guard = guard
        self.used_only = condition != "new"

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        url = (
            f"{self.base}/api/catalog_system/pub/products/search"
            f"?ft={quote(params.query)}&_from=0&_to=39"
        )
        data = await fetcher.get_json(url, guard=self.guard)
        return self.parse(data, params)

    def parse(self, data, params: SearchParams) -> list[FoundOffer]:
        if not isinstance(data, list):
            raise SourceError(f"{self.name}: formato inesperado")
        store_key, store = stores.identify(self.name, self.base)
        out: list[FoundOffer] = []
        for product in data:
            for item in (product.get("items") or [])[:8]:
                name = item.get("nameComplete") or product.get("productName") or ""
                if not params.relevant(name):
                    continue
                best = None
                for seller in item.get("sellers") or []:
                    offer = seller.get("commertialOffer") or {}
                    price = parse_brl(offer.get("Price"))
                    if not price or not offer.get("AvailableQuantity"):
                        continue
                    if best is None or price < best[0]:
                        best = (price, seller, offer)
                if not best:
                    continue
                price, seller, offer = best
                pix_price, card = None, None
                count, value, free = None, None, None
                for inst in offer.get("Installments") or []:
                    total = parse_brl(inst.get("TotalValuePlusInterestRate"))
                    number = inst.get("NumberOfInstallments") or 1
                    system = str(inst.get("PaymentSystemName", "")).lower()
                    if total and "pix" in system:
                        pix_price = min(total, pix_price or total)
                    interest_free = not inst.get("InterestRate")
                    if interest_free and (count is None or number > count):
                        count, value, free = number, parse_brl(inst.get("Value")), True
                        card = total
                final = min(price, pix_price or price)
                images = item.get("images") or []
                url = product.get("link") or f"{self.base}/{product.get('linkText')}/p"
                out.append(
                    FoundOffer(
                        source=self.key,
                        external_id=str(item.get("itemId")),
                        store=store,
                        store_key=store_key,
                        title=name,
                        url=url,
                        price=final,
                        card_price=card or price,
                        original_price=parse_brl(offer.get("ListPrice")),
                        installments=count,
                        installment_value=value,
                        interest_free=free,
                        pix=bool(pix_price and pix_price <= final),
                        seller=seller.get("sellerName", ""),
                        marketplace=str(seller.get("sellerId")) != "1",
                        image=images[0].get("imageUrl", "") if images else "",
                        condition=self.condition,
                    )
                )
        return out
