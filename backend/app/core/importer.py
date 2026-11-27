"""Anúncios e ofertas capturados pelo navegador do próprio usuário (extensão BFTracker
Companion ou favorito "Enviar ao BFTracker").

Serve para sites que recusam acesso automatizado ou exigem sessão do usuário, como OLX,
Mercado Livre, hardMOB e X (Twitter): a pessoa navega normalmente e envia o que está vendo,
sem compartilhar cookies nem senhas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, Watch, utcnow
from ..sources.base import FoundDeal, FoundOffer
from . import matching, radar, stores
from .engine import Collected, apply_results
from .text import normalize, short_hash, slug


@dataclass
class Item:
    title: str
    url: str
    price: float
    condition: str = ""
    location: str = ""
    image: str = ""
    original_price: float | None = None
    installments: int | None = None
    installment_value: float | None = None
    interest_free: bool | None = None
    free_shipping: bool | None = None
    coupon: str = ""
    seller: str = ""


@dataclass
class DealItem:
    title: str
    url: str
    source: str = "navegador"
    source_name: str = "Navegador"
    external_id: str = ""
    link: str = ""
    description: str = ""
    image: str = ""
    store: str = ""
    price: float | None = None
    old_price: float | None = None
    coupon: str = ""
    is_coupon: bool = False
    is_flash: bool = False


def _source_and_id(url: str) -> tuple[str, str, str, str]:
    """(fonte, id externo, chave da loja, nome da loja)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    store = stores.find_by_url(url)
    key, name = (store.key, store.name) if store else stores.identify("", url)
    if key == "olx":
        ad = re.search(r"-(\d{6,})$", parts.path.rstrip("/"))
        if ad:
            return "olx", ad.group(1), key, name
    if key == "mercadolivre":
        ad = (
            re.search(r"item_id[:=]+(MLB\d+)", url)
            or re.search(r"/(MLB)-?(\d{6,})", url)
            or re.search(r"/p/(MLB\d+)", url)
        )
        if ad:
            return "mercadolivre", "".join(ad.groups()), key, name
    clean = urlunsplit((parts.scheme, host, parts.path, "", ""))
    return "navegador", short_hash(clean), key, name


def to_offer(item: Item) -> FoundOffer:
    source, external, store_key, store = _source_and_id(item.url)
    condition = item.condition if item.condition in ("new", "used", "refurbished") else ""
    if store_key == "olx" and condition != "refurbished":
        condition = "used"
    title = " ".join(re.sub(r"<[^>]{0,20}>", " ", item.title).split())
    condition = condition or matching.detect_condition(title)
    original = (
        item.original_price
        if item.original_price and item.original_price > item.price
        else None
    )
    card_price = (
        round(item.installments * item.installment_value, 2)
        if item.installments and item.installment_value
        else None
    )
    return FoundOffer(
        source=source,
        external_id=external,
        store=store,
        store_key=store_key,
        seller=" ".join((item.seller or "").split())[:120],
        title=title,
        url=item.url,
        price=item.price,
        original_price=original,
        card_price=card_price,
        installments=item.installments,
        installment_value=item.installment_value,
        interest_free=item.interest_free,
        free_shipping=item.free_shipping,
        coupon=" ".join((item.coupon or "").split())[:200],
        condition=condition,
        location=item.location,
        image=item.image,
        marketplace=True,
    )


def to_deal(item: DealItem) -> FoundDeal:
    title = " ".join(re.sub(r"<[^>]{0,20}>", " ", item.title).split())
    ext = item.external_id.strip()
    if not ext:
        if m := re.search(r"/status/(\d+)", item.url):
            ext = m.group(1)
        elif m := re.search(r"threads/(\d+)", item.url):
            ext = m.group(1)
        else:
            ext = short_hash(item.url, title)
    source = item.source or "navegador"
    source_name = item.source_name or "Navegador"
    if "hardmob.com.br" in item.url.lower():
        source, source_name = "hardmob", "hardMOB Promoções"
    elif any(h in item.url.lower() for h in ("x.com/", "twitter.com/")):
        source = "x_twitter"
        if source_name == "Navegador":
            source_name = "X (Twitter)"
    return FoundDeal(
        source=source,
        source_name=source_name,
        external_id=ext,
        title=title,
        url=item.url,
        link=stores.unwrap_url(item.link) if item.link else "",
        description=item.description,
        image=item.image,
        store=item.store,
        price=item.price if item.price and item.price > 0 else None,
        old_price=item.old_price if item.old_price and item.old_price > 0 else None,
        coupon=item.coupon,
        is_coupon=item.is_coupon or (bool(item.coupon) and not item.price),
        is_flash=item.is_flash,
        published_at=utcnow(),
    )


def _in_region(watch: Watch, offer: FoundOffer) -> bool:
    if offer.store_key != "olx":
        return True
    host = urlsplit(offer.url).hostname or ""
    state = host.split(".")[0]
    if watch.used_state and len(state) == 2 and state != watch.used_state:
        return False
    if not watch.used_region:
        return True
    return slug(watch.used_region) in urlsplit(offer.url).path or normalize(
        watch.used_region
    ) in normalize(offer.location)


def import_items(
    db: Session,
    user: User,
    items: list[Item],
    deals: list[DealItem] | None = None,
) -> dict:
    offers = [to_offer(item) for item in items]
    watches = db.scalars(
        select(Watch).where(Watch.user_id == user.id, Watch.active, Watch.kind == "product")
    ).all()
    used_ids: set[int] = set()
    results = []
    for watch in watches:
        criteria = matching.Criteria(
            watch.query, list(watch.include_terms or []), list(watch.exclude_terms or []),
            watch.min_price, watch.max_price,
        )
        collected = Collected(partial=True)
        for offer in offers:
            if offer.condition != "new" and not watch.include_used:
                continue
            if not matching.matches(offer.title, criteria, offer.price):
                continue
            if not _in_region(watch, offer):
                continue
            key, label = matching.variant_of(offer.title, watch.query)
            collected.offers.append((offer, key, label))
            used_ids.add(id(offer))
        if not collected.offers:
            continue
        summary = apply_results(db, watch, collected)
        results.append({"id": watch.id, "name": watch.name, **summary})

    deal_summary = None
    if deals:
        found_deals = [to_deal(d) for d in deals]
        deal_summary = radar.ingest_deals(db, found_deals, baseline=False)
    else:
        db.commit()

    out: dict = {"received": len(offers), "matched": len(used_ids), "watches": results}
    if deal_summary is not None:
        out["deals_received"] = len(deals or [])
        out["deals_new"] = deal_summary["new"]
        out["deals_alerts"] = deal_summary["alerts"]
    return out
