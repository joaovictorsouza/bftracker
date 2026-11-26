import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import PASSWORD

HEADERS = {"X-Requested-With": "bftracker"}


@pytest.fixture
def client():
    with TestClient(create_app(), headers=HEADERS) as c:
        yield c


def login(client, username="admin", password=PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


PROTECTED = [
    "/api/me", "/api/watches", "/api/deals", "/api/coupons", "/api/interests",
    "/api/notifications", "/api/dashboard", "/api/meta", "/api/push/key", "/api/events",
    "/api/admin/settings", "/api/admin/sources", "/api/admin/users", "/api/admin/whatsapp/qr",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_everything_requires_login(client, path):
    assert client.get(path).status_code == 401


def test_login_logout_and_cookie_flags(client):
    assert login(client, password="errada-123").status_code == 401
    response = login(client)
    assert response.status_code == 200 and response.json()["is_admin"]
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_secure_cookie_over_https():
    with TestClient(create_app(), base_url="https://testserver", headers=HEADERS) as client:
        response = login(client)
        assert "secure" in response.headers["set-cookie"].lower()
        assert "strict-transport-security" in response.headers


def test_forged_token_is_rejected(client):
    import jwt

    client.cookies.set("bft_session", jwt.encode({"sub": "1", "ver": 0}, "x" * 40))
    assert client.get("/api/me").status_code == 401


def test_brute_force_is_limited(client):
    for _ in range(8):
        assert login(client, password="errada-123").status_code == 401
    assert login(client).status_code == 429


def test_csrf_header_required(client):
    login(client)
    response = client.post("/api/auth/logout", headers={"X-Requested-With": ""})
    assert response.status_code == 403


def test_security_headers_and_no_docs(client):
    response = client.get("/api/health")
    assert response.json()["status"] == "ok"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert client.get("/api/openapi.json").status_code == 404
    assert client.get("/api/nao-existe").status_code == 404


def test_static_files_cannot_escape(tmp_path, monkeypatch):
    from app import config

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>app</html>")
    (tmp_path / "segredo.txt").write_text("nao pode")
    monkeypatch.setenv("WEB_DIST", str(web))
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        for path in ("/%2e%2e/segredo.txt", "/..%2fsegredo.txt", "/radar"):
            assert "nao pode" not in client.get(path).text
        assert "app" in client.get("/monitorados/3").text


def test_watch_lifecycle(client):
    login(client)
    created = client.post("/api/watches", json={"query": "PS5", "used_state": "SP"})
    assert created.status_code == 201
    watch = created.json()
    assert watch["name"] == "PS5" and watch["used_state"] == "sp"
    assert [w["id"] for w in client.get("/api/watches").json()] == [watch["id"]]
    detail = client.get(f"/api/watches/{watch['id']}").json()
    assert detail["offer_list"] == [] and detail["verdict"]["level"] == "none"
    body = {"query": "PS5 Pro", "target_price": 5000}
    assert client.put(f"/api/watches/{watch['id']}", json=body).json()["reset"] is True
    assert client.post(f"/api/watches/{watch['id']}/run").status_code == 200
    assert client.delete(f"/api/watches/{watch['id']}").status_code == 200
    assert client.get("/api/watches").json() == []


@pytest.mark.parametrize(
    "body",
    [{"query": ""}, {"kind": "url", "url": "javascript:alert(1)"},
     {"kind": "url", "url": "http://127.0.0.1/x"}, {"query": "ps5", "interval_minutes": 1},
     {"query": "ps5", "min_price": 10, "max_price": 5}],
)
def test_watch_validation(client, body):
    login(client)
    response = client.post("/api/watches", json=body)
    assert response.status_code == 422


def test_users_are_isolated(client):
    login(client)
    watch = client.post("/api/watches", json={"query": "PS5"}).json()
    interest = client.get("/api/interests").json()[0]
    made = client.post("/api/admin/users",
                       json={"username": "maria", "password": "outra-senha-123"})
    assert made.status_code == 201
    assert client.post("/api/admin/users",
                       json={"username": "MARIA", "password": "outra-senha-123"}
                       ).status_code == 409
    client.post("/api/auth/logout")
    login(client, "maria", "outra-senha-123")
    assert client.get("/api/watches").json() == []
    assert client.get(f"/api/watches/{watch['id']}").status_code == 404
    assert client.delete(f"/api/watches/{watch['id']}").status_code == 404
    assert client.delete(f"/api/interests/{interest['id']}").status_code == 404
    assert client.get("/api/admin/settings").status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    client.post("/api/auth/logout")
    login(client)
    assert client.delete(f"/api/admin/users/{made.json()['id']}").status_code == 200
    assert client.delete("/api/admin/users/1").status_code == 400


def test_password_change_ends_other_sessions(client):
    login(client)
    other = TestClient(client.app, headers=HEADERS)
    login(other)
    wrong = client.post("/api/me/password", json={"current": "nao", "new": "nova-senha-123"})
    assert wrong.status_code == 400
    done = client.post("/api/me/password", json={"current": PASSWORD, "new": "nova-senha-123"})
    assert done.status_code == 200
    assert client.get("/api/me").status_code == 200
    assert other.get("/api/me").status_code == 401


def test_profile_interests_push_and_settings(client, monkeypatch):
    import socket

    real = socket.getaddrinfo

    def fake(host, *args, **kwargs):
        if host == "push.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    login(client)
    profile = {"email": "p@example.com", "whatsapp": "11 98765-4321",
               "prefs": {"channels": {"push": True}, "quiet_start": "22:00",
                         "quiet_end": "07:00"}}
    assert client.put("/api/me", json=profile).json()["prefs"]["quiet_start"] == "22:00"
    assert client.put("/api/me", json=profile | {"email": "ruim"}).status_code == 422

    assert client.post("/api/interests", json={"name": "vazio"}).status_code == 422
    made = client.post("/api/interests", json={"name": "TVs", "categories": ["tvs"]})
    assert made.status_code == 201

    key = client.get("/api/push/key").json()["key"]
    assert len(key) > 80
    sub = {"endpoint": "https://push.example/1",
           "keys": {"p256dh": "B" * 87, "auth": "a" * 22}}
    assert client.post("/api/push/subscribe", json=sub).status_code == 200
    assert len(client.get("/api/push/key").json()["devices"]) == 1
    for bad in ("http://push.example/1", "https://127.0.0.1/x", "https://10.0.0.1/x"):
        assert client.post("/api/push/subscribe",
                           json=sub | {"endpoint": bad}).status_code == 422

    saved = client.put("/api/admin/settings", json={"values": {
        "smtp_host": "smtp.example.com", "smtp_password": "segredo"}}).json()
    assert saved["values"]["smtp_password"] == "" and saved["configured"]["smtp_password"]
    assert saved["values"]["smtp_host"] == "smtp.example.com"
    assert client.put("/api/admin/settings",
                      json={"values": {"secret_key": "x"}}).status_code == 422


def test_sources_admin(client):
    login(client)
    listing = client.get("/api/admin/sources").json()
    keys = {s["key"] for s in listing["sources"]}
    assert {"zoom", "amazon", "kabum", "olx", "mercadolivre", "tg:pelandobr",
            "rss:tudocelular", "promobit:mercadolivre"} <= keys
    assert client.put("/api/admin/sources/vtex:samsung/enabled",
                      json={"enabled": False}).status_code == 200
    assert client.post("/api/admin/sources/tg:pelandobr/run").status_code == 200
    added = client.post("/api/admin/custom-sources",
                        json={"kind": "telegram", "value": "https://t.me/meucanal"})
    assert added.json()["channel"] == "meucanal"
    internal = client.post("/api/admin/custom-sources",
                           json={"kind": "rss", "value": "http://192.168.0.1/feed"})
    assert internal.status_code == 422
    assert client.delete("/api/admin/custom-sources/telegram/tg:meucanal").status_code == 200
    assert client.get("/api/admin/sources").json()["custom"] == []


def test_deal_search_escapes_wildcards(client):
    login(client)
    from app.core.radar import ingest_deals
    from app.db import session_scope
    from app.sources.base import FoundDeal

    with session_scope() as db:
        ingest_deals(db, [FoundDeal(source="s", source_name="S", external_id="1",
                                    title="Notebook 50% off", url="https://x.example")],
                     baseline=True)
    assert len(client.get("/api/deals", params={"q": "50%"}).json()["items"]) == 1
    assert client.get("/api/deals", params={"q": "_zzz"}).json()["items"] == []
    assert client.get("/api/deals", params={"kind": "invalido"}).status_code == 422
