from sqlalchemy import select

from app.core.importer import Item, import_items, to_offer
from app.core.radar import cleanup
from app.models import Notification, Offer, Watch, utcnow

OLX = "https://sp.olx.com.br/grande-campinas/games/ps5-slim-usado-1556003399?lis=x"


def item(title="PS5 Slim 1TB seminovo", url=OLX, price=2800, **extra):
    return Item(title=title, url=url, price=price, **extra)


def watch(session, user, **extra):
    row = Watch(user_id=user.id, name="PS5", query="ps5", baseline_done=True, **extra)
    session.add(row)
    session.flush()
    session.add(Offer(watch_id=row.id, source="kabum", external_id="n", store="KaBuM!",
                      store_key="kabum", title="Console PS5", url="https://x.example",
                      price=4800, lowest_price=4800, variant_key="padrao"))
    session.commit()
    return row


def test_identifies_store_and_listing():
    offer = to_offer(item())
    assert (offer.source, offer.external_id, offer.condition) == ("olx", "1556003399", "used")
    ml = to_offer(item(url="https://produto.mercadolivre.com.br/MLB-4012345678-ps5-_JM",
                       title="PS5 lacrado"))
    assert (ml.source, ml.external_id, ml.condition) == ("mercadolivre", "MLB4012345678", "new")
    assert to_offer(item(title="PS5 com GTA<br>")).title == "PS5 com GTA"
    other = to_offer(item(url="https://www.magazineluiza.com.br/ps5/p/1/?x=2"))
    assert (other.source, other.store_key) == ("navegador", "magalu")


def test_import_alerts_used_opportunity_once(session, user):
    target = watch(session, user)
    accessory = item("Controle PS5", OLX.replace("1556003399", "1556003400"), 200)
    result = import_items(session, user, [item(), accessory])
    assert result["matched"] == 1 and result["watches"][0]["new"] == 1
    [note] = session.scalars(select(Notification)).all()
    assert note.kind == "used" and "2.800" in note.title and "4.800" in note.body
    again = import_items(session, user, [item()])
    assert again["watches"][0]["new"] == 0
    assert len(session.scalars(select(Notification)).all()) == 1
    reference = session.scalar(select(Offer).where(Offer.source == "kabum"))
    assert reference.available and reference.missed_runs == 0
    session.refresh(target)
    assert target.baseline_done


def test_import_marks_scam_prices_and_respects_region(session, user):
    watch(session, user, used_state="sp", used_region="Campinas")
    cheap = item(price=700)
    far = item(url="https://rj.olx.com.br/rio-de-janeiro-e-regiao/games/ps5-1556009999")
    assert import_items(session, user, [cheap, far])["matched"] == 1
    assert session.scalar(select(Offer).where(Offer.source == "olx")).suspicious
    assert session.scalars(select(Notification)).all() == []


def test_import_before_first_search_keeps_baseline_open(session, user):
    row = Watch(user_id=user.id, name="PS5", query="ps5")
    session.add(row)
    session.commit()
    import_items(session, user, [item()])
    session.refresh(row)
    assert not row.baseline_done and session.scalars(select(Notification)).all() == []


def test_stale_imports_expire(session, user):
    watch(session, user)
    import_items(session, user, [item()])
    offer = session.scalar(select(Offer).where(Offer.source == "olx"))
    offer.last_seen_at = utcnow().replace(year=2020)
    session.commit()
    cleanup(session)
    session.refresh(offer)
    assert not offer.available
