"""Testes das integrações de Black Friday: X (Twitter), Gatry, Pelando, Busca Web (ML/OLX
sem API oficial), Alertas por E-mail (IMAP), ponte Radar→Monitorados e Extensão Companion."""

from __future__ import annotations

import asyncio
from email.message import EmailMessage
import io
import json
import zipfile

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import delete, select

from app.core import matching, stores
from app.core.appsettings import set_value
from app.core.radar import ingest_deals
from app.db import session_scope
from app.main import create_app
from app.models import (
    Coupon,
    DailyBest,
    Deal,
    Interest,
    Notification,
    Offer,
    SourceStatus,
    Watch,
    utcnow,
)
from app.sources.base import Blocked, Fetcher, FoundDeal, SearchParams
from app.sources.gatry import GatryFeed, GatrySearch
from app.sources.imap_alerts import parse_alert_email
from app.sources.pelando import PelandoCoupons, PelandoDeals
from app.sources.websearch import WebSearchStore
from app.sources.x_twitter import (
    XTwitterAccountsFeed,
    XTwitterWatchesFeed,
    build_product_batches,
    build_x_live_url,
    obtain_bearer_token,
    parse_x_rss,
)
from app.worker import Worker

from .conftest import PASSWORD

HEADERS = {"X-Requested-With": "bftracker"}


def test_unwrap_affiliate_and_short_store_domains():
    wrapped = (
        "https://www.awin1.com/cread.php?awinmid=17729&ued="
        "https%3A%2F%2Fwww.mercadolivre.com.br%2Fp%2FMLB12345"
    )
    assert stores.unwrap_url(wrapped) == "https://www.mercadolivre.com.br/p/MLB12345"
    assert stores.find_by_url(wrapped).key == "mercadolivre"
    assert stores.find_by_url("https://a.co/d/abc123").key == "amazon"
    assert stores.find_by_url("https://link.amazon/B03EYxw5F").key == "amazon"
    assert stores.find_in_text("Console PS5 Slim por R$ 3.199 no Meli").key == "mercadolivre"


def test_amazon_akamai_interstitial_is_classified_as_blocked():
    html = (
        "<html><head><meta http-equiv='refresh' content='5; URL=/s?k=ps5&bm-verify=AAA'></head>"
        "<body><script>function triggerInterstitialChallenge(){}</script></body></html>"
    )

    async def run():
        transport = httpx.MockTransport(lambda _r: httpx.Response(200, text=html))
        async with Fetcher(min_delay=0, transport=transport) as fetcher:
            await fetcher.get_text("https://www.amazon.com.br/s?k=ps5")

    with pytest.raises(Blocked):
        asyncio.run(run())


def test_gatry_search_and_feed_extract_offers_and_coupons():
    promo_payload = {
        "promotions": [
            {
                "id": "uuid-1",
                "kind": "promotion",
                "status": "active",
                "title": "Console PlayStation 5 Slim Digital 1TB",
                "slug": "console-ps5-slim-digital",
                "store_name": "Mercadolivre",
                "store_domain": "mercadolivre.com.br",
                "url": "https://www.awin1.com/cread.php?ued=https%3A%2F%2Fwww.mercadolivre.com.br%2Fp%2FMLB999",
                "price_cents": 319900,
                "old_price_cents": 379900,
                "free_shipping": True,
                "image_keys": ["promotions/uuid-1/foto.jpg"],
                "last_comment_body": "Use o cupom GANHA100 no pagamento",
                "approved_at": "2026-11-26T22:00:00Z",
            },
            {
                "id": "uuid-2",
                "kind": "promotion",
                "status": "inactive",
                "title": "Console PlayStation 5 Antigo",
                "price_cents": 299900,
            },
        ]
    }
    coupon_payload = {
        "promotions": [
            {
                "id": "uuid-c1",
                "kind": "coupon",
                "status": "active",
                "title": "Mercado Livre | R$ 200 OFF em R$ 1.500",
                "slug": "ml-200-off",
                "store_name": "Mercadolivre",
                "url": "https://www.mercadolivre.com.br/cupons",
                "code": "BLACK200",
                "discount_text": "R$ 200 OFF",
                "created_at": "2026-11-26T22:05:00Z",
            }
        ]
    }
    criteria = matching.Criteria("ps5")
    params = SearchParams(query="ps5", is_relevant=lambda t: matching.matches(t, criteria))
    [offer] = GatrySearch().parse(promo_payload, params)
    assert offer.store_key == "mercadolivre"
    assert offer.price == 3199.0 and offer.original_price == 3799.0
    assert offer.coupon == "GANHA100" and offer.free_shipping is True
    assert offer.url == "https://www.mercadolivre.com.br/p/MLB999"
    assert offer.image.endswith("/promotions/uuid-1/foto.jpg")

    deals, coupons = GatryFeed().parse(promo_payload, coupon_payload)
    assert len(deals) == 2 and len(coupons) == 2
    by_code = {c.code: c for c in coupons}
    assert "BLACK200" in by_code and "GANHA100" in by_code


