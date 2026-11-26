"""Monitora o preço de qualquer página de produto informada pelo usuário, usando os
dados estruturados (schema.org / Open Graph) que a maioria das lojas publica."""

from __future__ import annotations

from selectolax.parser import HTMLParser

from ..core import stores
from ..core.text import parse_brl, short_hash
from .base import Fetcher, FoundOffer, SourceError
from .htmlutil import json_ld


def _types(node: dict) -> set[str]:
    value = node.get("@type")
    return {str(v) for v in value} if isinstance(value, list) else {str(value)}


def _offer_nodes(product: dict) -> list[dict]:
    offers = product.get("offers")
    items = offers if isinstance(offers, list) else [offers] if offers else []
    flat: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        nested = item.get("offers")
        if isinstance(nested, list) and nested:
            flat.extend(o for o in nested if isinstance(o, dict))
        else:
            flat.append(item)
    return flat


def parse_product_page(page: str, url: str) -> FoundOffer:
    tree = HTMLParser(page)

    def meta(*names: str) -> str:
        for name in names:
            for attr in ("property", "name", "itemprop"):
                node = tree.css_first(f'meta[{attr}="{name}"]')
                if node and node.attributes.get("content"):
                    return node.attributes["content"].strip()
        return ""

    title, image, price, original, seller = "", "", None, None, ""
    available = True
    condition = "new"
    for node in json_ld(page):
        if not _types(node) & {"Product", "ProductGroup"}:
            continue
        candidates = []
        for offer in _offer_nodes(node):
            value = parse_brl(offer.get("price") or offer.get("lowPrice"))
            spec = offer.get("priceSpecification")
            if value is None and isinstance(spec, dict):
                value = parse_brl(spec.get("price"))
            if value:
                in_stock = "outofstock" not in str(offer.get("availability", "")).lower()
                candidates.append((not in_stock, value, offer))
        if not candidates:
            continue
        unavailable, price, best = sorted(candidates, key=lambda c: (c[0], c[1]))[0]
        available = not unavailable
        title = str(node.get("name") or "")
        img = node.get("image")
        if isinstance(img, list):
            img = img[0] if img else ""
        image = img.get("url", "") if isinstance(img, dict) else str(img or "")
        seller_node = best.get("seller")
        if isinstance(seller_node, dict):
            seller = str(seller_node.get("name") or "")
        if "used" in str(best.get("itemCondition", "")).lower():
            condition = "used"
        elif "refurb" in str(best.get("itemCondition", "")).lower():
            condition = "refurbished"
        break

    if price is None:
        price = parse_brl(meta("product:price:amount", "og:price:amount", "price"))
    if price is None and "amazon." in url:
        node = tree.css_first("#corePrice_feature_div span.a-offscreen") or tree.css_first(
            "span.a-price span.a-offscreen"
        )
        price = parse_brl(node.text()) if node else None
        heading = tree.css_first("#productTitle")
        title = heading.text(strip=True) if heading else title
    if price is None:
        raise SourceError(
            "Não encontrei o preço nessa página (a loja não publica dados estruturados)"
        )
    title = title or meta("og:title", "twitter:title")
    if not title and (node := tree.css_first("title")):
        title = node.text(strip=True)
    image = image or meta("og:image")
    store_key, store = stores.identify(meta("og:site_name"), url)
    known = stores.find_by_url(url)
    if known:
        store_key, store = known.key, known.name
    if not available:
        raise SourceError("Produto indisponível no momento")
    return FoundOffer(
        source="url",
        external_id=short_hash(url),
        store=store,
        store_key=store_key,
        title=" ".join(title.split()) or url,
        url=url,
        price=price,
        original_price=original,
        image=image,
        seller=seller,
        condition=condition,
    )


async def fetch_product(fetcher: Fetcher, url: str) -> FoundOffer:
    page = await fetcher.get_text(url, guard=True)
    return parse_product_page(page, url)
