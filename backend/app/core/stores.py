"""Cadastro de lojas conhecidas e nível de confiança.

Os dados de reputação são um retrato levantado em 25/11/2026 nas páginas públicas do
Reclame Aqui (quando há nota) e servem de orientação: confira o link antes de comprar.
Antes de comprar em lojas desconhecidas consulte a lista "Evite esses sites" do Procon-SP.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from .text import normalize, slug

CHECKED_AT = "2026-11-25"
PROCON_URL = "https://www.procon.sp.gov.br/"

TRUSTED = "alta"
GOOD = "boa"
CAUTION = "atencao"
UNKNOWN = "desconhecida"


@dataclass(frozen=True)
class Store:
    key: str
    name: str
    trust: str
    score: int
    domains: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    marketplace: bool = False
    note: str = ""
    reputation_url: str = ""

    def public(self) -> dict:
        return asdict(self)


_RA = "https://www.reclameaqui.com.br/empresa/"

STORES: tuple[Store, ...] = (
    Store("amazon", "Amazon", TRUSTED, 92, ("amazon.com.br", "amzn.to"), ("amazon br",), True,
          "Reputação Ótima (8,0) no Reclame Aqui. Em marketplace, confira o vendedor.",
          _RA + "amazon/"),
    Store("magalu", "Magazine Luiza", TRUSTED, 91,
          ("magazineluiza.com.br", "magazinevoce.com.br", "magalu.com", "mgl.io"),
          ("magalu", "magazine voce"), True,
          "Reputação Ótima (8,2) no Reclame Aqui.", _RA + "magazine-luiza-loja-online/"),
    Store("kabum", "KaBuM!", TRUSTED, 90, ("kabum.com.br",), ("kabum",), True,
          "Reputação Ótima (8,0) no Reclame Aqui.", _RA + "kabum/"),
    Store("fastshop", "Fast Shop", TRUSTED, 89, ("fastshop.com.br",), ("fast shop",), False,
          "Reputação Ótima (8,2) no Reclame Aqui.", _RA + "fast-shop/"),
    Store("mercadolivre", "Mercado Livre", GOOD, 82,
          ("mercadolivre.com.br", "mercadolivre.com", "meli.la", "mercadolibre.com"),
          ("ml", "mercado livre"), True,
          "Reputação Boa (7,6) no Reclame Aqui. Prefira lojas oficiais e Compra Garantida.",
          _RA + "mercado-livre/"),
    Store("casasbahia", "Casas Bahia", CAUTION, 55, ("casasbahia.com.br",), ("casas bahia",), True,
          "Reputação Ruim (5,9) no Reclame Aqui na consulta: compare antes de comprar.",
          _RA + "casas-bahia-loja-online/"),
    Store("ponto", "Ponto", CAUTION, 55, ("pontofrio.com.br", "ponto.com.br"),
          ("ponto frio", "pontofrio"), True,
          "Mesmo grupo da Casas Bahia: compare reputação e prazo antes de comprar."),
    Store("extra", "Extra", CAUTION, 55, ("extra.com.br",), (), True,
          "Mesmo grupo da Casas Bahia: compare reputação e prazo antes de comprar."),
    Store("americanas", "Americanas", GOOD, 68, ("americanas.com.br",), (), True,
          "Loja conhecida; verifique o vendedor e o momento da empresa."),
    Store("carrefour", "Carrefour", GOOD, 74, ("carrefour.com.br",), (), True,
          "Grande varejista; em marketplace, confira o vendedor."),
    Store("samsung", "Samsung", TRUSTED, 90, ("samsung.com", "shop.samsung.com"),
          ("loja samsung", "samsung shop"), False, "Loja oficial da fabricante."),
    Store("apple", "Apple", TRUSTED, 93, ("apple.com",), ("apple store",), False,
          "Loja oficial da fabricante."),
    Store("iplace", "iPlace", TRUSTED, 86, ("iplace.com.br",), (), False,
          "Revenda autorizada Apple."),
    Store("motorola", "Motorola", TRUSTED, 85, ("motorola.com.br",), (), False,
          "Loja oficial da fabricante."),
    Store("dell", "Dell", TRUSTED, 86, ("dell.com", "dell.com.br"), (), False,
          "Loja oficial da fabricante."),
    Store("lg", "LG", TRUSTED, 82, ("lg.com",), (), False, "Loja oficial da fabricante."),
    Store("electrolux", "Electrolux", TRUSTED, 84,
          ("loja.electrolux.com.br", "electrolux.com.br"), (), False,
          "Loja oficial da fabricante."),
    Store("brastemp", "Brastemp", TRUSTED, 84, ("brastemp.com.br",), (), False,
          "Loja oficial da fabricante."),
    Store("compracerta", "Compra Certa", TRUSTED, 80, ("compracerta.com.br",), (), False,
          "Loja do grupo Whirlpool."),
    Store("samsclub", "Sam's Club", GOOD, 78, ("samsclub.com.br",), ("sams club",), False,
          "Clube de compras do grupo Carrefour."),
    Store("webcontinental", "Webcontinental", GOOD, 70, ("webcontinental.com.br",), (), True),
    Store("casaevideo", "Casa & Video", GOOD, 68, ("casaevideo.com.br",),
          ("casa e video",), False),
    Store("trocafone", "Trocafone", GOOD, 70, ("trocafone.com.br", "trocafone.com"), (), False,
          "Especializada em seminovos com garantia."),
    Store("pichau", "Pichau", GOOD, 74, ("pichau.com.br",), (), False),
    Store("terabyte", "Terabyte", GOOD, 74, ("terabyteshop.com.br",),
          ("terabyte shop", "terabyteshop"), False),
    Store("shopee", "Shopee", GOOD, 66, ("shopee.com.br", "s.shopee.com.br", "shp.ee"), (), True,
          "Marketplace: a segurança depende do vendedor. Atenção a importados."),
    Store("aliexpress", "AliExpress", GOOD, 64, ("aliexpress.com", "s.click.aliexpress.com"), (),
          True, "Importado: considere impostos, prazo e garantia."),
    Store("olx", "OLX", CAUTION, 45, ("olx.com.br",), (), True,
          "Venda entre pessoas: nunca pague antes de ver o produto; desconfie de preço baixo."),
    Store("enjoei", "Enjoei", GOOD, 62, ("enjoei.com.br",), (), True, "Marketplace de usados."),
    Store("havan", "Havan", GOOD, 74, ("havan.com.br",), (), False),
    Store("carrefourparceiro", "Madeira Madeira", GOOD, 66, ("madeiramadeira.com.br",),
          ("madeiramadeira", "madeira madeira"), True),
    Store("netshoes", "Netshoes", GOOD, 78, ("netshoes.com.br",), (), True),
    Store("nike", "Nike", TRUSTED, 85, ("nike.com.br",), (), False),
)

BY_KEY = {s.key: s for s in STORES}
_BY_NAME = {normalize(n): s for s in STORES for n in (s.name, s.key, *s.aliases)}


def find_by_name(name: str) -> Store | None:
    value = normalize(name)
    if not value:
        return None
    if value in _BY_NAME:
        return _BY_NAME[value]
    for alias, store in sorted(_BY_NAME.items(), key=lambda kv: -len(kv[0])):
        if len(alias) >= 5 and alias in value:
            return store
    return None


def find_by_url(url: str) -> Store | None:
    host = (urlparse(url).hostname or "").lower()
    for store in STORES:
        for domain in store.domains:
            if host == domain or host.endswith("." + domain):
                return store
    return None


def find_in_text(text: str) -> Store | None:
    """Acha a loja citada num título/mensagem de oferta (a primeira que aparecer)."""
    value = f" {normalize(text)} "
    best: tuple[int, Store] | None = None
    for alias, store in _BY_NAME.items():
        if alias in {"ml", "extra", "ponto", "apple", "samsung", "motorola", "dell", "lg",
                     "nike", "electrolux", "brastemp"}:
            continue  # nomes que também são marcas ou palavras comuns
        at = value.find(f" {alias} ")
        if at >= 0 and (best is None or at < best[0]):
            best = (at, store)
    if best:
        return best[1]
    if value.startswith(" ml ") or " no ml " in value:
        return BY_KEY["mercadolivre"]
    return None


def identify(name: str, url: str = "") -> tuple[str, str]:
    """Retorna (chave, nome de exibição) da loja."""
    store = find_by_name(name) or (find_by_url(url) if url else None)
    if store:
        return store.key, store.name
    clean = " ".join((name or "").split()) or (urlparse(url).hostname or "Loja")
    return slug(clean), clean[:80]


def trust_of(store_key: str) -> dict:
    store = BY_KEY.get(store_key)
    if store:
        return {"level": store.trust, "score": store.score, "note": store.note,
                "reputation_url": store.reputation_url}
    return {"level": UNKNOWN, "score": 40,
            "note": "Loja fora da lista de confiança: pesquise reputação antes de comprar.",
            "reputation_url": PROCON_URL}