def test_pelando_deals_and_mercadolivre_coupons():
    deals_html = """<html><body>pelando
      <div class="_deal-card_1jdb6_25">
        <a href="https://www.pelando.com.br/d/ps5-slim-1tb-9999">
          <img srcset="https://media.pelando.com.br/100.jpg 100w, https://media.pelando.com.br/300.jpg 300w" src="https://media.pelando.com.br/100.jpg">
        </a>
        <h3><a href="https://www.pelando.com.br/d/ps5-slim-1tb-9999" data-deal-id="pel-1" data-inactive="false">Console PS5 Slim 1TB</a></h3>
        <div class="_default-deal-card-store_8rdza_84"><span>| Vendido por </span><a href="/cupons-de-descontos/mercado-livre">Mercado Livre</a></div>
        <span class="_deal-card-stamp_15l5n_25"><small>R$</small>3.299</span>
      </div>
      <div class="_deal-card_1jdb6_25">
        <h3><a href="https://www.pelando.com.br/d/expirada" data-deal-id="pel-2" data-inactive="true">Oferta encerrada</a></h3>
      </div>
    </body></html>"""
    [deal] = PelandoDeals("recentes", "Pelando · recentes", "/recentes").parse(deals_html)
    assert (deal.external_id, deal.store, deal.price) == ("pel-1", "Mercado Livre", 3299.0)
    assert deal.image == "https://media.pelando.com.br/300.jpg"

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Offer",
                "@id": "https://www.pelando.com.br/cupons-de-descontos/mercado-livre#offer-1",
                "name": "[Resgate 21h] Cupom Mercado Livre 25% OFF com código MELI25",
                "url": "/d/resgate-21h-cupom-ml",
                "availability": "https://schema.org/InStock",
                "description": "Use o cupom MELI25 em compras acima de R$ 200",
            },
            {
                "@type": "Offer",
                "@id": "https://www.pelando.com.br/cupons-de-descontos/mercado-livre#offer-2",
                "name": "Cupom esgotado",
                "availability": "https://schema.org/OutOfStock",
            },
        ],
    }
    coupons_html = f'<html>pelando<script type="application/ld+json">{json.dumps(ld)}</script></html>'
    flash_deals, coupons = PelandoCoupons(
        "mercadolivre", "Pelando · Cupons ML", "/cupons-de-descontos/mercado-livre"
    ).parse(coupons_html)
    assert len(coupons) == 1 and coupons[0].code == "MELI25" and coupons[0].is_flash
    assert len(flash_deals) == 1 and flash_deals[0].store == "Mercado Livre"


