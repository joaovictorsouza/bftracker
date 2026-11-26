"""Radar de ofertas: guarda o que os sites e canais publicam e avisa quando algo bate
com os interesses ou com os produtos monitorados do usuário."""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    Coupon,
    Deal,
    Interest,
    Notification,
    Offer,
    PricePoint,
    RunRequest,
    User,
    Watch,
    utcnow,
)
from ..notify.dispatch import notify
from ..sources.base import FoundCoupon, FoundDeal
from . import matching, stores
from .dealtext import CATEGORIES, category_of, classify, score_deal
from .engine import criteria_of
from .text import brl, clip, contains_term, normalize, short_hash, slug

# só avisa sobre o que acabou de ser publicado
FRESH = timedelta(minutes=45)

_PROMOBIT_CATEGORIES = {
    "smartphones-tablets-e-telefones": "celulares", "games": "games",
    "informatica": "informatica", "tv": "tvs", "audio": "audio",
    "eletrodomesticos": "eletrodomesticos", "casa-e-moveis": "casa", "moda-e-acessorios": "moda",
    "saude-e-beleza": "beleza", "supermercado": "mercado", "livros": "livros",
    "esporte-e-lazer": "esporte", "bebes-e-criancas": "infantil",
    "ferramentas-e-jardim": "ferramentas",
}


def _fingerprint(store_key: str, price: float | None, coupon: str, title: str) -> str:
    words = [w for w in normalize(title).split() if len(w) > 2][:7]
    if price:
        return short_hash(store_key, round(price), " ".join(words[:3]))
    if coupon:
        return short_hash(store_key, coupon.upper())
    return short_hash(store_key, " ".join(words))


def enrich(found: FoundDeal) -> Deal:
    info = classify(found.title, found.description)
    link = found.link or ""
    store = stores.find_by_name(found.store) if found.store else None
    store = (
        store
        or (stores.find_by_url(link) if link else None)
        or stores.find_in_text(found.title)
        or stores.find_in_text(found.description[:400])
    )
    if store:
        store_key, store_name = store.key, store.name
    elif found.store:
        store_key, store_name = stores.identify(found.store)
    else:
        store_key, store_name = "", ""
    price = found.price or info["price"]
    old = found.old_price or info["old_price"]
    discount = None
    if price and old and old > price:
        discount = round((old - price) / old * 100, 1)
    elif m := re.search(r"(\d{1,2})\s?% (?:off|de desconto)", found.title, re.I):
        discount = float(m.group(1))
    category = _PROMOBIT_CATEGORIES.get(found.category) or (
        found.category if found.category in CATEGORIES else info["category"]
    )
    coupon = found.coupon or info["coupon"]
    info["coupon"] = coupon
    info["is_flash"] = found.is_flash or info["is_flash"]
    is_coupon = found.is_coupon or info["is_coupon"]
    if is_coupon and category == "outros":
        category = "cupons"
    return Deal(
        source=found.source,
        source_name=found.source_name,
        external_id=found.external_id[:300],
        title=clip(found.title, 400),
        description=found.description[:2000],
        url=found.url,
        link=link,
        image=found.image,
        store=store_name[:80],
        store_key=store_key[:60],
        price=price,
        old_price=old,
        discount_percent=discount,
        coupon=coupon[:120],
        category=category,
        is_flash=info["is_flash"],
        is_coupon=is_coupon,
        is_blackfriday=info["is_blackfriday"],
        is_bug=info["is_bug"],
        score=score_deal(info, stores.trust_of(store_key)["score"] if store_key else 50, discount),
        fingerprint=_fingerprint(store_key, price, coupon, found.title),
        published_at=min(found.published_at or utcnow(), utcnow()),
    )


def interest_matches(interest: Interest, deal: Deal) -> bool:
    has_filter = any(
        (interest.categories, interest.keywords, interest.stores, interest.max_price,
         interest.min_discount, interest.only_flash, interest.only_coupons)
    )
    if not has_filter:
        return False
    if interest.only_flash and not (deal.is_flash or deal.is_bug):
        return False
    if interest.only_coupons and not deal.is_coupon:
        return False
    if interest.categories and deal.category not in interest.categories:
        return False
    if interest.stores and deal.store_key not in interest.stores:
        return False
    text = normalize(f"{deal.title} {deal.coupon}")
    if interest.keywords and not any(contains_term(text, k) for k in interest.keywords):
        return False
    if any(contains_term(text, k) for k in interest.exclude_terms or []):
        return False
    if interest.max_price and (deal.price is None or deal.price > interest.max_price):
        return False
    if interest.min_discount and (deal.discount_percent or 0) < interest.min_discount:
        return False
    return True


