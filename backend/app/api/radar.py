from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core import stores
from ..core.dealtext import CATEGORIES
from ..db import get_db
from ..models import Coupon, Deal, Heartbeat, Interest, Notification, Offer, User, Watch, utcnow
from ..schemas import InterestIn
from ..security import current_user
from ..sources.olx import STATES
from ..sources.x_twitter import build_x_live_url

router = APIRouter(prefix="/api", tags=["radar"])


def deal_dict(deal: Deal, also: list[str] | None = None) -> dict:
    return {
        "id": deal.id, "source": deal.source, "source_name": deal.source_name,
        "title": deal.title, "url": deal.url, "link": deal.link, "image": deal.image,
        "store": deal.store, "store_key": deal.store_key, "price": deal.price,
        "old_price": deal.old_price, "discount_percent": deal.discount_percent,
        "coupon": deal.coupon, "category": deal.category, "is_flash": deal.is_flash,
        "is_coupon": deal.is_coupon, "is_blackfriday": deal.is_blackfriday,
        "is_bug": deal.is_bug, "score": deal.score, "published_at": deal.published_at,
        "trust": stores.trust_of(deal.store_key) if deal.store_key else None,
        "also": also or [],
    }


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/deals")
def list_deals(
    q: str = "",
    category: str = "",
    store: str = "",
    kind: str = Query(default="", pattern="^(|flash|coupon|blackfriday|bug)$"),
    origin: str = Query(default="", pattern="^(|x|portals|telegram|rss|email)$"),
    sort: str = Query(default="recent", pattern="^(recent|hot|price)$"),
    hours: int = Query(default=72, ge=1, le=720),
    offset: int = Query(default=0, ge=0, le=5000),
    limit: int = Query(default=40, ge=1, le=100),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Deal).where(Deal.published_at >= utcnow() - timedelta(hours=hours))
    for word in q.split()[:6]:
        query = query.where(
            or_(Deal.title.ilike(_like(word), escape="\\"),
                Deal.coupon.ilike(_like(word), escape="\\"))
        )
    if category:
        query = query.where(Deal.category == category)
    if store:
        query = query.where(Deal.store_key == store)
    if origin == "x":
        query = query.where(Deal.source == "x_twitter")
    elif origin == "portals":
        query = query.where(
            or_(
                Deal.source.in_(("promobit", "pelando", "gatry", "hardmob")),
                Deal.source == "tg:hardmob_promo",
            )
        )
    elif origin == "telegram":
        query = query.where(Deal.source.like("tg:%"))
    elif origin == "rss":
        query = query.where(Deal.source.like("rss:%"))
    elif origin == "email":
        query = query.where(Deal.source.like("imap:%"))
    if kind:
        column = {"flash": Deal.is_flash, "coupon": Deal.is_coupon,
                  "blackfriday": Deal.is_blackfriday, "bug": Deal.is_bug}[kind]
        query = query.where(column)
    order = {
        "recent": (Deal.published_at.desc(),),
        "hot": (Deal.score.desc(), Deal.published_at.desc()),
        "price": (Deal.price.is_(None), Deal.price.asc()),
    }[sort]
    rows = db.scalars(query.order_by(*order).offset(offset).limit(limit * 2)).all()
    items: list[dict] = []
    by_print: dict[str, dict] = {}
    consumed = 0
    for row in rows:
        if len(items) >= limit:
            break
        consumed += 1
        if row.fingerprint in by_print:  # mesma oferta publicada em várias fontes
            entry = by_print[row.fingerprint]
            if row.source_name not in (entry["source_name"], *entry["also"]):
                entry["also"].append(row.source_name)
            continue
        entry = deal_dict(row)
        by_print[row.fingerprint] = entry
        items.append(entry)
    more = consumed < len(rows) or len(rows) == limit * 2
    return {"items": items, "next_offset": offset + consumed if more else None}


