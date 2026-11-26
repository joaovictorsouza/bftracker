import asyncio
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.radar import cleanup, ingest_coupons, ingest_deals
from app.models import Coupon, Deal, Interest, Notification, Offer, SourceStatus, Watch, utcnow
from app.sources.base import FeedSource, FoundCoupon, FoundDeal
from app.worker import Worker


def deal(ident="1", title="Console PS5 Slim por R$ 3.999 na Amazon", source="tg:a", **extra):
    extra.setdefault("published_at", utcnow())
    return FoundDeal(source=source, source_name=source, external_id=ident, title=title,
                     url=f"https://x.example/{source}/{ident}", **extra)


def notes(session):
    return session.scalars(select(Notification).order_by(Notification.id)).all()


def only_interest(session, user, **values):
    session.execute(delete(Interest))
    base = dict(user_id=user.id, name="i", categories=[], keywords=[], exclude_terms=[],
                stores=[], max_per_hour=10)
    session.add(Interest(**(base | values)))
    session.commit()


def test_baseline_is_silent_and_old_deals_do_not_alert(session, user):
    only_interest(session, user, categories=["games"])
    assert ingest_deals(session, [deal()], baseline=True) == {"new": 1, "alerts": 0}
    old = deal("2", published_at=utcnow() - timedelta(hours=5))
    assert ingest_deals(session, [old], baseline=False)["alerts"] == 0
    stored = session.scalar(select(Deal).where(Deal.external_id == "1"))
    assert (stored.store_key, stored.price, stored.category) == ("amazon", 3999, "games")


def test_same_deal_from_two_channels_alerts_once(session, user):
    only_interest(session, user, categories=["games"])
    ingest_deals(session, [deal()], baseline=False)
    ingest_deals(session, [deal(source="tg:b")], baseline=False)
    ingest_deals(session, [deal()], baseline=False)
    assert len(notes(session)) == 1
    assert len(session.scalars(select(Deal)).all()) == 2


def test_interest_filters_and_hourly_limit(session, user):
    only_interest(session, user, keywords=["rtx"], max_price=3000, max_per_hour=2)
    items = [deal("a", "Placa RTX 5070 por R$ 3.500"), deal("b", "Notebook por R$ 2.000")]
    items += [deal(f"c{i}", f"Placa RTX {5000 + i} modelo {i} por R$ {2000 + i * 100}")
              for i in range(4)]
    ingest_deals(session, items, baseline=False)
    assert len(notes(session)) == 2


def test_watch_receives_matching_deal_but_not_accessory(session, user):
    session.execute(delete(Interest))
    watch = Watch(user_id=user.id, name="PS5", query="ps5", target_price=4000)
    session.add(watch)
    session.flush()
    session.add(Offer(watch_id=watch.id, source="x", external_id="1", store="KaBuM!",
                      store_key="kabum", title="PS5", url="https://x.example", price=4500,
                      lowest_price=4500))
    session.commit()
    ingest_deals(session, [
        deal("1"),
        deal("2", "Controle PS5 DualSense por R$ 399"),
        deal("3", "PS5 faceplate por R$ 99"),
    ], baseline=False)
    [note] = notes(session)
    assert note.priority == 3 and note.path == f"/monitorados/{watch.id}"


def test_flash_coupon_alerts_interest_and_watch(session, user):
    only_interest(session, user, stores=["mercadolivre"], only_coupons=True)
    watch = Watch(user_id=user.id, name="PS5", query="ps5")
    session.add(watch)
    session.flush()
    session.add(Offer(watch_id=watch.id, source="x", external_id="1", store="Mercado Livre",
                      store_key="mercadolivre", title="Console PS5", url="https://x.example",
                      price=4500, lowest_price=4500))
    session.commit()
    coupon = FoundCoupon(source="promobit", store="Mercado Livre", title="R$ 100 OFF",
                         code="MELI100", discount="R$ 100", url="https://x.example/c")
    other = FoundCoupon(source="promobit", store="Shopee", title="R$ 10 OFF", code="SH10")
    expired = FoundCoupon(source="promobit", store="Mercado Livre", title="velho", code="OLD",
                          expires_at=utcnow() - timedelta(days=1))
    assert ingest_coupons(session, [coupon, other, expired], baseline=False)["new"] == 2
    got = notes(session)
    assert {n.kind.split(":")[0] for n in got} == {"interest"}, "mesmo cupom não avisa duas vezes"
    assert "MELI100" in got[0].body
    assert ingest_coupons(session, [coupon], baseline=False)["new"] == 0

    session.execute(delete(Interest))
    session.commit()
    ingest_coupons(session, [FoundCoupon(source="p", store="Mercado Livre", title="5% OFF",
                                         code="MELI5")], baseline=False)
    assert notes(session)[-1].kind == "coupon_possible"


def test_coupon_from_telegram_deal_is_listed(session, user):
    ingest_deals(session, [deal(title="Cupom relâmpago Mercado Livre: CORRE20",
                                description="Cupom: CORRE20")], baseline=True)
    coupon = session.scalar(select(Coupon))
    assert (coupon.store_key, coupon.code, coupon.is_flash) == ("mercadolivre", "CORRE20", True)


def test_cleanup(session, user):
    ingest_deals(session, [deal()], baseline=True)
    session.scalar(select(Deal)).first_seen_at = utcnow() - timedelta(days=40)
    session.commit()
    cleanup(session)
    assert session.scalar(select(Deal)) is None


class Feed(FeedSource):
    key, name = "tg:teste", "Teste"

    def __init__(self):
        self.items = [deal("1", source="tg:teste")]
        self.fail = False

    async def fetch(self, fetcher):
        if self.fail:
            raise ValueError("quebrou")
        return self.items, []


def test_worker_feed_cycle(session, user):
    only_interest(session, user, categories=["games"])
    source = Feed()

    async def go():
        worker = Worker(fetcher=object())
        await worker.run_one_feed(source)
        source.items = [deal("2", "Console PS5 Pro por R$ 6.500 na KaBuM", source="tg:teste")]
        await worker.run_one_feed(source)
        source.fail = True
        await worker.run_one_feed(source)

    asyncio.run(go())
    assert len(notes(session)) == 1, "primeira coleta só forma a base"
    status = session.get(SourceStatus, "tg:teste", populate_existing=True)
    assert status.state == "error" and status.baseline_done


def test_worker_schedules_due_work(session, user, monkeypatch):
    watch = Watch(user_id=user.id, name="PS5", query="ps5")
    session.add(watch)
    session.commit()
    ran = []

    async def go():
        worker = Worker(fetcher=object())

        async def fake_watch(watch_id):
            ran.append(watch_id)

        async def fake_feed(source):
            ran.append(source.key)

        monkeypatch.setattr(worker, "run_one_watch", fake_watch)
        monkeypatch.setattr(worker, "run_one_feed", fake_feed)
        worker.schedule()
        await asyncio.gather(*worker.tasks)

    asyncio.run(go())
    assert watch.id in ran and "tg:pelandobr" in ran and "rss:canaltech" in ran