def _deal_body(deal: Deal) -> str:
    parts = []
    if deal.price:
        parts.append(brl(deal.price))
        if deal.old_price:
            parts.append(f"(antes {brl(deal.old_price)})")
    if deal.store:
        parts.append(f"na {deal.store}")
    lines = [" ".join(parts)] if parts else []
    if deal.coupon:
        lines.append(f"Cupom: {deal.coupon}")
    lines.append(f"Fonte: {deal.source_name}")
    if deal.store_key and stores.trust_of(deal.store_key)["level"] in {"atencao", "desconhecida"}:
        lines.append("⚠️ Confira a reputação da loja antes de comprar.")
    return "\n".join(lines)


def _prefix(deal: Deal) -> str:
    if deal.is_bug:
        return "🐞 Possível bug de preço"
    if deal.is_coupon and deal.is_flash:
        return "⚡ Cupom relâmpago"
    if deal.is_flash:
        return "⚡ Oferta relâmpago"
    if deal.is_coupon:
        return "🎟️ Cupom"
    return "🛍️ Oferta"


def alert_deal(db: Session, deal: Deal) -> int:
    sent = 0
    link = deal.link or deal.url
    hour_ago = utcnow() - timedelta(hours=1)

    watches = db.scalars(select(Watch).where(Watch.active, Watch.kind == "product")).all()
    for watch in watches:
        if not matching.matches(deal.title, criteria_of(watch), deal.price):
            continue
        floor = watch.min_price
        if floor is None and deal.price:
            known = db.scalar(
                select(func.min(Offer.price)).where(
                    Offer.watch_id == watch.id, Offer.available, ~Offer.suspicious,
                    Offer.condition == "new",
                )
            )
            # muito abaixo do que existe no mercado costuma ser acessório
            if known and deal.price < known * 0.3 and not deal.is_bug:
                continue
        urgent = deal.is_flash or deal.is_bug or bool(
            watch.target_price and deal.price and deal.price <= watch.target_price
        )
        if notify(
            db, watch.user, kind="deal",
            title=f"{_prefix(deal)} para {watch.name}: {clip(deal.title, 110)}",
            body=_deal_body(deal), dedupe_key=f"deal:{deal.fingerprint}",
            priority=3 if urgent else 2, url=link, path=f"/monitorados/{watch.id}",
            image=deal.image, watch_id=watch.id,
        ):
            sent += 1

    interests = db.scalars(select(Interest).where(Interest.active)).all()
    for interest in interests:
        if not interest_matches(interest, deal):
            continue
        recent = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == interest.user_id,
                Notification.kind == f"interest:{interest.id}",
                Notification.created_at >= hour_ago,
            )
        )
        if recent >= interest.max_per_hour:
            continue
        if notify(
            db, interest.user, kind=f"interest:{interest.id}",
            title=f"{_prefix(deal)}: {clip(deal.title, 140)}",
            body=_deal_body(deal) + f"\nInteresse: {interest.name}",
            dedupe_key=f"deal:{deal.fingerprint}",
            priority=3 if (deal.is_flash or deal.is_bug) else 2,
            url=link, path="/radar", image=deal.image,
        ):
            sent += 1
    return sent


def ingest_deals(db: Session, found: list[FoundDeal], *, baseline: bool) -> dict:
    created = alerts = 0
    for item in found:
        if not item.url or not item.title:
            continue
        external = item.external_id[:300]
        existing = db.scalar(
            select(Deal).where(Deal.source == item.source, Deal.external_id == external)
        )
        if existing is not None:
            continue
        deal = enrich(item)
        db.add(deal)
        db.flush()
        created += 1
        if deal.is_coupon and deal.coupon and deal.store_key:
            _store_coupon(
                db,
                FoundCoupon(
                    source=deal.source, store=deal.store, title=deal.title, code=deal.coupon,
                    url=deal.link or deal.url, is_flash=deal.is_flash,
                ),
                published=deal.published_at,
            )
        fresh = utcnow() - deal.published_at <= FRESH
        if fresh and not baseline:
            alerts += alert_deal(db, deal)
    db.commit()
    return {"new": created, "alerts": alerts}


