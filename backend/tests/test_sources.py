"""Coletores testados com amostras sintéticas que reproduzem o formato real das páginas."""

import asyncio
import json

import httpx
import pytest

from app.sources.amazon import Amazon
from app.sources.base import Blocked, Fetcher, SearchParams, SourceError, assert_public_url
from app.sources.comparators import Zoom
from app.sources.feeds import Hardmob, Promobit, RssFeed, TelegramChannel
from app.sources.generic import parse_product_page
from app.sources.kabum import Kabum
from app.sources.mercadolivre import MercadoLivre
from app.sources.olx import Olx
from app.sources.vtex import Vtex

ALL = SearchParams(query="ps5", include_used=True)


def next_page(data: dict) -> str:
    return (f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}'
            "</script></html>")


def test_kabum_pix_installments_and_flash_offer():
    attr = {
        "title": "Console PS5 Slim", "available": True, "price": 5000.0,
        "price_with_discount": 4750.0, "old_price": 6000.0,
        "max_installment": "10x de R$ 500,00", "product_link": "console-ps5",
        "offer": {"name": "OFERTAS", "starts_at": 10, "ends_at": 30,
                  "price": 4600, "price_with_discount": 4400},
    }
    data = {"data": [{"id": 7, "attributes": attr},
                     {"id": 8, "attributes": attr | {"available": False}}]}
    [offer] = Kabum().parse(data, ALL, now=20)
    assert (offer.price, offer.card_price, offer.installments) == (4400, 4600, 10)
    assert offer.coupon.startswith("Oferta relâmpago") and offer.url.endswith("/7/console-ps5")
    assert Kabum().parse(data, ALL, now=40)[0].price == 4750


def test_vtex_prefers_pix_and_max_interest_free():
    installments = [
        {"PaymentSystemName": "Pix", "NumberOfInstallments": 1, "InterestRate": 0,
         "Value": 900, "TotalValuePlusInterestRate": 900},
        {"PaymentSystemName": "Visa", "NumberOfInstallments": 10, "InterestRate": 0,
         "Value": 100, "TotalValuePlusInterestRate": 1000},
        {"PaymentSystemName": "Visa", "NumberOfInstallments": 12, "InterestRate": 2.9,
         "Value": 95, "TotalValuePlusInterestRate": 1140},
    ]
    data = [{
        "productName": "PS5", "link": "https://loja.example/ps5/p",
        "items": [{"itemId": "1", "nameComplete": "Console PS5", "images": [], "sellers": [
            {"sellerId": "1", "sellerName": "Loja", "commertialOffer": {
                "Price": 1000, "ListPrice": 1200, "AvailableQuantity": 3,
                "Installments": installments}},
            {"sellerId": "9", "sellerName": "Sem estoque", "commertialOffer": {
                "Price": 10, "AvailableQuantity": 0}},
        ]}],
    }]
    [offer] = Vtex("americanas", "Americanas", "https://www.americanas.com.br").parse(data, ALL)
    assert offer.price == 900 and offer.pix and offer.card_price == 1000
    assert (offer.installments, offer.installment_value, offer.interest_free) == (10, 100, True)
    assert offer.store_key == "americanas" and not offer.marketplace


def olx_card(ad_id, region, location, price="R$ 3.500", title="PS5 Slim usado"):
    return f"""<section class="olx-adcard olx-adcard__horizontal">
      <a data-testid="adcard-link" class="olx-adcard__link" title="{title}"
         href="https://sp.olx.com.br/{region}/games/ps5-{ad_id}"><h2>{title}</h2></a>
      <h3 class="olx-adcard__price">{price}</h3>
      <div data-testid="adcard-price-info">em até <span>10x de R$ 350,00</span></div>
      <p class="olx-adcard__location">{location}</p></section>"""


def test_olx_parses_and_filters_region():
    page = "<html>olx" + olx_card(111111111, "grande-campinas", "Campinas, Centro") + olx_card(
        222222222, "sao-paulo-e-regiao", "São Paulo, Mooca") + "</html>"
    everything = Olx().parse(page, SearchParams(query="ps5", used_state="sp"))
    assert [o.external_id for o in everything] == ["111111111", "222222222"]
    only = Olx().parse(page, SearchParams(query="ps5", used_state="sp", used_region="Campinas"))
    assert [o.external_id for o in only] == ["111111111"]
    assert only[0].condition == "used" and only[0].price == 3500 and only[0].installments == 10
    urls = Olx().urls(SearchParams(query="ps5 pro", used_state="rj", max_price=3000))
    assert urls[0] == "https://www.olx.com.br/estado-rj?q=ps5+pro&sf=1&pe=3000"


def test_amazon_card_with_coupon():
    page = """<div data-component-type="s-search-result" data-asin="B0ABC">
      <h2><span>Console PlayStation 5 Slim</span></h2>
      <span class="a-price"><span class="a-offscreen">R$&nbsp;4.699,90</span></span>
      <span class="a-price" data-a-strike="true"><span class="a-offscreen">R$ 5.499,00</span></span>
      <span>em até 10x de R$ 469,99 sem juros</span> <span>Frete GRÁTIS</span>
      <span>Economize R$ 200,00 com cupom</span></div>"""
    [offer] = Amazon().parse(page, ALL)
    assert offer.price == 4699.90 and offer.original_price == 5499
    assert offer.installments == 10 and offer.interest_free
    assert "cupom" in offer.coupon.lower() and offer.url.endswith("/dp/B0ABC")


