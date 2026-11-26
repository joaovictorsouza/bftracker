"""Normalização de texto e preços em português do Brasil."""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata

_SYNONYMS: list[tuple[str, str]] = [
    (r"\bplay\s*station\s*([345])\b", r"ps\1"),
    (r"\bps\s+([345])\b", r"ps\1"),
    (r"\bx[\s-]?box\b", "xbox"),
    (r"\bi\s+phone\b", "iphone"),
    (r"\bair\s+pods\b", "airpods"),
    (r"\bair\s*fryer\b", "airfryer"),
    (r"\bsmart\s+tv\b", "smart tv"),
    (r"(\d+)\s*(gb|tb)\b", r"\1\2"),
    (r"(\d+)\s*(?:polegadas|pol\b|\")", r"\1pol"),
    (r"\b(ps[345])(?=slim|pro|digital)", r"\1 "),
]

PRICE_RE = re.compile(
    r"R\$\s*(\d{1,3}(?:[.\s]\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)(?![\d])", re.IGNORECASE
)


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize(value: str) -> str:
    text = re.sub("[®™©]", "", html.unescape(value or ""))
    text = strip_accents(text).lower()
    for pattern, repl in _SYNONYMS:
        text = re.sub(pattern, repl, text)
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    text = text.replace("+", " + ")
    return " ".join(text.split())


def tokens(value: str) -> list[str]:
    return normalize(value).split()


def contains_term(normalized_text: str, term: str) -> bool:
    needle = normalize(term)
    if not needle:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", normalized_text) is not None


def parse_brl(value: str | float | int | None) -> float | None:
    """Converte '1.234,56', 'R$ 3.800' ou '1234.56' em float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    text = re.sub(r"[^\d.,]", "", str(value).replace("\xa0", " "))
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return number if number > 0 else None


def brl(value: float | None) -> str:
    if value is None:
        return "—"
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"R$ {text}"


def slug(value: str, limit: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "-", strip_accents(value or "").lower()).strip("-")[:limit]


def short_hash(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:20]


def clip(value: str, limit: int) -> str:
    value = " ".join((value or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
