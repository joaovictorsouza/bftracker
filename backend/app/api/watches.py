from __future__ import annotations

from datetime import timedelta
import io
import json
from pathlib import Path
from urllib.parse import quote_plus
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import analysis, importer
from ..core.appsettings import get_value
from ..core.engine import reset_offers
from ..core.radar import backfill_watch_from_deals
from ..db import get_db
from ..models import ApiToken, DailyBest, Offer, RunRequest, User, Watch, utcnow
from ..schemas import ImportIn, TokenCreateIn, WatchIn
from ..security import current_user, generate_api_token, is_https_request
from ..sources.base import SourceError, assert_public_url
from ..sources.x_twitter import build_x_live_url

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
    backfill_watch_from_deals(db, watch)
    queue_run(db, watch.id)
    db.commit()
    offers = db.scalars(select(Offer).where(Offer.watch_id == watch.id, Offer.available)).all()
    history = db.scalars(select(DailyBest).where(DailyBest.watch_id == watch.id)).all()
    return summary(watch, offers, history)


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
        backfill_watch_from_deals(db, watch)
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


@router.post("/import")
def import_offers(
    data: ImportIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Recebe anúncios e ofertas que o usuário capturou no próprio navegador."""
    items = [importer.Item(**item.model_dump()) for item in data.items]
    deals = [importer.DealItem(**d.model_dump()) for d in data.deals] if data.deals else None
    return importer.import_items(db, user, items, deals)


def _watch_links(watch: Watch) -> dict[str, str]:
    q = quote_plus(watch.query)
    slug_q = "-".join(watch.query.strip().lower().split())
    area = f"estado-{watch.used_state}" if watch.used_state else "brasil"
    olx_price = f"&pe={int(watch.used_max_price or watch.max_price)}" if (
        watch.used_max_price or watch.max_price
    ) else ""
    return {
        "ml_new": f"https://lista.mercadolivre.com.br/{quote_plus(slug_q)}_NoIndex_True",
        "ml_used": f"https://lista.mercadolivre.com.br/{quote_plus(slug_q)}_ITEM*CONDITION_2230581_NoIndex_True",
        "olx": f"https://www.olx.com.br/{area}?q={q}&sf=1{olx_price}",
        "x_live": build_x_live_url([watch.query]),
        "hardmob": "https://www.hardmob.com.br/forums/407-Promocoes",
    }


@router.get("/tokens")
def list_tokens(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.id.desc())
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "prefix": r.prefix,
            "last_used_at": r.last_used_at,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.post("/tokens", status_code=201)
def create_token(
    data: TokenCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    existing_count = len(
        db.scalars(select(ApiToken.id).where(ApiToken.user_id == user.id)).all()
    )
    if existing_count >= 10:
        raise HTTPException(400, "Limite de 10 chaves atingido; revogue uma antiga primeiro")
    raw, prefix, token_hash = generate_api_token()
    row = ApiToken(user_id=user.id, name=data.name.strip(), prefix=prefix, token_hash=token_hash)
    db.add(row)
    db.commit()
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "token": raw,
        "created_at": row.created_at,
    }


@router.delete("/tokens/{token_id}")
def revoke_token(
    token_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.get(ApiToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "Chave não encontrada")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/ext/ping")
def ext_ping(user: User = Depends(current_user), db: Session = Depends(get_db)):
    watches = db.scalars(
        select(Watch).where(Watch.user_id == user.id, Watch.active, Watch.kind == "product")
    ).all()
    queries = [w.query for w in watches if w.query]
    return {
        "ok": True,
        "username": user.username,
        "watches_count": len(watches),
        "x_all_url": build_x_live_url(queries),
        "hardmob_url": "https://www.hardmob.com.br/forums/407-Promocoes",
        "watches": [
            {
                "id": w.id,
                "name": w.name,
                "query": w.query,
                "target_price": w.target_price,
                "include_used": w.include_used,
                "links": _watch_links(w),
            }
            for w in watches
        ],
    }


def _extension_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parents[2], here.parents[3]):
        candidate = parent / "extension"
        if (candidate / "manifest.json").is_file():
            return candidate
    raise HTTPException(404, "Arquivos da extensão não encontrados no servidor")


@router.get("/extension.zip")
def download_extension(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    ext_dir = _extension_dir()
    scheme = "https" if is_https_request(request) else request.url.scheme
    origin = f"{scheme}://{request.headers.get('host') or request.url.netloc}"
    configured = get_value(db, "public_url").strip().rstrip("/")
    default_url = configured if configured and "localhost" not in configured else origin

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(ext_dir.rglob("*")):
            if file_path.is_file() and not file_path.name.startswith("."):
                arcname = f"bftracker-companion/{file_path.relative_to(ext_dir).as_posix()}"
                zf.writestr(arcname, file_path.read_bytes())
        zf.writestr(
            "bftracker-companion/default-config.json",
            json.dumps({"serverUrl": default_url}, indent=2),
        )
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="bftracker-companion.zip"',
            "Cache-Control": "no-store",
        },
    )