def test_comparator_search_and_product_page():
    search = next_page({"props": {"initialReduxState": {"hits": {"hits": [
        {"type": "product", "name": "PlayStation 5 Slim 1TB", "price": 4700, "sourceId": "55",
         "objectId": "product55", "url": "/console/ps5"},
        {"type": "product", "name": "Controle para PS5", "price": 300, "url": "/c"},
    ]}}}})
    product = next_page({"props": {"initialReduxState": {
        "offers": {"offerList": [
            {"id": "1", "name": "PS5 Slim", "price": 4700, "sellerName": "Magazine Luiza",
             "numParcels": 10, "parcelValue": 470, "totalParceledValue": 4700},
            {"id": "2", "name": "PS5 Slim", "price": 4600, "sellerName": "Casas Bahia",
             "numParcels": 10, "parcelValue": 500, "totalParceledValue": 5000},
        ]},
        "priceHistory": {"priceHistory": {"55": {"days": [
            {"date": "2026-10-01", "price": 4999}]}}},
    }}})

    def handler(request):
        return httpx.Response(200, text=search if request.url.path == "/search" else product)

    from app.core import matching

    criteria = matching.Criteria("ps5")
    params = SearchParams(query="ps5", is_relevant=lambda t: matching.matches(t, criteria))

    async def run():
        async with Fetcher(min_delay=0, transport=httpx.MockTransport(handler)) as fetcher:
            return await Zoom().search(fetcher, params)

    offers = asyncio.run(run())
    by_store = {o.store_key: o for o in offers}
    assert set(by_store) == {"magalu", "casasbahia"}
    assert by_store["magalu"].interest_free is True
    assert by_store["casasbahia"].interest_free is None
    assert offers[0].history == [("2026-10-01", 4999.0)]


def test_mercadolivre_items_and_missing_credentials():
    product = {"id": "MLB1", "name": "PS5 Slim"}
    data = {"results": [
        {"item_id": "MLB10", "price": 4000, "condition": "new", "official_store_id": 3},
        {"item_id": "MLB11", "price": 2800, "condition": "used"},
    ]}
    ml = MercadoLivre()
    assert [o.condition for o in ml.parse_items(product, data, ALL)] == ["new", "used"]
    assert len(ml.parse_items(product, data, SearchParams(query="ps5"))) == 1
    with pytest.raises(SourceError):
        asyncio.run(MercadoLivre(lambda: "").search(None, ALL))


def test_mercadolivre_search_sends_bearer_token():
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        if request.url.path == "/products/search":
            return httpx.Response(200, json={"results": [{"id": "MLB1", "name": "PS5 Slim"}]})
        return httpx.Response(200, json={"results": [{"item_id": "1", "price": 4000}]})

    async def run():
        async with Fetcher(min_delay=0, transport=httpx.MockTransport(handler)) as fetcher:
            return await MercadoLivre(lambda: "abc").search(fetcher, ALL)

    assert asyncio.run(run())[0].price == 4000
    assert seen == ["Bearer abc", "Bearer abc"]


def test_mercadolivre_authorization_and_refresh_rotation():
    from urllib.parse import parse_qs

    from app.core.appsettings import set_value, stored
    from app.db import session_scope
    from app.sources import mlauth

    sent = []

    def handler(request):
        data = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        sent.append(data)
        number = len(sent)
        return httpx.Response(200, json={"access_token": f"acesso-{number}", "expires_in": 21600,
                                         "refresh_token": f"renova-{number}"})

    transport = httpx.MockTransport(handler)
    assert mlauth.access_token(transport) == ""
    with session_scope() as db:
        set_value(db, "ml_client_id", "123")
        set_value(db, "ml_client_secret", "segredo")
        mlauth.exchange_code(db, "TG-code", "https://x.example/cb", transport)
    assert sent[0]["grant_type"] == "authorization_code" and sent[0]["code"] == "TG-code"
    assert mlauth.access_token(transport) == "acesso-1" and len(sent) == 1, "usa o cache"
    with session_scope() as db:
        set_value(db, "ml_access_expires", "1")
    assert mlauth.access_token(transport) == "acesso-2"
    assert sent[1] == {"grant_type": "refresh_token", "client_id": "123",
                       "client_secret": "segredo", "refresh_token": "renova-1"}
    with session_scope() as db:
        assert stored(db, "ml_refresh_token") == "renova-2", "o novo refresh token é guardado"

    with session_scope() as db:
        set_value(db, "ml_access_expires", "1")
    denied = httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(mlauth.AuthError, match="invalid_grant"):
        mlauth.access_token(denied)


