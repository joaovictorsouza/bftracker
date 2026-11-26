"""Decide se um anúncio é o produto procurado e a qual variante pertence."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .text import contains_term, normalize

# Palavras que, no começo do título, indicam acessório/jogo/peça e não o produto em si.
ACCESSORY_HEADS = {
    "jogo", "jogos", "game", "controle", "capa", "capinha", "case", "pelicula", "cabo",
    "carregador", "suporte", "base", "dock", "headset", "fone", "adaptador", "skin", "adesivo",
    "volante", "kit", "protetor", "bolsa", "mochila", "estojo", "grip", "thumb", "cooler",
    "ventoinha", "tampa", "placa", "faceplate", "camera", "microfone", "teclado", "mouse",
    "ssd", "hd", "memoria", "cartao", "gift", "credito", "assinatura", "pulseira", "bateria",
    "fonte", "lente", "leitor", "unidade", "pecas", "peca", "display", "tela", "flex",
    "conserto", "manutencao", "aluguel", "locacao", "caixa", "manual", "poster", "boneco",
    "chaveiro", "camiseta", "caneca", "luminaria", "gamepad", "joystick", "analogico",
    "apoio", "organizador", "refil", "filtro", "forma", "cesto", "borracha", "conta",
    "midia", "painel", "reprodutor", "estacao", "mao", "carregamento", "dualsense", "mesa", "rack", "antena", "hub", "extensor", "compativel",
}

_FOR_RE = re.compile(
    r"\b(para|p|compativel com|compativel|de reposicao|for)\s+(o\s+|a\s+|os\s+)?"
    r"(console\s+|videogame\s+)?(sony\s+|apple\s+|samsung\s+|microsoft\s+)?$"
)
_DEFECT_RE = re.compile(
    r"\b(defeito|quebrad[oa]|sucata|para pecas|retirada de pecas|nao liga|banid[oa]|"
    r"somente (a )?caixa|so (a )?caixa|caixa vazia|procuro|compro|troco por|aluguel|alugo)\b"
)
# palavras que podem vir antes de "PS5" no título do próprio console
_CONSOLE_PREFIX = {
    "console", "sony", "videogame", "video", "game", "pack", "bundle", "combo", "usado",
    "usada", "seminovo", "novo", "vendo", "lindo", "lacrado", "o", "um", "do", "de", "+",
}
_CONSOLE_EXTRA = {"pro", "slim", "digital", "fat"}

_USED_RE = re.compile(r"\b(usad[oa]|seminov[oa]|semi nov[oa]|vitrine|open ?box|de segunda mao)\b")
_REFURB_RE = re.compile(r"\b(recondicionad[oa]|reembalad[oa]|refurbished|renewed|reformad[oa])\b")

_MODIFIERS = [
    ("pro max", "Pro Max"), ("pro", "Pro"), ("max", "Max"), ("plus", "Plus"),
    ("ultra", "Ultra"), ("mini", "Mini"), ("slim", "Slim"), ("fat", "Fat"), ("lite", "Lite"),
    ("fe", "FE"), ("air", "Air"), ("oled", "OLED"), ("qled", "QLED"), ("neo", "Neo"),
    ("series x", "Series X"), ("series s", "Series S"), ("edge", "Edge"), ("fold", "Fold"),
    ("flip", "Flip"), ("se", "SE"),
]


@dataclass
class Criteria:
    query: str
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None


def query_tokens(query: str) -> list[str]:
    stop = {"de", "da", "do", "com", "e", "para", "o", "a", "em"}
    return [t for t in normalize(query).split() if t not in stop and t != "+"]


def _has_token(text: str, token: str) -> bool:
    if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text):
        return True
    # "iphone17" ou "galaxys26" escritos juntos
    if len(token) >= 5 and token in text.replace(" ", ""):
        return True
    return False


def is_accessory(title: str, query: str) -> bool:
    text = normalize(title)
    wanted = set(query_tokens(query))
    words = text.split()
    if not words:
        return True
    head = [w for w in words[:3] if not w.isdigit()]
    if head and head[0] in ACCESSORY_HEADS and head[0] not in wanted:
        return True
    # "... para PS5", "compatível com iPhone": o produto procurado é só o alvo do acessório
    first = next(iter(query_tokens(query)), "")
    if first:
        match = re.search(rf"(?<![a-z0-9]){re.escape(first)}(?![a-z0-9])", text)
        if match and _FOR_RE.search(text[: match.start()]):
            return True
    return _is_game_for_console(words, text, wanted)


def _is_game_for_console(words: list[str], text: str, wanted: set[str]) -> bool:
    """Ao procurar um PlayStation, "Minecraft PS5 Mídia Física" é um jogo, não o console."""
    platform = wanted & {"ps4", "ps5"}
    if not platform or not wanted - platform <= _CONSOLE_EXTRA:
        return False
    if re.search(r"\b(console|sony)\b", text):
        return False
    if re.search(r"\bmidia fisica\b", text):
        return True
    name = next(iter(platform))
    if name not in words:
        return False
    at = words.index(name)
    if words[0] in {"bundle", "pack", "pacote", "combo"}:
        return False
    if at + 1 < len(words) and re.fullmatch(r"slim|825gb|1tb|2tb", words[at + 1]):
        return False  # "... PlayStation 5 Slim": o título descreve o console
    return not set(words[:at]) <= _CONSOLE_PREFIX


def matches(title: str, criteria: Criteria, price: float | None = None) -> bool:
    text = normalize(title)
    if not text:
        return False
    for token in query_tokens(criteria.query):
        if not _has_token(text, token):
            return False
    if criteria.include_terms and not all(contains_term(text, t) for t in criteria.include_terms):
        return False
    if any(contains_term(text, t) for t in criteria.exclude_terms):
        return False
    if criteria.query and is_accessory(title, criteria.query):
        return False
    wanted = normalize(criteria.query)
    defect = _DEFECT_RE.search(text)
    if defect and defect.group(0) not in wanted:
        return False
    if price is not None:
        if criteria.min_price and price < criteria.min_price:
            return False
        if criteria.max_price and price > criteria.max_price:
            return False
    return True


def detect_condition(title: str, default: str = "new") -> str:
    text = normalize(title)
    if _REFURB_RE.search(text):
        return "refurbished"
    if _USED_RE.search(text):
        return "used"
    return default


_STORAGE_RE = re.compile(r"\b(\d{1,4})(gb|tb)\b")


def has_storage(text: str) -> bool:
    return any(u == "tb" or int(n) >= 32 for n, u in _STORAGE_RE.findall(normalize(text)))


def best_variant_title(title: str, product: str, criteria: Criteria) -> str:
    """Escolhe o texto que melhor descreve a variante quando há título do anúncio e do
    produto agrupado pelo comparador."""
    if not product:
        return title
    if not matches(title, criteria):
        return product
    if not has_storage(title) and has_storage(product):
        sizes = " ".join(f"{n}{u}" for n, u in _STORAGE_RE.findall(normalize(product)))
        return f"{title} {sizes}"
    return title


def variant_of(title: str, query: str) -> tuple[str, str]:
    """Extrai o que diferencia o anúncio: modelo, edição digital, armazenamento, tela, pacote."""
    text = normalize(title)
    wanted = set(query_tokens(query))
    parts: list[str] = []

    consumed = text
    for token, label in _MODIFIERS:
        if re.search(rf"(?<![a-z0-9]){token}(?![a-z0-9])", consumed):
            if not set(token.split()) <= wanted:
                parts.append(label)
            consumed = re.sub(rf"(?<![a-z0-9]){token}(?![a-z0-9])", " ", consumed)

    is_console = bool({"ps4", "ps5", "xbox"} & wanted) or " console " in f" {text} "
    if is_console:
        if "Fat" in parts:
            parts.remove("Fat")
        # todo PS5 à venda que não é Pro é Slim: separar só fragmentaria as variantes
        if "ps5" in wanted and "Slim" in parts:
            parts.remove("Slim")
        if re.search(r"\b(digital|sem leitor)\b", text) and "digital" not in wanted:
            parts.append("Digital")
        elif re.search(r"\b(com leitor|leitor de discos?|disk|disc|midia fisica|blue? ?ray)\b",
                       text):
            parts.append("Com leitor")

    sizes = [(int(n), u) for n, u in re.findall(r"\b(\d{1,4})(gb|tb)\b", text)]
    storage = [(n, u) for n, u in sizes if u == "tb" or n >= 32]
    if storage:
        number, unit = max(storage, key=lambda s: s[0] * (1024 if s[1] == "tb" else 1))
        if f"{number}{unit}" not in wanted:
            parts.append(f"{number}{unit.upper()}")
    ram = re.search(r"\b(\d{1,3})gb (?:de )?(?:memoria )?ram\b|\bram (\d{1,3})gb\b", text)
    if ram and re.search(r"\b(notebook|laptop|macbook|computador|desktop|pc|chromebook)\b", text):
        value = ram.group(1) or ram.group(2)
        if int(value) < 32 or len(storage) > 1:
            parts.append(f"{value}GB RAM")
    screen = re.search(r"\b(\d{2})pol\b", text)
    if screen and f"{screen.group(1)}pol" not in wanted:
        parts.append(f'{screen.group(1)}"')
    if re.search(r"\b(bundle|pacote|combo)\b|\+ ?(jogos?|\d+ jogos?|ea|fc ?\d+|astro)|"
                 r"\b\d+ jogos\b|\be \d+ jogos?\b", text):
        parts.append("Com jogos/bundle")

    if not parts:
        return "padrao", "Padrão"
    ordered = list(dict.fromkeys(parts))
    key = "-".join(sorted(re.sub(r"[^a-z0-9]", "", p.lower()) for p in ordered))
    return key[:120], " · ".join(ordered)[:160]
