"""Executa um monitoramento: coleta nas fontes, atualiza o histórico e detecta
oportunidades (variante nova, queda, menor preço, preço-alvo, usado barato…)."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import DailyBest, Offer, PricePoint, Watch, utcnow
from ..notify.dispatch import notify
from ..sources.base import (
    Blocked,
    Fetcher,
    FoundOffer,
    NotConfigured,
    SearchParams,
    SourceError,
    StoreSource,
)
from ..sources.generic import fetch_product
from . import matching
from .analysis import dedupe
from .sourcestate import get_status, is_waiting, mark_failure, mark_ok
from .stores import trust_of
from .text import brl, clip, short_hash

log = logging.getLogger(__name__)

MISSES_TO_UNAVAILABLE = 3


def today() -> date:
    return utcnow().astimezone(ZoneInfo(get_settings().timezone)).date()


def criteria_of(watch: Watch) -> matching.Criteria:
    return matching.Criteria(
        query=watch.query,
        include_terms=list(watch.include_terms or []),
        exclude_terms=list(watch.exclude_terms or []),
        min_price=watch.min_price,
        max_price=watch.max_price,
    )


@dataclass
class Collected:
    offers: list[tuple[FoundOffer, str, str]] = field(default_factory=list)  # (oferta, var, rótulo)
    report: dict = field(default_factory=dict)
    ok_sources: set[str] = field(default_factory=set)
    # coleta parcial (ex.: anúncios enviados pelo navegador): não representa o mercado todo
    partial: bool = False


def selected_sources(db: Session, watch: Watch, sources: list[StoreSource]) -> list[StoreSource]:
    chosen = []
    wanted = set(watch.sources or [])
    for source in sources:
        if source.used_only and not watch.include_used:
            continue
        if wanted and source.key not in wanted:
            continue
        status = get_status(db, source.key, source.name, "store")
        if not status.enabled:
            continue
        chosen.append(source)
    return chosen


async def collect(
    db: Session, watch: Watch, fetcher: Fetcher, sources: list[StoreSource]
) -> Collected:
    result = Collected()
    if watch.kind == "url":
        try:
            offer = await fetch_product(fetcher, watch.url)
            result.offers.append((offer, "padrao", "Padrão"))
            result.ok_sources.add("url")
            result.report["url"] = {"state": "ok", "name": offer.store, "items": 1}
        except Blocked as exc:
            result.report["url"] = {"state": "blocked", "name": "Página", "message": str(exc)}
        except SourceError as exc:
            result.report["url"] = {"state": "error", "name": "Página", "message": str(exc)}
        return result

    criteria = criteria_of(watch)
    params = SearchParams(
        query=watch.query,
        include_used=watch.include_used,
        used_state=watch.used_state,
        used_region=watch.used_region,
        min_price=watch.min_price,
        max_price=watch.max_price,
        is_relevant=lambda title: matching.matches(title, criteria),
    )
    runnable = []
    for source in selected_sources(db, watch, sources):
        status = get_status(db, source.key, source.name, "store")
        if is_waiting(status):
            result.report[source.key] = {
                "state": status.state, "name": source.name,
                "message": f"Aguardando nova tentativa: {status.message}",
            }
        else:
            runnable.append(source)
    db.commit()

    async def run(source: StoreSource):
        try:
            return source, await asyncio.wait_for(source.search(fetcher, params), 120), None
        except Exception as exc:  # noqa: BLE001 - uma fonte nunca derruba as outras
            if not isinstance(exc, (SourceError, TimeoutError)):
                log.exception("Erro na fonte %s", source.key)
            return source, [], exc

    for source, offers, error in await asyncio.gather(*(run(s) for s in runnable)):
        if error is not None:
            if isinstance(error, NotConfigured):
                result.report[source.key] = {
                    "state": "unconfigured", "name": source.name, "message": str(error)
                }
                continue
            state = "blocked" if isinstance(error, Blocked) else "error"
            message = str(error) or type(error).__name__
            mark_failure(db, source.key, source.name, "store", state, message)
            result.report[source.key] = {"state": state, "name": source.name, "message": message}
            continue
        kept = 0
        for offer in offers:
            title = offer.match_title or offer.title
            if offer.condition != "new" and not watch.include_used:
                continue
            if offer.condition == "new":
                offer.condition = matching.detect_condition(offer.title, "new")
                if offer.condition != "new" and not watch.include_used:
                    continue
            if not matching.matches(title, criteria, offer.price):
                continue
            if offer.match_title and any(
                matching.contains_term(matching.normalize(offer.title), t)
                for t in criteria.exclude_terms
            ):
                continue
            described = matching.best_variant_title(offer.title, offer.match_title, criteria)
            key, label = matching.variant_of(described, watch.query)
            result.offers.append((offer, key, label))
            kept += 1
        mark_ok(db, source.key, source.name, "store", kept)
        result.ok_sources.add(source.key)
        result.report[source.key] = {"state": "ok", "name": source.name, "items": kept}
    db.commit()
    return result


def screen_prices(
    offers: list[tuple[FoundOffer, str, str]], known_new: list[tuple[str, float]] | None = None
) -> tuple[list, set[int]]:
    """Descarta itens que quase certamente são acessórios (muito abaixo da mediana) e
    marca como suspeitos os preços bons demais para ser verdade."""
    known_new = known_new or []
    new_prices = [o.price for o, _, _ in offers if o.condition == "new"]
    new_prices += [price for _, price in known_new]
    overall = median(new_prices) if len(new_prices) >= 6 else None
    if overall:
        offers = [item for item in offers if item[0].price >= overall * 0.22]
    by_variant: dict[str, list[float]] = defaultdict(list)
    for offer, key, _ in offers:
        if offer.condition == "new":
            by_variant[key].append(offer.price)
    for key, price in known_new:
        by_variant[key].append(price)
    every_new = [price for prices in by_variant.values() for price in prices]
    suspicious: set[int] = set()
    for offer, key, _ in offers:
        prices = by_variant.get(key, [])
        reference = median(prices) if len(prices) >= 3 else overall
        if offer.condition != "new" and not reference:
            # para usados basta saber quanto custa um novo
            known = prices or every_new
            reference = median(known) if known else None
        if not reference:
            continue
        limit = 0.55 if offer.condition == "new" else 0.35
        if offer.price < reference * limit:
            suspicious.add(id(offer))
    return offers, suspicious


def _offer_line(offer: Offer) -> str:
    parts = [f"{brl(offer.price)} na {offer.store}"]
    if offer.pix:
        parts[0] += " (Pix)"
    if offer.installments and offer.installment_value and offer.installments > 1:
        interest = " sem juros" if offer.interest_free else ""
        parts.append(f"ou {offer.installments}x de {brl(offer.installment_value)}{interest}")
    if offer.free_shipping:
        parts.append("frete grátis")
    if offer.coupon:
        flash = offer.coupon.startswith("Oferta relâmpago")
        parts.append(f"⚡ {offer.coupon}" if flash else f"cupom: {offer.coupon}")
    if offer.location:
        parts.append(offer.location)
    return " · ".join(parts)


def _warning(offer: Offer) -> str:
    if offer.suspicious:
        return "\n⚠️ Preço muito abaixo do normal: risco de golpe, confira com cuidado."
    if offer.condition == "used":
        return "\nUsado: veja o produto pessoalmente e não pague adiantado."
    if trust_of(offer.store_key)["level"] in {"atencao", "desconhecida"}:
        return "\n⚠️ Confira a reputação da loja antes de comprar."
    return ""


class Events:
    def __init__(self, db: Session, watch: Watch):
        self.db, self.watch, self.count = db, watch, 0

    def send(self, kind: str, title: str, body: str, offer: Offer | None, key: str,
             priority: int = 2) -> None:
        if notify(
            self.db,
            self.watch.user,
            kind=kind,
            title=title,
            body=body,
            dedupe_key=f"{kind}:{self.watch.id}:{key}",
            priority=priority,
            url=offer.url if offer else "",
            path=f"/monitorados/{self.watch.id}",
            image=offer.image if offer else "",
            watch_id=self.watch.id,
        ):
            self.count += 1


def apply_results(db: Session, watch: Watch, collected: Collected) -> dict:
    now = utcnow()
    day = today()
    baseline = not watch.baseline_done
    events = Events(db, watch)
    existing = {
        (o.source, o.external_id): o
        for o in db.scalars(select(Offer).where(Offer.watch_id == watch.id))
    }
    # numa coleta parcial, os preços de novos já conhecidos servem de referência
    context = [
        o for o in existing.values()
        if collected.partial and o.available and o.condition == "new"
        and not o.suspicious and not o.hidden
    ]
    offers, suspicious = screen_prices(
        collected.offers, [(o.variant_key, o.price) for o in context]
    )
    known_variants = {o.variant_key for o in existing.values()}
    known_combos = {(o.store_key, o.variant_key, o.condition) for o in existing.values()}
    history_rows = db.scalars(select(DailyBest).where(DailyBest.watch_id == watch.id)).all()
    past: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in history_rows:
        if row.day < day:
            past[(row.variant_key, row.condition)].append(row.price)
    todays = {(r.variant_key, r.condition): r for r in history_rows if r.day == day}

    seen: dict[tuple[str, str], Offer] = {}
    new_offers: list[Offer] = []
    drops: list[tuple[float, Offer, float]] = []
    restocked: list[Offer] = []
    new_coupons: list[Offer] = []

    for found, variant_key, variant_label in offers:
        ident = (found.source, found.external_id[:200])
        if ident in seen:
            continue
        row = existing.get(ident)
        values = dict(
            store=found.store[:80], store_key=found.store_key[:60], seller=found.seller[:120],
            marketplace=found.marketplace, title=found.title, url=found.url,
            image=found.image, card_price=found.card_price,
            original_price=found.original_price, installments=found.installments,
            installment_value=found.installment_value, interest_free=found.interest_free,
            pix=found.pix, free_shipping=found.free_shipping,
            condition=found.condition, location=found.location[:160],
            variant_key=variant_key, variant_label=variant_label,
            suspicious=id(found) in suspicious,
        )
        if row is None:
            row = Offer(
                watch_id=watch.id, source=found.source, external_id=ident[1],
                price=found.price, lowest_price=found.price, coupon=found.coupon[:200], **values,
            )
            db.add(row)
            db.flush()
            db.add(PricePoint(offer_id=row.id, price=found.price))
            new_offers.append(row)
        else:
            if not row.available:
                restocked.append(row)
            if found.coupon and found.coupon[:200] != row.coupon:
                new_coupons.append(row)
            if abs(found.price - row.price) >= 0.01:
                if found.price < row.price:
                    drops.append(((row.price - found.price) / row.price * 100, row, row.price))
                row.previous_price = row.price
                row.price = found.price
                row.changed_at = now
                row.lowest_price = min(row.lowest_price, found.price)
                db.add(PricePoint(offer_id=row.id, price=found.price))
            row.coupon = found.coupon[:200]
            for key, value in values.items():
                setattr(row, key, value)
        row.available = True
        row.missed_runs = 0
        row.last_seen_at = now
        seen[ident] = row

        # histórico importado do comparador (antes de existir monitoramento próprio)
        if found.history and found.condition == "new":
            for stamp, price in found.history[-90:]:
                when = date.fromisoformat(stamp)
                key = (variant_key, "new", when)
                if when >= day:
                    continue
                current = db.scalar(
                    select(DailyBest).where(
                        DailyBest.watch_id == watch.id, DailyBest.variant_key == variant_key,
                        DailyBest.condition == "new", DailyBest.day == when,
                    )
                )
                if current is None:
                    db.add(DailyBest(watch_id=watch.id, variant_key=key[0], condition=key[1],
                                     day=when, price=price, store="Comparador", imported=True))
                    db.flush()
                    past[(variant_key, "new")].append(price)
                elif current.imported and price < current.price:
                    current.price = price

    for ident, row in existing.items():
        if ident not in seen and (row.source in collected.ok_sources):
            row.missed_runs += 1
            if row.missed_runs >= MISSES_TO_UNAVAILABLE:
                row.available = False

    live = [o for o in seen.values() if not o.hidden]
    reliable = [o for o in live if not o.suspicious]
    best: dict[tuple[str, str], Offer] = {}
    for offer in reliable:
        key = (offer.variant_key, offer.condition)
        if key not in best or offer.price < best[key].price:
            best[key] = offer
    for key, offer in best.items():
        row = todays.get(key)
        if row is None:
            db.add(DailyBest(watch_id=watch.id, variant_key=key[0], condition=key[1], day=day,
                             price=offer.price, store=offer.store))
        elif offer.price < row.price or row.imported:
            row.price, row.store, row.imported = offer.price, offer.store, False

    new_best = {k[0]: o for k, o in best.items() if k[1] == "new"}
    if collected.partial:
        for offer in context:
            current = new_best.get(offer.variant_key)
            if current is None or offer.price < current.price:
                new_best[offer.variant_key] = offer
    if baseline and collected.partial:
        pass  # a primeira busca completa ainda vai formar a base
    elif baseline:
        if live:
            _baseline_events(events, watch, live, new_best, best)
    else:
        _change_events(events, watch, live, best, new_best, past, known_variants, known_combos,
                       new_offers, drops, restocked, new_coupons)

    if not collected.partial:
        watch.baseline_done = watch.baseline_done or bool(live)
    db.flush()
    return {"found": len(live), "new": len(new_offers), "notifications": events.count}


def _baseline_events(events: Events, watch: Watch, live, new_best, best) -> None:
    live = dedupe(live)  # a mesma oferta vista por loja e comparador conta uma vez
    ranked = sorted(new_best.values(), key=lambda o: o.price) or sorted(
        best.values(), key=lambda o: o.price
    )
    if not ranked:
        return
    lines = [f"• {o.variant_label}: {_offer_line(o)}" for o in ranked[:5]]
    stores_count = len({o.store_key for o in live})
    used = sorted(
        (o for o in live if o.condition != "new" and not o.suspicious), key=lambda o: o.price
    )
    if used and new_best:
        lines.append(f"• Usados a partir de {_offer_line(used[0])}")
    events.send(
        "started",
        f"{watch.name}: monitorando {len(live)} ofertas em {stores_count} lojas",
        "\n".join(lines),
        ranked[0],
        "baseline",
    )
    if watch.target_price:
        hits = [o for o in live if not o.suspicious and o.price <= watch.target_price]
        if hits:
            hit = min(hits, key=lambda o: o.price)
            events.send(
                "target", f"🎯 {watch.name} já está no seu preço-alvo: {brl(hit.price)}",
                f"{clip(hit.title, 120)}\n{_offer_line(hit)}{_warning(hit)}",
                hit, f"{round(hit.price)}", 3,
            )


def _change_events(events: Events, watch: Watch, live, best, new_best, past, known_variants,
                   known_combos, new_offers, drops, restocked, new_coupons) -> None:
    covered: set[int] = set()
    overall_new = min((o.price for o in new_best.values()), default=None)

    if watch.target_price:
        hits = sorted(
            (o for o in live if not o.suspicious and o.price <= watch.target_price),
            key=lambda o: o.price,
        )
        if hits:
            hit = hits[0]
            events.send(
                "target", f"🎯 Preço-alvo atingido: {watch.name} por {brl(hit.price)}",
                f"{clip(hit.title, 120)}\n{_offer_line(hit)}{_warning(hit)}",
                hit, f"{round(hit.price)}", 3,
            )
            covered.add(hit.id)

    for (variant, condition), offer in best.items():
        history = past.get((variant, condition), [])
        if condition != "new" or len(history) < 3 or offer.id in covered:
            continue
        low = min(history)
        if offer.price < low * 0.99:
            events.send(
                "lowest",
                f"📉 Menor preço já visto: {watch.name} ({offer.variant_label})",
                f"{_offer_line(offer)}\nAntes, o menor era {brl(low)} "
                f"({len(history)} dias de histórico).{_warning(offer)}",
                offer, f"{variant}:{round(offer.price)}", 3,
            )
            covered.add(offer.id)

    fresh_variants: dict[str, list[Offer]] = defaultdict(list)
    for offer in new_offers:
        # usado de variante inédita é tratado como oportunidade, não como lançamento
        if (offer.condition == "new" and offer.variant_key not in known_variants
                and not offer.suspicious):
            fresh_variants[offer.variant_key].append(offer)
    for variant, group in list(fresh_variants.items())[:4]:
        cheapest = min(group, key=lambda o: o.price)
        events.send(
            "new_variant",
            f"🆕 Nova variante de {watch.name}: {cheapest.variant_label}",
            f"{clip(cheapest.title, 130)}\n{_offer_line(cheapest)}{_warning(cheapest)}",
            cheapest, variant,
        )
        covered.update(o.id for o in group)

    # melhor queda por variante, só se continuar competitiva
    chosen: dict[tuple[str, str], tuple[float, Offer, float]] = {}
    for percent, offer, before in drops:
        if percent < max(watch.drop_percent, 0.5) or offer.id in covered or offer.suspicious:
            continue
        reference = best.get((offer.variant_key, offer.condition))
        if reference and offer.price > reference.price * 1.15:
            continue
        key = (offer.variant_key, offer.condition)
        if key not in chosen or offer.price < chosen[key][1].price:
            chosen[key] = (percent, offer, before)
    for percent, offer, before in sorted(chosen.values(), key=lambda c: -c[0])[:5]:
        events.send(
            "price_drop",
            f"⬇️ {watch.name} caiu {percent:.0f}%: {brl(offer.price)}",
            f"{clip(offer.title, 120)}\nDe {brl(before)} para {_offer_line(offer)}"
            f"{_warning(offer)}",
            offer, f"{offer.id}:{round(offer.price)}", 3 if percent >= 15 else 2,
        )
        covered.add(offer.id)

    for offer in restocked[:3]:
        reference = best.get((offer.variant_key, offer.condition))
        if offer.id in covered or offer.suspicious or offer.condition != "new":
            continue
        if reference and offer.price <= reference.price * 1.05:
            events.send(
                "restock", f"📦 De volta ao estoque: {watch.name}",
                f"{clip(offer.title, 120)}\n{_offer_line(offer)}{_warning(offer)}",
                offer, f"{offer.id}:{today().isoformat()}",
            )
            covered.add(offer.id)

    for offer in sorted(new_coupons + [o for o in new_offers if o.coupon], key=lambda o: o.price):
        reference = new_best.get(offer.variant_key)
        if offer.id in covered or offer.suspicious:
            continue
        if reference and offer.price > reference.price * 1.2:
            continue
        events.send(
            "coupon",
            f"⚡ Oferta relâmpago: {watch.name} ({offer.store})"
            if offer.coupon.startswith("Oferta relâmpago")
            else f"🎟️ Cupom possível em {watch.name} ({offer.store})",
            f"{clip(offer.title, 120)}\n{_offer_line(offer)}{_warning(offer)}",
            offer, f"{offer.store_key}:{short_hash(offer.coupon)}:{offer.variant_key}",
        )
        covered.add(offer.id)

    fresh_stores = []
    announced: set[tuple[str, str, str]] = set()
    for offer in sorted(new_offers, key=lambda o: o.price):
        combo = (offer.store_key, offer.variant_key, offer.condition)
        if (offer.id in covered or offer.suspicious or offer.condition != "new"
                or combo in known_combos or combo in announced
                or offer.variant_key in fresh_variants):
            continue
        reference = new_best.get(offer.variant_key)
        if reference and offer.price <= reference.price * 1.10:
            fresh_stores.append(offer)
            announced.add(combo)
    if fresh_stores:
        first = fresh_stores[0]
        lines = [f"• {o.variant_label}: {_offer_line(o)}" for o in fresh_stores[:5]]
        title = (
            f"✨ Nova oferta de {watch.name}: {brl(first.price)} na {first.store}"
            if len(fresh_stores) == 1
            else f"✨ {len(fresh_stores)} novas ofertas de {watch.name}"
        )
        events.send(
            "new_offer", title, "\n".join(lines) + _warning(first), first,
            short_hash(*sorted(f"{o.store_key}{o.variant_key}{round(o.price)}"
                               for o in fresh_stores)),
        )

    used_values = [o.price for o in live if o.condition != "new" and not o.suspicious]
    used_median = median(used_values) if len(used_values) >= 5 else None
    bargains = []
    for offer in new_offers + [d[1] for d in drops]:
        if offer.condition == "new" or offer.suspicious or offer.id in covered:
            continue
        reference = new_best.get(offer.variant_key)
        new_price = reference.price if reference else overall_new
        if watch.used_max_price:
            good = offer.price <= watch.used_max_price
        else:
            good = bool(
                (new_price and offer.price <= new_price * 0.65)
                or (used_median and offer.price <= used_median * 0.78)
            )
        if good:
            bargains.append(offer)
            covered.add(offer.id)
    for offer in sorted(bargains, key=lambda o: o.price)[:4]:
        context = []
        if overall_new:
            context.append(f"Novo a partir de {brl(overall_new)}")
        if used_median:
            context.append(f"mediana dos usados {brl(used_median)}")
        events.send(
            "used",
            f"♻️ Oportunidade em usado: {watch.name} por {brl(offer.price)}",
            f"{clip(offer.title, 120)}\n{_offer_line(offer)}\n{' · '.join(context)}"
            f"{_warning(offer)}",
            offer, f"{offer.source}:{offer.external_id}:{round(offer.price)}",
        )


def schedule_next(watch: Watch) -> None:
    minimum = get_settings().min_interval_minutes
    watch.next_run_at = utcnow() + timedelta(minutes=max(watch.interval_minutes, minimum))


async def run_watch(
    db: Session, watch_id: int, fetcher: Fetcher, sources: list[StoreSource]
) -> dict | None:
    watch = db.get(Watch, watch_id)
    if watch is None:
        return None
    started = utcnow()
    schedule_next(watch)
    db.commit()
    collected = await collect(db, watch, fetcher, sources)
    watch = db.get(Watch, watch_id, populate_existing=True)
    if watch is None:  # excluído durante a coleta
        return None
    summary = apply_results(db, watch, collected)
    watch.last_checked_at = utcnow()
    watch.last_report = {
        "sources": collected.report,
        "summary": summary,
        "seconds": round((utcnow() - started).total_seconds(), 1),
    }
    db.commit()
    return summary


def reset_offers(db: Session, watch: Watch) -> None:
    """Quando os critérios mudam, recomeça a base de comparação."""
    ids = select(Offer.id).where(Offer.watch_id == watch.id)
    db.execute(delete(PricePoint).where(PricePoint.offer_id.in_(ids)))
    db.execute(delete(Offer).where(Offer.watch_id == watch.id))
    db.execute(delete(DailyBest).where(DailyBest.watch_id == watch.id))
    watch.baseline_done = False
    watch.last_report = {}