@router.get("/coupons")
def list_coupons(
    store: str = "", q: str = "", user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = select(Coupon).where(
        or_(Coupon.expires_at.is_(None), Coupon.expires_at >= utcnow())
    )
    if store:
        query = query.where(Coupon.store_key == store)
    for word in q.split()[:5]:
        query = query.where(
            or_(Coupon.title.ilike(_like(word), escape="\\"),
                Coupon.code.ilike(_like(word), escape="\\"),
                Coupon.store.ilike(_like(word), escape="\\"))
        )
    rows = db.scalars(query.order_by(Coupon.first_seen_at.desc()).limit(300)).all()
    counts = db.execute(
        select(Coupon.store_key, func.min(Coupon.store), func.count(Coupon.id))
        .group_by(Coupon.store_key)
        .order_by(func.count(Coupon.id).desc())
        .limit(30)
    ).all()
    return {
        "items": [
            {
                "id": c.id, "store": c.store, "store_key": c.store_key, "code": c.code,
                "title": c.title, "discount": c.discount, "conditions": c.conditions,
                "url": c.url, "source": c.source, "is_flash": c.is_flash,
                "expires_at": c.expires_at, "first_seen_at": c.first_seen_at,
            }
            for c in rows
        ],
        "stores": [{"key": k, "name": n, "count": total} for k, n, total in counts],
    }


def interest_dict(row: Interest) -> dict:
    return {
        "id": row.id,
        **{name: getattr(row, name) for name in InterestIn.model_fields},
    }


def _own_interest(db: Session, user: User, interest_id: int) -> Interest:
    row = db.get(Interest, interest_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Alerta não encontrado")
    return row


@router.get("/interests")
def list_interests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Interest).where(Interest.user_id == user.id).order_by(Interest.id)
    )
    return [interest_dict(r) for r in rows]


@router.post("/interests", status_code=201)
def create_interest(
    data: InterestIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = Interest(user_id=user.id, **data.model_dump())
    db.add(row)
    db.commit()
    return interest_dict(row)


@router.put("/interests/{interest_id}")
def update_interest(
    interest_id: int, data: InterestIn, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    row = _own_interest(db, user, interest_id)
    for name, value in data.model_dump().items():
        setattr(row, name, value)
    db.commit()
    return interest_dict(row)


@router.delete("/interests/{interest_id}")
def delete_interest(
    interest_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    db.delete(_own_interest(db, user, interest_id))
    db.commit()
    return {"ok": True}


@router.get("/meta")
def meta(user: User = Depends(current_user)):
    return {
        "categories": [{"key": k, "name": v} for k, v in CATEGORIES.items()],
        "stores": [s.public() for s in sorted(stores.STORES, key=lambda s: -s.score)],
        "stores_checked_at": stores.CHECKED_AT,
        "states": list(STATES),
    }


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    watch_ids = select(Watch.id).where(Watch.user_id == user.id)

    def count(query) -> int:
        return db.scalar(query) or 0

    recent_drops = db.execute(
        select(Offer, Watch.name)
        .join(Watch, Watch.id == Offer.watch_id)
        .where(
            Watch.user_id == user.id, Offer.available, ~Offer.hidden, ~Offer.suspicious,
            Offer.previous_price.is_not(None), Offer.price < Offer.previous_price,
            Offer.changed_at >= now - timedelta(days=3),
        )
        .order_by(Offer.changed_at.desc())
        .limit(40)
    ).all()
    drops, seen = [], set()
    for offer, name in recent_drops:
        key = (offer.watch_id, offer.store_key, offer.variant_key, round(offer.price))
        if key in seen:
            continue
        seen.add(key)
        drops.append(
            {
                "watch_id": offer.watch_id, "watch": name, "title": offer.title,
                "store": offer.store, "price": offer.price, "previous": offer.previous_price,
                "url": offer.url, "image": offer.image, "at": offer.changed_at,
            }
        )
    hot_rows = db.scalars(
        select(Deal)
        .where(Deal.published_at >= now - timedelta(hours=12), Deal.image != "")
        .order_by(Deal.score.desc(), Deal.published_at.desc())
        .limit(40)
    ).all()
    hot, prints = [], set()
    for row in hot_rows:
        if row.fingerprint not in prints:
            prints.add(row.fingerprint)
            hot.append(deal_dict(row))
    beat = db.get(Heartbeat, "worker")
    watch_queries = db.scalars(
        select(Watch.query).where(Watch.user_id == user.id, Watch.active, Watch.kind == "product")
    ).all()
    return {
        "stats": {
            "watches": count(
                select(func.count(Watch.id)).where(Watch.user_id == user.id, Watch.active)
            ),
            "offers": count(
                select(func.count(Offer.id)).where(Offer.watch_id.in_(watch_ids), Offer.available)
            ),
            "deals_24h": count(
                select(func.count(Deal.id)).where(Deal.first_seen_at >= day_ago)
            ),
            "coupons": count(
                select(func.count(Coupon.id)).where(
                    or_(Coupon.expires_at.is_(None), Coupon.expires_at >= now)
                )
            ),
            "alerts_24h": count(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user.id, Notification.created_at >= day_ago
                )
            ),
        },
        "drops": drops[:8],
        "hot": hot[:8],
        "worker_online": bool(beat and now - beat.at < timedelta(seconds=60)),
        "x_live_url": build_x_live_url([q for q in watch_queries if q]),
    }