def test_x_twitter_watches_oauth_since_id_and_bridge_to_watch(session, user):
    session.execute(delete(Interest))
    w1 = Watch(user_id=user.id, name="PS5", query="ps5 slim", target_price=3300)
    w2 = Watch(user_id=user.id, name="RTX 5070", query="rtx 5070")
    session.add_all([w1, w2])
    set_value(session, "x_api_key", "key1")
    set_value(session, "x_api_secret", "sec1")
    set_value(session, "x_accounts", "pelandobr, promobitoficial")
    session.commit()

    batches = build_product_batches(["ps5 slim", "rtx 5070"])
    assert len(batches) == 1 and '("ps5" "slim")' in batches[0] and len(batches[0]) <= 512
    assert "f=live" in build_x_live_url(["ps5 slim", "rtx 5070"])

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "x-token-123"})
        since = request.url.params.get("since_id")
        if since == "1999999999":
            return httpx.Response(200, json={"data": [], "meta": {"result_count": 0}})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "1999999999",
                        "author_id": "u1",
                        "created_at": utcnow().isoformat().replace("+00:00", "Z"),
                        "text": "🔥 CORRE! Console Sony PS5 Slim 1TB por R$ 3.199 no Pix!\nCupom: XBLACK10\nhttps://t.co/shortml",
                        "attachments": {"media_keys": ["m1"]},
                        "entities": {
                            "urls": [
                                {
                                    "url": "https://t.co/shortml",
                                    "unwound_url": "https://www.mercadolivre.com.br/p/MLB777",
                                }
                            ]
                        },
                    },
                    {
                        "id": "1999999998",
                        "author_id": "u1",
                        "text": "Bom dia pessoal, prontos para amanhã?",
                    },
                ],
                "includes": {
                    "users": [{"id": "u1", "username": "nerdofertas", "name": "Nerd Ofertas"}],
                    "media": [{"media_key": "m1", "url": "https://pbs.twimg.com/media/ps5.jpg"}],
                },
                "meta": {"newest_id": "1999999999", "result_count": 2},
            },
        )

    async def go():
        async with Fetcher(min_delay=0, transport=httpx.MockTransport(handler)) as fetcher:
            with session_scope() as db:
                tok = await obtain_bearer_token(fetcher, db)
                assert tok == "x-token-123"
            first_deals, _ = await XTwitterWatchesFeed().fetch(fetcher)
            second_deals, _ = await XTwitterWatchesFeed().fetch(fetcher)
            acc_deals, _ = await XTwitterAccountsFeed().fetch(fetcher)
            return first_deals, second_deals, acc_deals

    first_deals, second_deals, acc_deals = asyncio.run(go())
    assert len(first_deals) == 1 and second_deals == []
    assert len(acc_deals) == 1
    search_calls = [c for c in calls if c.url.path == "/2/tweets/search/recent"]
    assert "since_id" not in search_calls[0].url.params
    assert search_calls[1].url.params.get("since_id") == "1999999999"

    d = first_deals[0]
    assert d.source == "x_twitter" and d.source_name == "X · @nerdofertas"
    assert d.store == "Mercado Livre" and d.price == 3199.0 and d.coupon == "XBLACK10"
    assert d.image == "https://pbs.twimg.com/media/ps5.jpg"

    # Ao ingerir a oferta do X no radar, ela também entra como Offer no Watch do PS5 e avisa!
    res = ingest_deals(session, first_deals, baseline=False)
    assert res == {"new": 1, "alerts": 1}
    watch_offers = session.scalars(select(Offer).where(Offer.watch_id == w1.id)).all()
    assert len(watch_offers) == 1
    assert watch_offers[0].store_key == "mercadolivre" and watch_offers[0].price == 3199.0
    assert watch_offers[0].coupon == "XBLACK10"
    assert session.scalar(select(Coupon).where(Coupon.code == "XBLACK10")) is not None
    note = session.scalar(select(Notification).where(Notification.watch_id == w1.id))
    assert note is not None and note.priority == 3


