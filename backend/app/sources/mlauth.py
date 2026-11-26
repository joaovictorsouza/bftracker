"""Autorização do Mercado Livre (OAuth 2.0, fluxo authorization_code).

O token de acesso vale 6 horas. O refresh token é de uso único: a cada renovação chega um
novo, que precisa ser guardado imediatamente, senão a conexão se perde.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import httpx

from ..core.appsettings import get_value, set_value, stored
from ..db import session_scope

AUTH_URL = "https://auth.mercadolivre.com.br/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
CALLBACK_PATH = "/api/admin/ml/callback"


class AuthError(Exception):
    pass


def redirect_uri(public_url: str) -> str:
    return public_url.rstrip("/") + CALLBACK_PATH


def authorization_url(client_id: str, uri: str, state: str) -> str:
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": uri, "state": state}
    return f"{AUTH_URL}?{urlencode(query)}"


def _token_request(data: dict, transport=None) -> dict:
    try:
        with httpx.Client(timeout=25, transport=transport) as client:
            response = client.post(TOKEN_URL, data=data, headers={"Accept": "application/json"})
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthError(f"Mercado Livre inacessível: {type(exc).__name__}") from exc
    if response.status_code >= 400 or not body.get("access_token"):
        reason = body.get("error") or f"HTTP {response.status_code}"
        raise AuthError(f"Mercado Livre recusou a autorização ({reason})")
    return body


def _save(db, body: dict) -> str:
    set_value(db, "ml_access_cache", body["access_token"])
    expires = time.time() + int(body.get("expires_in", 21600)) - 300
    set_value(db, "ml_access_expires", str(int(expires)))
    if body.get("refresh_token"):
        set_value(db, "ml_refresh_token", body["refresh_token"])
    return body["access_token"]


def exchange_code(db, code: str, uri: str, transport=None) -> None:
    body = _token_request(
        {
            "grant_type": "authorization_code",
            "client_id": get_value(db, "ml_client_id"),
            "client_secret": get_value(db, "ml_client_secret"),
            "code": code,
            "redirect_uri": uri,
        },
        transport,
    )
    _save(db, body)


def access_token(transport=None) -> str:
    """Token válido, renovando quando preciso. Vazio se a conta não foi conectada."""
    with session_scope() as db:
        cached = stored(db, "ml_access_cache")
        if cached and float(stored(db, "ml_access_expires") or 0) > time.time():
            return cached
        refresh = stored(db, "ml_refresh_token")
        if not refresh:
            return get_value(db, "ml_access_token")  # token manual, opcional
        body = _token_request(
            {
                "grant_type": "refresh_token",
                "client_id": get_value(db, "ml_client_id"),
                "client_secret": get_value(db, "ml_client_secret"),
                "refresh_token": refresh,
            },
            transport,
        )
        return _save(db, body)


def disconnect(db) -> None:
    for key in ("ml_refresh_token", "ml_access_cache", "ml_access_expires"):
        set_value(db, key, "")
