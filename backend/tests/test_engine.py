"""Fluxo do monitoramento: o que gera aviso (e o que não pode gerar)."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core import analysis
from app.core.engine import run_watch, today
from app.models import DailyBest, Notification, Offer, SourceStatus, Watch
from app.sources.base import Blocked, FoundOffer, StoreSource


class Shop(StoreSource):
    key = "loja"
    name = "Loja"

    def __init__(self):
        self.offers: list[FoundOffer] = []
        self.error = None

    async def search(self, fetcher, params):
        if self.error:
            raise self.error
        import copy

        return copy.deepcopy(self.offers)


def offer(ident, title, price, store="kabum", **extra):
    names = {"kabum": "KaBuM!", "amazon": "Amazon", "magalu": "Magazine Luiza", "olx": "OLX"}
    return FoundOffer(source="loja", external_id=ident, store=names[store], store_key=store,
                      title=title, url=f"https://x.example/{ident}", price=price, **extra)


def make_watch(session, user, **extra):
    watch = Watch(user_id=user.id, name="PS5", query="ps5", include_used=True, **extra)
    session.add(watch)
    session.commit()
    return watch


def run(session, watch, shop):
    asyncio.run(run_watch(session, watch.id, None, [shop]))


def kinds(session, skip=0):
    rows = session.scalars(select(Notification).order_by(Notification.id)).all()
    return [r.kind for r in rows][skip:]


BASE = [
    offer("1", "Console PS5 Slim 1TB", 4800, "kabum", installments=10, installment_value=480,
          interest_free=True),
    offer("2", "Console PS5 Slim 1TB", 5000, "amazon"),
]


def test_baseline_sends_only_one_summary(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = [*BASE, offer("3", "Controle DualSense para PS5", 350)]
    run(session, watch, shop)
    assert kinds(session) == ["started"]
    assert len(session.scalars(select(Offer)).all()) == 2  # acessório ficou de fora
    run(session, watch, shop)
    assert kinds(session) == ["started"], "sem mudança, sem aviso"


def test_baseline_reports_target_already_met(session, user):
    shop, watch = Shop(), make_watch(session, user, target_price=4900)
    shop.offers = BASE
    run(session, watch, shop)
    assert kinds(session) == ["started", "target"]


def test_price_drop_target_new_variant_and_new_store(session, user):
    shop, watch = Shop(), make_watch(session, user, target_price=4000)
    shop.offers = BASE
    run(session, watch, shop)
    shop.offers = [
        offer("1", "Console PS5 Slim 1TB", 4300, "kabum"),
        BASE[1],
        offer("4", "PlayStation 5 Pro 2TB", 7900, "amazon"),
        offer("5", "Console PS5 Slim 1TB", 4350, "magalu"),
    ]
    run(session, watch, shop)
    assert sorted(kinds(session, 1)) == ["new_offer", "new_variant", "price_drop"]
    drop = session.scalar(select(Notification).where(Notification.kind == "price_drop"))
    assert "10%" in drop.title and "R$ 4.800,00" in drop.body

    shop.offers = [offer("5", "Console PS5 Slim 1TB", 3990, "magalu")]
    run(session, watch, shop)
    assert kinds(session)[-1] == "target"
    assert kinds(session).count("price_drop") == 1, "o alvo substitui o aviso de queda"
    before = len(kinds(session))
    run(session, watch, shop)
    assert len(kinds(session)) == before, "aviso não se repete"


def test_lowest_price_uses_history(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = BASE
    run(session, watch, shop)
    for days in range(1, 6):
        session.add(DailyBest(watch_id=watch.id, variant_key="1tb", condition="new",
                              day=today() - timedelta(days=days), price=4790))
    session.commit()
    shop.offers = [offer("1", "Console PS5 Slim 1TB", 4500)]
    run(session, watch, shop)
    assert kinds(session)[-1] == "lowest"


def test_used_opportunity_and_suspicious_price(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = BASE
    run(session, watch, shop)
    shop.offers = [
        *BASE,
        offer("u1", "PS5 Slim 1TB seminovo", 2900, "olx", condition="used",
              location="Campinas"),
        offer("u2", "PS5 Slim 1TB", 900, "olx", condition="used"),
    ]
    run(session, watch, shop)
    assert kinds(session, 1) == ["used"]
    note = session.scalar(select(Notification).where(Notification.kind == "used"))
    assert "2.900" in note.title and "Campinas" in note.body
    scam = session.scalar(select(Offer).where(Offer.external_id == "u2"))
    assert scam.suspicious, "preço bom demais é marcado como suspeito"


def test_used_limit_is_respected(session, user):
    shop, watch = Shop(), make_watch(session, user, used_max_price=2500)
    shop.offers = BASE
    run(session, watch, shop)
    shop.offers = [*BASE, offer("u1", "PS5 Slim 1TB", 2900, "olx", condition="used")]
    run(session, watch, shop)
    assert kinds(session, 1) == []


def test_coupon_and_back_in_stock(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = BASE
    run(session, watch, shop)
    shop.offers = [offer("1", "Console PS5 Slim 1TB", 4800, coupon="Economize R$ 200 com cupom"),
                   BASE[1]]
    run(session, watch, shop)
    assert kinds(session, 1) == ["coupon"]

    shop.offers = [BASE[1]]
    for _ in range(3):
        run(session, watch, shop)
    gone = session.scalar(select(Offer).where(Offer.external_id == "1"))
    assert not gone.available
    shop.offers = BASE
    run(session, watch, shop)
    assert kinds(session)[-1] == "restock"


def test_blocked_source_backs_off_and_keeps_offers(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = BASE
    run(session, watch, shop)
    shop.error = Blocked("loja recusou o acesso (HTTP 403)")
    for _ in range(5):
        run(session, watch, shop)
    status = session.get(SourceStatus, "loja", populate_existing=True)
    assert status.state == "blocked" and status.failures == 1 and status.blocked_until
    assert all(o.available for o in session.scalars(select(Offer)))
    session.refresh(watch)
    assert watch.last_report["sources"]["loja"]["state"] == "blocked"


def test_used_disabled_and_imported_history(session, user):
    shop, watch = Shop(), make_watch(session, user)
    watch.include_used = False
    session.commit()
    history = [((today() - timedelta(days=d)).isoformat(), 5000.0 + d) for d in range(8, 0, -1)]
    shop.offers = [
        offer("1", "Console PS5 Slim 1TB", 4500, history=history),
        offer("u", "PS5 Slim 1TB usado", 3000, "olx"),
    ]
    run(session, watch, shop)
    assert [o.external_id for o in session.scalars(select(Offer))] == ["1"]
    rows = session.scalars(select(DailyBest)).all()
    assert len(rows) == 9
    [variant] = analysis.variants(session.scalars(select(Offer)).all(), rows)
    assert variant["verdict"]["level"] == "record"


def test_verdict_exposes_fake_discount():
    history = [100.0] * 10
    assert analysis.verdict(100, history, original=200)["level"] == "fake"
    assert analysis.verdict(115, history)["level"] == "expensive"
    assert analysis.verdict(93, history)["level"] == "record"
    assert analysis.verdict(100, [100.0] * 2)["level"] == "learning"


def test_recommendation_prefers_trusted_store(session, user):
    shop, watch = Shop(), make_watch(session, user)
    shop.offers = [*BASE, FoundOffer(source="loja", external_id="z", store="Loja Estranha",
                                     store_key="loja-estranha", title="Console PS5 Slim 1TB",
                                     url="https://x.example/z", price=4000)]
    run(session, watch, shop)
    rec = analysis.recommend(session.scalars(select(Offer)).all())
    assert rec["best"]["store_key"] == "kabum"
    assert rec["cheapest"]["store_key"] == "loja-estranha"
    assert rec["installment"]["installments"] == 10
