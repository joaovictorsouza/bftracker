"""Infraestrutura dos coletores: cliente HTTP educado, detecção de bloqueio e tipos.

O BFTracker se identifica no User-Agent, limita a frequência por domínio e, quando um
site recusa o acesso (403/429/CAPTCHA), apenas registra o bloqueio e espera. Ele não
tenta contornar proteções anti-robô.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx

from ..config import get_settings

USER_AGENT = "Mozilla/5.0 (compatible; BFTracker/1.0; personal price monitor)"
MAX_BYTES = 8 * 1024 * 1024

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_BLOCK_MARKERS = (
    "api-services-support@amazon.com",
    "/errors/validatecaptcha",
    "bm-verify",
    "triggerinterstitialchallenge",
    "/_sec/verify",
    "<title>just a moment",
    "suspicious-traffic-frontend",
    "account-verification",
    "não é possível acessar a página",
    "<title>acesso bloqueado",
    "<title>access denied",
    "cf-challenge",
)


class SourceError(Exception):
    """Falha ao coletar de uma fonte."""


class Blocked(SourceError):
    """O site recusou o acesso automatizado."""


class NotConfigured(SourceError):
    """A fonte precisa de configuração (ex.: credenciais)."""


@dataclass
class FoundOffer:
    source: str
    external_id: str
    store: str
    title: str
    url: str
    price: float
    store_key: str = ""
    seller: str = ""
    marketplace: bool = False
    image: str = ""
    card_price: float | None = None
    original_price: float | None = None
    installments: int | None = None
    installment_value: float | None = None
    interest_free: bool | None = None
    pix: bool = False
    free_shipping: bool | None = None
    coupon: str = ""
    condition: str = "new"
    location: str = ""
    # quando preenchido, o título do produto no comparador decide relevância e variante
    match_title: str = ""
    history: list[tuple[str, float]] = field(default_factory=list)  # (AAAA-MM-DD, preço)


@dataclass
class FoundDeal:
    source: str
    source_name: str
    external_id: str
    title: str
    url: str
    description: str = ""
    link: str = ""
    image: str = ""
    store: str = ""
    price: float | None = None
    old_price: float | None = None
    coupon: str = ""
    category: str = ""
    published_at: datetime | None = None
    is_flash: bool = False
    is_coupon: bool = False


@dataclass
class FoundCoupon:
    source: str
    store: str
    title: str
    code: str = ""
    discount: str = ""
    conditions: str = ""
    url: str = ""
    expires_at: datetime | None = None
    is_flash: bool = False


@dataclass
class SearchParams:
    query: str
    include_used: bool = False
    used_state: str = ""
    used_region: str = ""
    min_price: float | None = None
    max_price: float | None = None
    # filtro de relevância fornecido pelo motor (evita abrir páginas de itens irrelevantes)
    is_relevant: object = None

    def relevant(self, title: str) -> bool:
        if callable(self.is_relevant):
            return bool(self.is_relevant(title))
        return True


def assert_public_url(url: str) -> None:
    """Impede que URLs informadas pelo usuário alcancem a rede interna (SSRF)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceError("URL inválida: use um endereço http(s) público")
    if parsed.port not in (None, 80, 443):
        raise SourceError("Porta não permitida")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise SourceError(f"Domínio não encontrado: {parsed.hostname}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise SourceError("Endereços de rede interna não são permitidos")


class Fetcher:
    """Cliente HTTP compartilhado com intervalo mínimo por domínio."""

    def __init__(self, min_delay: float | None = None, transport=None):
        self.min_delay = (
            get_settings().host_min_delay_seconds if min_delay is None else min_delay
        )
        self.client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=False,
            transport=transport,
            http2=transport is None,
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def close(self) -> None:
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def _wait_turn(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0) + self.min_delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def request(
        self, method: str, url: str, *, guard: bool = False, **kwargs
    ) -> httpx.Response:
        for _hop in range(6):
            if guard:
                await asyncio.to_thread(assert_public_url, url)
            host = urlparse(url).hostname or ""
            await self._wait_turn(host)
            try:
                async with self.client.stream(method, url, **kwargs) as response:
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise SourceError("Resposta grande demais")
                        chunks.append(chunk)
                    response._content = b"".join(chunks)
            except httpx.HTTPError as exc:
                raise SourceError(f"Falha de rede em {host}: {type(exc).__name__}") from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise SourceError(f"Redirecionamento sem destino em {host}")
                url = urljoin(url, location)
                if response.status_code == 303:
                    method = "GET"
                kwargs.pop("params", None)
                continue
            self._check(response, host)
            return response
        raise SourceError("Redirecionamentos demais")

    @staticmethod
    def _check(response: httpx.Response, host: str) -> None:
        status = response.status_code
        if status in (401, 403, 429):
            raise Blocked(f"{host} recusou o acesso (HTTP {status})")
        if len(response.content) < 120_000:
            sample = response.text[:60_000].lower()
            if any(marker in sample for marker in _BLOCK_MARKERS):
                raise Blocked(f"{host} exigiu verificação anti-robô")
        if status == 503 and "amazon" in host:
            raise Blocked(f"{host} limitou as requisições (HTTP 503)")
        if status >= 400:
            raise SourceError(f"{host} respondeu HTTP {status}")

    async def get_text(self, url: str, **kwargs) -> str:
        response = await self.request("GET", url, **kwargs)
        return response.text

    async def get_json(self, url: str, **kwargs):
        response = await self.request("GET", url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"{urlparse(url).hostname} não devolveu JSON") from exc


class StoreSource:
    """Fonte pesquisável por produto."""

    key: str = ""
    name: str = ""
    covers: str = ""
    used_only: bool = False

    async def search(self, fetcher: Fetcher, params: SearchParams) -> list[FoundOffer]:
        raise NotImplementedError


class FeedSource:
    """Fonte de ofertas/cupons publicada continuamente (sites, fóruns, canais)."""

    key: str = ""
    name: str = ""
    interval_seconds: int = 300

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        raise NotImplementedError
