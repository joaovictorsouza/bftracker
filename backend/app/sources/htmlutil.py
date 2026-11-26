from __future__ import annotations

import json
import re
from collections.abc import Iterator

from .base import SourceError

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_LD_RE = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S)


def next_data(page: str) -> dict:
    match = _NEXT_RE.search(page)
    if not match:
        raise SourceError("Página mudou de formato (__NEXT_DATA__ ausente)")
    try:
        return json.loads(match.group(1))
    except ValueError as exc:
        raise SourceError("Dados da página ilegíveis") from exc


def find_key(obj, key: str, depth: int = 0):
    """Primeira ocorrência de `key` em uma estrutura aninhada."""
    if depth > 12:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        values = obj.values()
    elif isinstance(obj, list):
        values = obj
    else:
        return None
    for value in values:
        found = find_key(value, key, depth + 1)
        if found is not None:
            return found
    return None


def json_ld(page: str) -> Iterator[dict]:
    for raw in _LD_RE.findall(page):
        try:
            data = json.loads(raw.strip(), strict=False)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.append(item["@graph"])
                yield item
