from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import analysis
from ..core.engine import reset_offers
from ..db import get_db
from ..models import DailyBest, Offer, RunRequest, User, Watch, utcnow
from ..schemas import WatchIn
from ..security import current_user
from ..sources.base import SourceError, assert_public_url

router = APIRouter(prefix="/api", tags=["monitorados"])

MAX_WATCHES = 100
_CRITERIA = ("kind", "query", "url", "include_terms", "exclude_terms", "min_price", "max_price")
_FIELDS = (
    "name", "kind", "query", "url", "include_terms", "exclude_terms", "min_price", "max_price",
    "target_price", "drop_percent", "sources", "include_used", "used_state", "used_region",
    "used_max_price", "interval_minutes", "active",
)


def owned(db: Session, user: User, watch_id: int) -> Watch:
    watch = db.get(Watch, watch_id)
    if watch is None or watch.user_id != user.id:
        raise HTTPException(404, "Monitorado não encontrado")
    return watch


def queue_run(db: Session, watch_id: int) -> None:
    exists = db.scalar(
        select(RunRequest.id).where(RunRequest.kind == "watch", RunRequest.target == str(watch_id))
    )
    if not exists:
        db.add(RunRequest(kind="watch", target=str(watch_id)))


def summary(watch: Watch, offers: list[Offer], history: list[DailyBest]) -> dict:
    data = {name: getattr(watch, name) for name in _FIELDS}
    visible = analysis.dedupe([o for o in offers if o.available and not o.hidden])
    new = [o for o in visible if o.condition == "new"]
    used = [o for o in visible if o.condition != "new"]
    rec = analysis.recommend(new) or analysis.recommend(used)
    spark: dict = {}
    if rec:
        key = (rec["best"]["variant_key"], rec["best"]["condition"])
        for row in sorted(history, key=lambda r: r.day):
            if (row.variant_key, row.condition) == key:
                spark[row.day] = row.price
    verdict = analysis.verdict(
        rec["best"]["price"] if rec else None, list(spark.values())[:-1],
        rec["best"]["original_price"] if rec else None,
    )
    usable_used = [o for o in used if not o.suspicious]
    return {
        "id": watch.id, **data,
        "last_checked_at": watch.last_checked_at, "next_run_at": watch.next_run_at,
        "report": watch.last_report or {},
        "offers": len(visible),
        "stores": len({o.store_key for o in visible}),
        "variants": len({o.variant_key for o in visible}),
        "best": rec["best"] if rec else None,
        "cheapest_used": analysis.offer_dict(usable_used[0]) if usable_used else None,
        "verdict": verdict,
        "spark": list(spark.values())[-30:],
        "image": (rec["best"]["image"] if rec else "") or
                 next((o.image for o in visible if o.image), ""),
    }


@router.get("/watches")
def list_watches(user: User = Depends(current_user), db: Session = Depends(get_db)):
    watches = db.scalars(
        select(Watch).where(Watch.user_id == user.id).order_by(Watch.created_at.desc())
    ).all()
    ids = [w.id for w in watches]
    offers: dict[int, list] = {i: [] for i in ids}
    history: dict[int, list] = {i: [] for i in ids}
    if ids:
        for offer in db.scalars(select(Offer).where(Offer.watch_id.in_(ids), Offer.available)):
            offers[offer.watch_id].append(offer)
        since = utcnow().date() - timedelta(days=60)
        for row in db.scalars(
            select(DailyBest).where(DailyBest.watch_id.in_(ids), DailyBest.day >= since)
        ):
            history[row.watch_id].append(row)
    return [summary(w, offers[w.id], history[w.id]) for w in watches]


def _validate_url(data: WatchIn) -> None:
    if data.kind == "url":
        try:
            assert_public_url(data.url)
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post("/watches", status_code=201)
def create_watch(
    data: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    count = len(db.scalars(select(Watch.id).where(Watch.user_id == user.id)).all())
    if count >= MAX_WATCHES:
        raise HTTPException(400, f"Limite de {MAX_WATCHES} monitorados")
    _validate_url(data)
    watch = Watch(user_id=user.id, **data.model_dump())
    db.add(watch)
    db.flush()
    queue_run(db, watch.id)
    db.commit()
    return summary(watch, [], [])


@router.put("/watches/{watch_id}")
def update_watch(
    watch_id: int, data: WatchIn, user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    watch = owned(db, user, watch_id)
    _validate_url(data)
    values = data.model_dump()
    changed = any(getattr(watch, name) != values[name] for name in _CRITERIA)
    for name, value in values.items():
        setattr(watch, name, value)
    if changed:
        reset_offers(db, watch)
    if watch.active:
        watch.next_run_at = utcnow()
        queue_run(db, watch.id)
    db.commit()
    return {"ok": True, "reset": changed}


@router.delete("/watches/{watch_id}")
def delete_watch(
    watch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    watch = owned(db, user, watch_id)
    reset_offers(db, watch)
    db.delete(watch)
    db.commit()
    return {"ok": True}


@router.post("/watches/{watch_id}/run")
def run_now(watch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    watch = owned(db, user, watch_id)
    if watch.last_checked_at and utcnow() - watch.last_checked_at < timedelta(seconds=45):
        raise HTTPException(429, "Verificado há instantes; aguarde um pouco")
    queue_run(db, watch.id)
    db.commit()
    return {"ok": True}


@router.get("/watches/{watch_id}")
def watch_detail(
    watch_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    watch = owned(db, user, watch_id)
    offers = db.scalars(select(Offer).where(Offer.watch_id == watch.id)).all()
    history = db.scalars(select(DailyBest).where(DailyBest.watch_id == watch.id)).all()
    visible = analysis.dedupe([o for o in offers if o.available and not o.hidden])
    hidden = [o for o in offers if o.hidden]
    return {
        **summary(watch, offers, history),
        "recommendation": analysis.recommend([o for o in visible if o.condition == "new"]),
        "variant_list": analysis.variants(visible, history),
        "offer_list": [analysis.offer_dict(o) for o in visible[:400]],
        "hidden_list": [analysis.offer_dict(o) for o in hidden[:100]],
    }


@router.post("/offers/{offer_id}/hidden")
def toggle_hidden(
    offer_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise HTTPException(404, "Oferta não encontrada")
    owned(db, user, offer.watch_id)
    offer.hidden = not offer.hidden
    # as cópias da mesma oferta vindas de outras fontes seguem o mesmo estado
    for other in db.scalars(
        select(Offer).where(
            Offer.watch_id == offer.watch_id, Offer.store_key == offer.store_key,
            Offer.title == offer.title,
        )
    ):
        other.hidden = offer.hidden
    db.commit()
    return {"hidden": offer.hidden}