def test_x_rss_bridge_parses_tweets():
    rss = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>X Search</title>
      <item>
        <title>RTX 5070 Asus Dual por R$ 3.899 na KaBuM! Use cupom GPU10</title>
        <link>https://x.com/ofertas/status/1888888888</link>
        <description><![CDATA[<p>RTX 5070 por R$ 3.899 <a href="https://www.kabum.com.br/produto/99">link</a></p>]]></description>
      </item>
    </channel></rss>"""
    [deal] = parse_x_rss(rss, "X · RTX 5070")
    assert deal.external_id == "1888888888"
    assert deal.store == "KaBuM!" and deal.price == 3899.0 and deal.coupon == "GPU10"
    assert deal.link == "https://www.kabum.com.br/produto/99"


def test_websearch_serper_covers_mercadolivre_and_olx(session):
    set_value(session, "serper_api_key", "serper-test-key")
    session.commit()

    def handler(request: httpx.Request):
        assert request.headers.get("x-api-key") == "serper-test-key"
        if request.url.path == "/shopping":
            return httpx.Response(
                200,
                json={
                    "shopping": [
                        {
                            "title": "Console PlayStation 5 Slim 1TB Branco",
                            "source": "Mercado Livre",
                            "link": "https://www.mercadolivre.com.br/p/MLB555555",
                            "price": "R$ 3.449,00",
                            "delivery": "Frete grátis",
                            "imageUrl": "https://http2.mlstatic.com/ps5.jpg",
                        },
                        {
                            "title": "Capa Silicone Controle PS5",
                            "source": "Shopee",
                            "link": "https://shopee.com.br/capa",
                            "price": "R$ 19,90",
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "PS5 Slim 1TB seminovo na caixa - OLX",
                        "link": "https://sp.olx.com.br/grande-campinas/games/ps5-slim-1444555666",
                        "snippet": "Vendo PS5 Slim impecável em Campinas por R$ 2.650,00.",
                    }
                ]
            },
        )

    criteria = matching.Criteria("ps5")
    params = SearchParams(
        query="ps5",
        include_used=True,
        used_state="sp",
        used_region="Campinas",
        is_relevant=lambda t: matching.matches(t, criteria),
    )

    async def go():
        async with Fetcher(min_delay=0, transport=httpx.MockTransport(handler)) as fetcher:
            return await WebSearchStore().search(fetcher, params)

    offers = asyncio.run(go())
    by_store = {o.store_key: o for o in offers}
    assert set(by_store) == {"mercadolivre", "olx"}
    assert by_store["mercadolivre"].price == 3449.0 and by_store["mercadolivre"].free_shipping
    assert by_store["olx"].price == 2650.0 and by_store["olx"].condition == "used"


def test_imap_alert_email_parsers_olx_hardmob_and_google_alerts():
    # 1) Busca salva da OLX com dois anúncios
    olx_msg = EmailMessage()
    olx_msg["From"] = "OLX <alertas@olx.com.br>"
    olx_msg["Subject"] = "Novos anúncios para sua busca: PS5"
    olx_msg["Message-ID"] = "<olx-1@olx.com.br>"
    olx_msg.set_content("Veja no app")
    olx_msg.add_alternative(
        """<html><body>
        <div><a href="https://sp.olx.com.br/grande-campinas/games/ps5-slim-1999888777">PS5 Slim 1TB Seminovo</a> <span>R$ 2.700</span></div>
        <div><a href="https://sp.olx.com.br/sao-paulo-e-regiao/games/ps5-pro-1999888778">Console PS5 Pro 2TB</a> <span>R$ 5.200</span></div>
        <a href="https://www.olx.com.br/unsubscribe">Descadastrar</a>
        </body></html>""",
        subtype="html",
    )
    olx_deals = parse_alert_email(olx_msg.as_bytes())
    assert [(d.external_id, d.price, d.store) for d in olx_deals] == [
        ("1999888777", 2700.0, "OLX"),
        ("1999888778", 5200.0, "OLX"),
    ]

    # 2) Notificação instantânea do fórum hardMOB Promoções
    hm_msg = EmailMessage()
    hm_msg["From"] = "hardMOB Forum <forum@hardmob.com.br>"
    hm_msg["Subject"] = "[hardMOB] Novo tópico: [Mercado Livre] PS5 Slim 1TB - R$ 3.099 c/ cupom GANHA200"
    hm_msg["Message-ID"] = "<hm-407-1@hardmob.com.br>"
    hm_msg.set_content(
        "Novo tópico em Promoções:\n"
        "https://www.hardmob.com.br/threads/999111-Mercado-Livre-PS5-Slim\n"
        "Link direto: https://www.mercadolivre.com.br/p/MLB321\n"
        "Preço: R$ 3.099 usando cupom GANHA200"
    )
    [hm_deal] = parse_alert_email(hm_msg.as_bytes())
    assert hm_deal.source == "imap:hardmob"
    assert hm_deal.store == "Mercado Livre" and hm_deal.price == 3099.0
    assert hm_deal.coupon == "GANHA200"
    assert hm_deal.link == "https://www.mercadolivre.com.br/p/MLB321"

    # 3) E-mail pessoal comum é ignorado
    personal = EmailMessage()
    personal["From"] = "colega@empresa.com.br"
    personal["Subject"] = "Reunião R$ 500"
    personal.set_content("https://empresa.com.br/doc")
    assert parse_alert_email(personal.as_bytes()) == []


def test_backfill_watch_from_existing_radar_deals_and_extension_api():
    with TestClient(create_app(), headers=HEADERS) as client:
        client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})

        # Cria chave pessoal para a extensão do navegador
        tok_resp = client.post("/api/tokens", json={"name": "Meu Chrome"})
        assert tok_resp.status_code == 201
        raw_token = tok_resp.json()["token"]
        tok_id = tok_resp.json()["id"]
        assert raw_token.startswith("bft_")
        assert len(client.get("/api/tokens").json()) == 1

        # Baixa o pacote ZIP da extensão e valida conteúdo
        zip_resp = client.get("/api/extension.zip")
        assert zip_resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            names = set(zf.namelist())
            assert "bftracker-companion/manifest.json" in names
            assert "bftracker-companion/background.js" in names
            assert "bftracker-companion/content.js" in names
            assert "bftracker-companion/default-config.json" in names

        # Usa a extensão apenas com Bearer token (sem cookie de sessão!)
        with TestClient(client.app, headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Requested-With": "bftracker",
        }) as ext_client:
            # Envia primeiro uma oferta do X e um tópico do hardMOB antes mesmo de criar o Watch
            ingest_1 = ext_client.post(
                "/api/import",
                json={
                    "items": [],
                    "deals": [
                        {
                            "source": "x_twitter",
                            "source_name": "X · @pelandobr",
                            "external_id": "tw-777",
                            "title": "Console PS5 Slim 1TB por R$ 3.250 no Mercado Livre",
                            "url": "https://x.com/pelandobr/status/777",
                            "link": "https://www.mercadolivre.com.br/p/MLB888",
                            "price": 3250,
                            "coupon": "MELIBF",
                        },
                        {
                            "source": "hardmob",
                            "source_name": "hardMOB Promoções",
                            "external_id": "hm-555",
                            "title": "[KaBuM] SSD NVMe 2TB Kingston - R$ 699",
                            "url": "https://www.hardmob.com.br/threads/555-SSD",
                            "link": "https://www.kabum.com.br/produto/555",
                            "price": 699,
                        },
                    ],
                },
            )
            assert ingest_1.status_code == 200
            assert ingest_1.json()["deals_new"] == 2

            # Agora cadastra o Watch "PS5": o backfill imediato já traz a oferta do Mercado Livre!
            created = client.post("/api/watches", json={"query": "PS5", "used_state": "SP"})
            assert created.status_code == 201
            watch = created.json()
            assert watch["offers"] == 1
            assert watch["best"]["store_key"] == "mercadolivre"
            assert watch["best"]["price"] == 3250

            # Ping da extensão lista o Watch com os atalhos diretos (ML, OLX, X, hardMOB)
            ping = ext_client.get("/api/ext/ping")
            assert ping.status_code == 200
            pdata = ping.json()
            assert pdata["watches_count"] == 1
            links = pdata["watches"][0]["links"]
            assert "mercadolivre.com.br" in links["ml_new"]
            assert "olx.com.br/estado-sp" in links["olx"]
            assert "x.com/search" in links["x_live"]

            # Envia anúncio enriquecido do Mercado Livre (parcelamento + frete grátis)
            ingest_2 = ext_client.post(
                "/api/import",
                json={
                    "items": [
                        {
                            "title": "Console Sony PlayStation 5 Slim 1TB",
                            "url": "https://produto.mercadolivre.com.br/MLB-5001234567-ps5-_JM",
                            "price": 3180,
                            "original_price": 3999,
                            "installments": 12,
                            "installment_value": 265,
                            "interest_free": True,
                            "free_shipping": True,
                            "coupon": "R$ 100 OFF no cupom",
                            "seller": "PlayStation Loja Oficial",
                        }
                    ]
                },
            )
            assert ingest_2.status_code == 200 and ingest_2.json()["matched"] == 1

            # Filtro por origem no Radar (X e Portais)
            x_deals = client.get("/api/deals?origin=x").json()["items"]
            hm_deals = client.get("/api/deals?origin=portals").json()["items"]
            assert len(x_deals) == 1 and "PS5" in x_deals[0]["title"]
            assert any("SSD" in d["title"] for d in hm_deals)

            # Revoga a chave: a extensão perde o acesso imediatamente
            assert client.delete(f"/api/tokens/{tok_id}").status_code == 200
            assert ext_client.get("/api/ext/ping").status_code == 401


def test_worker_marks_unconfigured_feed_without_backoff(session, user):
    async def go():
        worker = Worker(fetcher=Fetcher(min_delay=0))
        try:
            await worker.run_one_feed(XTwitterWatchesFeed())
        finally:
            await worker.fetcher.close()

    asyncio.run(go())
    status = session.get(SourceStatus, "x:watches", populate_existing=True)
    assert status is not None
    assert status.state == "unconfigured" and status.blocked_until is None


def test_cloudflare_and_dokploy_proxy_headers_enable_https_cookies_and_sw_headers(
    tmp_path, monkeypatch
):
    from app import config

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>app</html>")
    (web / "sw.js").write_text("self.addEventListener('push', () => {});")
    (web / "manifest.webmanifest").write_text('{"name":"BFTracker"}')
    monkeypatch.setenv("WEB_DIST", str(web))
    config.get_settings.cache_clear()

    # Simula chegada HTTP interna do Traefik do Dokploy com cabeçalhos da Cloudflare
    cf_headers = {
        **HEADERS,
        "Host": "ofertas.seudominio.com",
        "CF-Visitor": '{"scheme":"https"}',
        "CF-Connecting-IP": "177.10.20.30",
    }
    with TestClient(create_app(), base_url="http://app:8000", headers=cf_headers) as client:
        resp = client.post("/api/auth/login", json={"username": "admin", "password": PASSWORD})
        assert resp.status_code == 200
        assert "secure" in resp.headers["set-cookie"].lower()
        assert "strict-transport-security" in resp.headers
        assert resp.headers["cdn-cache-control"] == "no-store"

        sw = client.get("/sw.js")
        assert sw.status_code == 200
        assert sw.headers["cdn-cache-control"] == "no-store"
        assert "no-store" in sw.headers["cache-control"]
        assert sw.headers["service-worker-allowed"] == "/"

        manifest = client.get("/manifest.webmanifest")
        assert manifest.headers["cdn-cache-control"] == "no-store"

        # O navegador está em HTTPS na ponta e reenvia o cookie Secure; o proxy repassa ao app:
        session_cookie = resp.headers["set-cookie"].split(";", 1)[0]
        ext_zip = client.get("/api/extension.zip", headers={"Cookie": session_cookie})
        assert ext_zip.status_code == 200
        with zipfile.ZipFile(io.BytesIO(ext_zip.content)) as zf:
            default_cfg = json.loads(zf.read("bftracker-companion/default-config.json"))
            assert default_cfg["serverUrl"] == "https://ofertas.seudominio.com"
