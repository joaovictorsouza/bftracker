"""Anúncios capturados pelo navegador do próprio usuário (favorito "Enviar ao BFTracker").

Serve para sites que recusam acesso automatizado, como OLX e Mercado Livre: a pessoa
navega normalmente e envia a página que está vendo. Nada aqui acessa esses sites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, Watch
from ..sources.base import FoundOffer
from . import matching, stores
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
        ad = re.search(r"item_id[:=]+(MLB\d+)", url) or re.search(r"/(MLB)-?(\d{6,})", url)
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
    return FoundOffer(
        source=source, external_id=external, store=store, store_key=store_key,
        title=title, url=item.url, price=item.price, condition=condition,
        location=item.location, image=item.image, marketplace=True,
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


def import_items(db: Session, user: User, items: list[Item]) -> dict:
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
    db.commit()
    return {"received": len(offers), "matched": len(used_ids), "watches": results}
