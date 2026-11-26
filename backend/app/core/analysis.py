"""Resumo de um monitorado: melhor onde comprar por variante e se o preço é bom mesmo."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from .stores import trust_of

SOURCE_PRIORITY = {"url": 0, "amazon": 1, "kabum": 1, "mercadolivre": 1, "olx": 1,
                   "zoom": 3, "buscape": 4}


def offer_dict(offer) -> dict:
    return {
        "id": offer.id, "source": offer.source, "store": offer.store,
        "store_key": offer.store_key, "seller": offer.seller, "marketplace": offer.marketplace,
        "title": offer.title, "url": offer.url, "image": offer.image, "price": offer.price,
        "card_price": offer.card_price, "original_price": offer.original_price,
        "installments": offer.installments, "installment_value": offer.installment_value,
        "interest_free": offer.interest_free, "pix": offer.pix,
        "free_shipping": offer.free_shipping, "coupon": offer.coupon,
        "condition": offer.condition, "location": offer.location,
        "variant_key": offer.variant_key, "variant_label": offer.variant_label,
        "suspicious": offer.suspicious, "available": offer.available, "hidden": offer.hidden,
        "previous_price": offer.previous_price, "lowest_price": offer.lowest_price,
        "first_seen_at": offer.first_seen_at, "last_seen_at": offer.last_seen_at,
        "changed_at": offer.changed_at, "trust": trust_of(offer.store_key),
    }


def dedupe(offers: list) -> list:
    """A mesma oferta vista pela loja e por comparadores aparece uma vez só (fica a
    versão da fonte mais direta, preferindo a que informa parcelamento)."""
    best: dict[tuple, object] = {}
    for offer in sorted(
        offers,
        key=lambda o: (SOURCE_PRIORITY.get(o.source, 2), not o.installments, o.id),
    ):
        if offer.source == "olx" or offer.condition != "new":
            key = (offer.source, offer.external_id)
        else:
            key = (offer.store_key, offer.variant_key, round(offer.price))
        if key not in best:
            best[key] = offer
    return sorted(best.values(), key=lambda o: o.price)


def verdict(current: float | None, history: list[float], original: float | None = None) -> dict:
    """Compara o preço atual com o histórico para expor "metade do dobro"."""
    if current is None:
        return {"level": "none", "label": "Sem oferta disponível"}
    if len(history) < 5:
        return {"level": "learning", "label": "Formando histórico", "days": len(history)}
    low, typical = min(history), median(history)
    change = round((current - typical) / typical * 100, 1)
    info = {"lowest": low, "median": round(typical, 2), "change": change, "days": len(history)}
    if current < low * 0.995:
        return {"level": "record", "label": "Menor preço já visto", **info}
    if current <= low * 1.03 and current < typical * 0.97:
        return {"level": "great", "label": "Ótimo momento", **info}
    if current <= typical * 0.95:
        return {"level": "good", "label": "Abaixo do normal", **info}
    claimed = original and original > current * 1.15
    if claimed and current >= typical * 0.99:
        return {"level": "fake", "label": "Desconto enganoso: preço igual ao de sempre", **info}
    if current >= typical * 1.08:
        return {"level": "expensive", "label": "Acima do normal: espere", **info}
    return {"level": "fair", "label": "Preço normal", **info}


def recommend(offers: list) -> dict | None:
    """Melhor compra: menor preço entre lojas confiáveis; informa a mais barata de todas."""
    usable = [o for o in offers if o.available and not o.suspicious and not o.hidden]
    if not usable:
        return None
    cheapest = min(usable, key=lambda o: o.price)
    trusted = [o for o in usable if trust_of(o.store_key)["score"] >= 65]
    pick = min(trusted, key=lambda o: o.price) if trusted else cheapest
    installment = [o for o in trusted or usable if o.interest_free and (o.installments or 0) > 1]
    best_installment = min(
        installment, key=lambda o: (o.card_price or o.price, -(o.installments or 0)),
        default=None,
    )
    return {
        "best": offer_dict(pick),
        "cheapest": offer_dict(cheapest) if cheapest.id != pick.id else None,
        "installment": offer_dict(best_installment) if best_installment else None,
    }


def variants(offers: list, history_rows: list) -> list[dict]:
    history: dict[tuple[str, str], list] = defaultdict(list)
    for row in history_rows:
        history[(row.variant_key, row.condition)].append(row)
    grouped: dict[str, list] = defaultdict(list)
    for offer in offers:
        grouped[offer.variant_key].append(offer)
    out = []
    for key, group in grouped.items():
        new = [o for o in group if o.condition == "new"]
        used = [o for o in group if o.condition != "new"]
        rec = recommend(new)
        used_rec = recommend(used)
        rows = sorted(history.get((key, "new"), []), key=lambda r: r.day)
        past = [r.price for r in rows[:-1]]
        current = rec["best"]["price"] if rec else None
        usable = [o for o in new if o.available and not o.suspicious]
        out.append(
            {
                "key": key,
                "label": group[0].variant_label,
                "offers": len([o for o in group if o.available]),
                "stores": len({o.store_key for o in group if o.available}),
                "new": rec,
                "used": used_rec,
                "image": next((o.image for o in group if o.image), ""),
                "verdict": verdict(
                    min((o.price for o in usable), default=current), past,
                    rec["best"]["original_price"] if rec else None,
                ),
                "history": [
                    {"day": r.day.isoformat(), "price": r.price, "store": r.store,
                     "imported": r.imported}
                    for r in rows[-120:]
                ],
            }
        )
    out.sort(key=lambda v: (v["new"] is None, -(v["stores"]),
                            v["new"]["best"]["price"] if v["new"] else 0))
    return out