def test_generic_page_json_ld_and_meta():
    ld = {"@context": "https://schema.org", "@graph": [{
        "@type": "Product", "name": "Fone X", "image": ["https://img.example/x.jpg"],
        "offers": {"@type": "AggregateOffer", "offers": [
            {"price": "350.00", "availability": "https://schema.org/OutOfStock"},
            {"price": "399.90", "availability": "https://schema.org/InStock"}]}}]}
    page = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    offer = parse_product_page(page, "https://www.fastshop.com.br/p/fone")
    assert (offer.price, offer.title, offer.store_key) == (399.90, "Fone X", "fastshop")
    meta = ('<meta property="og:title" content="Mesa">'
            '<meta property="product:price:amount" content="199,90">')
    assert parse_product_page(meta, "https://loja.example/mesa").price == 199.90
    with pytest.raises(SourceError):
        parse_product_page("<html><body>nada</body></html>", "https://loja.example/x")


def test_telegram_messages():
    page = """<div class="tgme_widget_message" data-post="canal/10">
      <div class="tgme_widget_message_text js-message_text"><b>Console PS5 Slim na Amazon</b><br/>
      R$ 4.199 no Pix<br/>Cupom: <code>PS5OFF</code><br/>
      <a href="https://amzn.to/abc">comprar</a></div>
      <a class="tgme_widget_message_date" href="x"><time datetime="2026-11-25T12:00:00+00:00">
      </time></a></div>
      <div class="tgme_widget_message" data-post="canal/11">
      <div class="tgme_widget_message_text js-message_text">Bom dia, grupo!</div></div>"""
    [deal] = TelegramChannel("canal", "Canal").parse(page)
    assert deal.coupon == "PS5OFF" and deal.link == "https://amzn.to/abc"
    assert deal.url == "https://t.me/canal/10" and deal.published_at.hour == 12


def test_rss_keeps_only_deals():
    feed = b"""<rss version="2.0"><channel>
      <item><title>Echo Dot em oferta por R$ 299</title><link>https://s.example/1</link></item>
      <item><title>Nova atualizacao do Windows</title><link>https://s.example/2</link></item>
    </channel></rss>"""
    deals = RssFeed("x", "X", "https://s.example/feed").parse(feed)
    assert [d.url for d in deals] == ["https://s.example/1"]


def test_promobit_offers_and_coupons():
    page = next_page({"props": {"pageProps": {
        "serverOffers": {"offers": [{
            "offerId": 1, "offerTitle": "SSD 1TB", "offerPrice": 300, "offerOldPrice": 450,
            "storeName": "KaBuM!", "offerCoupon": "SSD10", "offerSlug": "ssd-1",
            "offerPhoto": "/a.jpg", "offerPublished": "2026-11-25T13:06:58-0300"}]},
        "couponsByStore": [{
            "couponId": 2, "couponTitle": "R$ 30 OFF", "storeName": "Amazon",
            "couponCode": "30OFF", "couponDiscount": "R$ 30 OFF", "couponUrl": "/Redirect/2",
            "couponUntil": "2026-11-30T23:59:00-0300"},
            {"couponId": 3, "couponTitle": "Sem código", "storeName": "Shopee",
             "couponCode": "Resgate no link"}],
    }}})
    deals, coupons = Promobit("k", "K", "/x/").parse(page)
    assert deals[0].price == 300 and deals[0].old_price == 450
    assert deals[0].published_at.utcoffset().total_seconds() == -10800
    assert [c.code for c in coupons] == ["30OFF", ""]
    assert coupons[0].url == "https://www.promobit.com.br/Redirect/2"


def test_hardmob_threads():
    page = """<ol><li class="threadbit"><div class="rating0 nonsticky">
      <div class="threadinfo" title="https://www.amazon.com.br/dp/1 texto"></div>
      <a class="title" href="threads/123-JBL?s=abcdef">Amazon - JBL Boombox - R$1.486,65</a>
      </div></li></ol>"""
    [deal] = Hardmob().parse(page)
    assert deal.url == "https://www.hardmob.com.br/threads/123-JBL" and deal.store == "Amazon"


@pytest.mark.parametrize(
    "response",
    [httpx.Response(403), httpx.Response(429),
     httpx.Response(200, text="<title>Just a moment...</title>")],
)
def test_blocks_are_reported_not_bypassed(response):
    async def run():
        transport = httpx.MockTransport(lambda r: response)
        async with Fetcher(min_delay=0, transport=transport) as fetcher:
            await fetcher.get_text("https://loja.example/")

    with pytest.raises(Blocked):
        asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://169.254.169.254/",
     "http://[::1]/", "file:///etc/passwd", "https://example.com:8443/", "ftp://example.com/"],
)
def test_ssrf_guard(url):
    with pytest.raises(SourceError):
        assert_public_url(url)


def test_ssrf_guard_applies_to_redirects(monkeypatch):
    import socket

    real = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == "publico.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    async def run():
        async with Fetcher(min_delay=0, transport=httpx.MockTransport(handler)) as fetcher:
            await fetcher.get_text("https://publico.example/", guard=True)

    with pytest.raises(SourceError, match="interna"):
        asyncio.run(run())