def _store_coupon(db: Session, item: FoundCoupon, published=None) -> Coupon | None:
    store_key, store = stores.identify(item.store, item.url)
    code = item.code.strip()[:60]
    title_key = "" if code else slug(item.title, 80)
    row = db.scalar(
        select(Coupon).where(
            Coupon.store_key == store_key, Coupon.code == code, Coupon.title_key == title_key
        )
    )
    if row is not None:
        row.last_seen_at = utcnow()
        if item.expires_at:
            row.expires_at = item.expires_at
        return None
    row = Coupon(
        store=store, store_key=store_key, code=code, title=clip(item.title, 300),
        title_key=title_key, discount=item.discount[:60], conditions=item.conditions,
        url=item.url, source=item.source, is_flash=item.is_flash, expires_at=item.expires_at,
        first_seen_at=published or utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def alert_coupon(db: Session, coupon: Coupon) -> int:
    """Cupom novo: avisa quem se interessa por cupons da loja e quem monitora um produto
    cuja melhor oferta está nessa loja (cupom possível)."""
    sent = 0
    code = f"Código: {coupon.code}\n" if coupon.code else ""
    body = f"{code}{coupon.title}\n{clip(coupon.conditions, 300)}".strip()
    key = f"coupon:{coupon.store_key}:{(coupon.code or coupon.title_key).upper()}"
    hour_ago = utcnow() - timedelta(hours=1)
    for interest in db.scalars(select(Interest).where(Interest.active, Interest.only_coupons)):
        if interest.stores and coupon.store_key not in interest.stores:
            continue
        if interest.max_price or interest.min_discount or interest.categories:
            continue  # esses filtros só fazem sentido para ofertas com preço/categoria
        text = normalize(f"{coupon.title} {coupon.code} {coupon.conditions}")
        if interest.keywords and not any(contains_term(text, k) for k in interest.keywords):
            continue
        if interest.only_flash and not coupon.is_flash:
            continue
        recent = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == interest.user_id,
                Notification.kind == f"interest:{interest.id}",
                Notification.created_at >= hour_ago,
            )
        )
        if recent >= interest.max_per_hour:
            continue
        if notify(
            db, interest.user, kind=f"interest:{interest.id}",
            title=f"🎟️ Novo cupom {coupon.store}: {coupon.discount or coupon.code}",
            body=body, dedupe_key=key, priority=3 if coupon.is_flash else 2,
            url=coupon.url, path="/cupons",
        ):
            sent += 1

    category = category_of(coupon.title)
    day_ago = utcnow() - timedelta(days=1)
    for watch in db.scalars(select(Watch).where(Watch.active)):
        offer = db.scalar(
            select(Offer)
            .where(Offer.watch_id == watch.id, Offer.available, ~Offer.suspicious,
                   ~Offer.hidden, Offer.condition == "new")
            .order_by(Offer.price)
            .limit(1)
        )
        if offer is None or offer.store_key != coupon.store_key:
            continue
        # cupom de outra categoria (ex.: mercado) não serve para o produto
        if category not in ("outros", category_of(offer.title)):
            continue
        recent = db.scalar(
            select(func.count(Notification.id)).where(
                Notification.watch_id == watch.id, Notification.kind == "coupon_possible",
                Notification.created_at >= day_ago,
            )
        )
        if recent >= 2:
            continue
        if notify(
            db, watch.user, kind="coupon_possible",
            title=f"🎟️ Cupom possível para {watch.name} na {coupon.store}",
            body=f"{body}\nMelhor oferta atual: {brl(offer.price)}. Confira as regras no carrinho.",
            dedupe_key=key, priority=2, url=coupon.url or offer.url,
            path=f"/monitorados/{watch.id}", watch_id=watch.id,
        ):
            sent += 1
    return sent


def ingest_coupons(db: Session, found: list[FoundCoupon], *, baseline: bool) -> dict:
    created = alerts = 0
    for item in found:
        if item.expires_at and item.expires_at < utcnow():
            continue
        row = _store_coupon(db, item)
        if row is None:
            continue
        created += 1
        if not baseline:
            alerts += alert_coupon(db, row)
    db.commit()
    return {"new": created, "alerts": alerts}


def default_interests(db: Session, user: User) -> None:
    db.add_all(
        [
            Interest(
                user_id=user.id, name="Cupons das grandes lojas",
                stores=["mercadolivre", "amazon", "magalu", "kabum"], only_coupons=True,
                max_per_hour=4, categories=[], keywords=[], exclude_terms=[],
            ),
            Interest(
                user_id=user.id, name="Relâmpagos e bugs de tecnologia",
                categories=["celulares", "games", "informatica", "hardware", "tvs", "audio",
                            "wearables", "tablets"],
                only_flash=True, max_per_hour=4, keywords=[], stores=[], exclude_terms=[],
            ),
        ]
    )


def cleanup(db: Session) -> None:
    now = utcnow()
    db.execute(delete(Deal).where(Deal.first_seen_at < now - timedelta(days=30)))
    db.execute(delete(Coupon).where(Coupon.last_seen_at < now - timedelta(days=21)))
    db.execute(delete(PricePoint).where(PricePoint.at < now - timedelta(days=180)))
    db.execute(delete(Notification).where(Notification.created_at < now - timedelta(days=90)))
    db.execute(delete(RunRequest).where(RunRequest.created_at < now - timedelta(days=1)))
    db.execute(
        delete(Offer).where(~Offer.available, Offer.last_seen_at < now - timedelta(days=45))
    )
    db.commit()


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")
