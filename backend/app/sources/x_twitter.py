"""Monitoramento de ofertas no X (Twitter) para os produtos cadastrados e perfis de promoção.

Suporta dois caminhos automáticos no servidor (além da extensão do navegador):
1. API oficial do X v2 (`https://api.x.com/2/tweets/search/recent`) com Bearer Token ou
   Consumer Key + Secret (troca automática via `oauth2/token`), agrupando os produtos
   cadastrados em lotes econômicos e guardando `since_id` para não repetir leituras.
2. Ponte RSS de busca (`X_RSS_SEARCH_URL` com `{query}`), compatível com RSSHub, RSS-Bridge
   ou geradores de RSS, consultando cada produto monitorado automaticamente.
"""

from __future__ import annotations

import asyncio
import calendar
import re
from datetime import UTC, datetime
from urllib.parse import quote, quote_plus, unquote

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import dealtext, matching, stores
from ..core.appsettings import get_json, get_value, set_json, set_value, stored
from ..core.text import clip, short_hash
from ..db import session_scope
from ..models import Watch
from .base import (
    Blocked,
    FeedSource,
    Fetcher,
    FoundCoupon,
    FoundDeal,
    NotConfigured,
    SourceError,
)

API_BASE = "https://api.x.com"
DEAL_FILTER = (
    '("R$" OR oferta OR promo OR promocao OR promoção OR cupom OR desconto '
    "OR bug OR relampago OR relâmpago OR menor OR pix) -is:retweet -is:reply lang:pt"
)
MAX_QUERY_LEN = 490
_URL_RE = re.compile(r"https?://[^\s<>\"')]+")


def clean_bearer(raw: str) -> str:
    token = unquote((raw or "").strip())
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _watch_clause(query: str) -> str:
    tokens = matching.query_tokens(query)
    if not tokens:
        cleaned = " ".join(query.replace('"', " ").split())
        return f'"{cleaned}"' if cleaned else ""
    if len(tokens) == 1:
        return f'"{tokens[0]}"'
    inner = " ".join(f'"{t}"' for t in tokens[:5])
    return f"({inner})"


def build_product_batches(queries: list[str], max_len: int = MAX_QUERY_LEN) -> list[str]:
    """Agrupa os produtos cadastrados em expressões que cabem no limite de 512 caracteres da API."""
    clauses: list[str] = []
    seen: set[str] = set()
    for q in queries:
        clause = _watch_clause(q)
        if clause and clause.lower() not in seen:
            seen.add(clause.lower())
            clauses.append(clause)
    if not clauses:
        return []

    suffix = f" {DEAL_FILTER}"
    batches: list[str] = []
    current: list[str] = []
    for clause in clauses:
        candidate_group = " OR ".join([*current, clause])
        full = f"({candidate_group}){suffix}"
        if current and len(full) > max_len:
            batches.append(f"({' OR '.join(current)}){suffix}")
            current = [clause]
        else:
            current.append(clause)
    if current:
        batches.append(f"({' OR '.join(current)}){suffix}")
    return batches


def build_account_batches(accounts_csv: str, max_len: int = MAX_QUERY_LEN) -> list[str]:
    handles = []
    seen: set[str] = set()
    for raw in re.split(r"[\s,;]+", accounts_csv or ""):
        handle = raw.strip().lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle) and handle.lower() not in seen:
            seen.add(handle.lower())
            handles.append(handle)
    if not handles:
        return []
    suffix = " -is:retweet -is:reply"
    batches: list[str] = []
    current: list[str] = []
    for h in handles:
        part = f"from:{h}"
        candidate = f"({' OR '.join([*current, part])}){suffix}"
        if current and len(candidate) > max_len:
            batches.append(f"({' OR '.join(current)}){suffix}")
            current = [part]
        else:
            current.append(part)
    if current:
        batches.append(f"({' OR '.join(current)}){suffix}")
    return batches


def build_x_live_url(queries: list[str]) -> str:
    """Gera o endereço de busca ao vivo (aba Latest) no X para um ou vários produtos."""
    clauses = [_watch_clause(q) for q in queries if q and q.strip()]
    clauses = [c for c in dict.fromkeys(clauses) if c][:8]
    if not clauses:
        expr = '(oferta OR cupom OR bug) "R$" lang:pt'
    elif len(clauses) == 1:
        expr = f'{clauses[0]} ("R$" OR cupom OR oferta OR promo) lang:pt'
    else:
        expr = f'({" OR ".join(clauses)}) ("R$" OR cupom OR oferta OR promo) lang:pt'
    return f"https://x.com/search?q={quote(expr)}&src=typed_query&f=live"


def active_watch_queries(db: Session) -> list[str]:
    rows = db.scalars(
        select(Watch.query)
        .where(Watch.active, Watch.kind == "product")
        .order_by(Watch.id)
    ).all()
    return [q for q in rows if q and q.strip()]


async def obtain_bearer_token(fetcher: Fetcher, db: Session) -> str:
    direct = clean_bearer(get_value(db, "x_bearer_token"))
    if direct:
        return direct
    api_key = get_value(db, "x_api_key").strip()
    api_secret = get_value(db, "x_api_secret").strip()
    if not api_key or not api_secret:
        return ""
    cached = clean_bearer(stored(db, "x_bearer_cache") or "")
    if cached:
        return cached
    response = await fetcher.request(
        "POST",
        f"{API_BASE}/oauth2/token",
        auth=(api_key, api_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    payload = response.json()
    token = clean_bearer(str(payload.get("access_token") or ""))
    if not token:
        raise SourceError("X API não retornou access_token válido")
    set_value(db, "x_bearer_cache", token)
    db.commit()
    return token


def _tweet_title(text: str) -> str:
    cleaned = _URL_RE.sub("", text)
    lines = [" ".join(line.split()) for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return clip(" ".join(text.split()), 220)
    head = lines[0]
    if len(head) < 28 and len(lines) > 1:
        head = f"{head} — {lines[1]}"
    return clip(head, 220)


def parse_x_api_response(payload: dict) -> tuple[list[FoundDeal], str]:
    """Converte a resposta JSON de `/2/tweets/search/recent` em ofertas do radar."""
    if not isinstance(payload, dict):
        raise SourceError("X API: formato inesperado")
    tweets = payload.get("data") or []
    includes = payload.get("includes") or {}
    users = {
        str(u.get("id")): u
        for u in (includes.get("users") or [])
        if isinstance(u, dict) and u.get("id")
    }
    media_map = {
        str(m.get("media_key")): (m.get("url") or m.get("preview_image_url") or "")
        for m in (includes.get("media") or [])
        if isinstance(m, dict) and m.get("media_key")
    }
    newest_id = str((payload.get("meta") or {}).get("newest_id") or "")
    out: list[FoundDeal] = []

    for tweet in tweets:
        if not isinstance(tweet, dict) or not tweet.get("id"):
            continue
        tid = str(tweet["id"])
        if not newest_id or (tid.isdigit() and newest_id.isdigit() and int(tid) > int(newest_id)):
            newest_id = tid
        raw_text = str(tweet.get("text") or "").strip()
        if not raw_text:
            continue

        entities = tweet.get("entities") or {}
        expanded_links: list[str] = []
        text = raw_text
        for u in entities.get("urls") or []:
            if not isinstance(u, dict):
                continue
            short = str(u.get("url") or "")
            full = str(u.get("unwound_url") or u.get("expanded_url") or short).strip()
            if short and full:
                text = text.replace(short, full)
            host_check = full.lower()
            if full.startswith("http") and not any(
                d in host_check for d in ("x.com/", "twitter.com/", "pic.twitter.com")
            ):
                expanded_links.append(stores.unwrap_url(full))

        link = expanded_links[0] if expanded_links else ""
        price, old_price = dealtext.find_prices(text)
        coupon = dealtext.find_coupon(text)
        store_match = (
            (stores.find_by_url(link) if link else None)
            or stores.find_in_text(text)
        )
        if (
            price is None
            and not coupon
            and store_match is None
            and not dealtext.looks_like_deal(text)
        ):
            continue

        author = users.get(str(tweet.get("author_id") or ""), {})
        username = str(author.get("username") or "").strip()
        media_keys = ((tweet.get("attachments") or {}).get("media_keys")) or []
        image = next((media_map[k] for k in media_keys if media_map.get(k)), "")

        published = None
        if created := tweet.get("created_at"):
            try:
                published = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            except ValueError:
                published = None

        tweet_url = (
            f"https://x.com/{username}/status/{tid}"
            if username
            else f"https://x.com/i/web/status/{tid}"
        )
        out.append(
            FoundDeal(
                source="x_twitter",
                source_name=f"X · @{username}" if username else "X (Twitter)",
                external_id=tid,
                title=_tweet_title(text),
                url=tweet_url,
                link=link,
                description=clip(text, 1000),
                image=image,
                store=store_match.name if store_match else "",
                price=price,
                old_price=old_price,
                coupon=coupon,
                published_at=published,
                is_coupon=bool(coupon) and price is None,
            )
        )
    return out, newest_id


async def _search_x_batches(
    fetcher: Fetcher, token: str, batches: list[str], state_key: str
) -> list[FoundDeal]:
    with session_scope() as db:
        since_map: dict[str, str] = dict(get_json(db, state_key, {}))

    headers = {"Authorization": f"Bearer {token}"}
    all_deals: dict[str, FoundDeal] = {}
    updated_since = dict(since_map)

    for query in batches:
        qhash = short_hash(query)
        params: dict[str, str | int] = {
            "query": query,
            "max_results": 35,
            "tweet.fields": "created_at,author_id,entities,attachments,public_metrics",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username,name",
            "media.fields": "url,preview_image_url",
        }
        if since_id := since_map.get(qhash):
            params["since_id"] = since_id
        try:
            payload = await fetcher.get_json(
                f"{API_BASE}/2/tweets/search/recent",
                params=params,
                headers=headers,
            )
        except Blocked as exc:
            if "401" in str(exc):
                with session_scope() as db:
                    set_value(db, "x_bearer_cache", "")
                    db.commit()
            raise
        deals, newest = parse_x_api_response(payload)
        if newest:
            updated_since[qhash] = newest
        for d in deals:
            all_deals[d.external_id] = d

    if updated_since != since_map:
        # mantém no máximo 40 hashes recentes para não acumular lixo
        trimmed = dict(list(updated_since.items())[-40:])
        with session_scope() as db:
            set_json(db, state_key, trimmed)
            db.commit()
    return list(all_deals.values())


def parse_x_rss(content: bytes, label: str = "X (RSS)") -> list[FoundDeal]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise SourceError(f"{label}: feed RSS ilegível")
    out: list[FoundDeal] = []
    for entry in parsed.entries:
        raw_title = " ".join(str(entry.get("title") or "").split())
        summary = str(entry.get("summary") or entry.get("description") or "")
        plain_summary = re.sub(r"<[^>]+>", " ", summary)
        plain_summary = " ".join(plain_summary.split())
        full = f"{raw_title}\n{plain_summary}".strip()
        if not full:
            continue
        entry_url = str(entry.get("link") or "").strip()
        ext_links = [
            stores.unwrap_url(m.group(0).rstrip(')"\'>,.'))
            for m in _URL_RE.finditer(f"{summary} {raw_title}")
        ]
        link = next(
            (
                u
                for u in ext_links
                if not any(d in u.lower() for d in ("x.com/", "twitter.com/", "nitter"))
            ),
            "",
        )
        price, old_price = dealtext.find_prices(full)
        coupon = dealtext.find_coupon(full)
        store_match = (stores.find_by_url(link) if link else None) or stores.find_in_text(full)
        if price is None and not coupon and store_match is None and not dealtext.looks_like_deal(full):
            continue
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        published = (
            datetime.fromtimestamp(calendar.timegm(stamp), UTC) if stamp else None
        )
        image = ""
        if m := re.search(r'<img[^>]+src="(https://[^"]+)"', summary):
            image = m.group(1)
        ident = str(entry.get("id") or entry_url or short_hash(full))
        if sm := re.search(r"/status/(\d+)", entry_url):
            ident = sm.group(1)
        out.append(
            FoundDeal(
                source="x_twitter",
                source_name=label,
                external_id=ident,
                title=_tweet_title(raw_title or plain_summary),
                url=entry_url,
                link=link,
                description=clip(plain_summary or raw_title, 900),
                image=image,
                store=store_match.name if store_match else "",
                price=price,
                old_price=old_price,
                coupon=coupon,
                published_at=published,
                is_coupon=bool(coupon) and price is None,
            )
        )
    return out


class XTwitterWatchesFeed(FeedSource):
    """Busca ofertas no X (Twitter) especificamente para os produtos cadastrados."""

    key = "x:watches"
    name = "X (Twitter) · produtos monitorados"
    interval_seconds = 120

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        with session_scope() as db:
            queries = active_watch_queries(db)
            rss_template = get_value(db, "x_rss_search_url").strip()
            token = await obtain_bearer_token(fetcher, db)

        if not token and not rss_template:
            raise NotConfigured(
                "Configure o Bearer Token da API do X (ou URL RSS de busca) em Configurações → "
                "Integrações, ou use a extensão do navegador"
            )
        if not queries:
            return [], []

        deals: dict[str, FoundDeal] = {}
        if token:
            batches = build_product_batches(queries)
            for item in await _search_x_batches(fetcher, token, batches, "x_watch_since"):
                deals[item.external_id] = item

        if rss_template and "{query}" in rss_template:
            seen_q: list[str] = []
            for q in queries:
                norm_q = " ".join(q.lower().split())
                if norm_q not in seen_q:
                    seen_q.append(norm_q)
            for q in seen_q[:12]:
                url = rss_template.replace("{query}", quote_plus(f"{q} R$"))
                response = await fetcher.request("GET", url, guard=True)
                for item in parse_x_rss(response.content, f"X · {q}"):
                    deals.setdefault(item.external_id, item)
        return list(deals.values()), []


class XTwitterAccountsFeed(FeedSource):
    """Acompanha perfis brasileiros de ofertas no X (ex.: @pelandobr, @promobitoficial)."""

    key = "x:accounts"
    name = "X (Twitter) · perfis de ofertas"
    interval_seconds = 180

    async def fetch(self, fetcher: Fetcher) -> tuple[list[FoundDeal], list[FoundCoupon]]:
        with session_scope() as db:
            accounts = get_value(db, "x_accounts").strip()
            token = await obtain_bearer_token(fetcher, db)

        if not token:
            raise NotConfigured(
                "Informe o Bearer Token da API do X em Configurações → Integrações para ler perfis automaticamente"
            )
        batches = build_account_batches(accounts)
        if not batches:
            return [], []
        deals = await _search_x_batches(fetcher, token, batches, "x_accounts_since")
        return deals, []


async def test_connection(db: Session, query_hint: str = "") -> dict:
    """Valida a configuração atual do X a partir da tela de Configurações."""
    queries = active_watch_queries(db) or ([query_hint] if query_hint else ["PS5"])
    rss_template = get_value(db, "x_rss_search_url").strip()
    async with Fetcher(min_delay=0.2) as fetcher:
        token = await obtain_bearer_token(fetcher, db)
        if not token and not rss_template:
            raise NotConfigured(
                "Salve o Bearer Token (ou API Key + Secret, ou URL RSS de busca) antes de testar"
            )
        found: list[FoundDeal] = []
        mode = []
        if token:
            mode.append("API v2 oficial")
            batch = build_product_batches(queries[:4])[0]
            payload = await fetcher.get_json(
                f"{API_BASE}/2/tweets/search/recent",
                params={
                    "query": batch,
                    "max_results": 15,
                    "tweet.fields": "created_at,author_id,entities,attachments",
                    "expansions": "author_id,attachments.media_keys",
                    "user.fields": "username,name",
                    "media.fields": "url,preview_image_url",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            deals, _ = parse_x_api_response(payload)
            found.extend(deals)
        if rss_template and "{query}" in rss_template:
            mode.append("Ponte RSS")
            url = rss_template.replace("{query}", quote_plus(f"{queries[0]} R$"))
            resp = await fetcher.request("GET", url, guard=True)
            found.extend(parse_x_rss(resp.content))
    return {
        "ok": True,
        "mode": " + ".join(mode),
        "watches": len(queries),
        "sample_count": len(found),
        "live_url": build_x_live_url(queries),
    }


def test_connection_sync(db: Session) -> dict:
    return asyncio.run(test_connection(db))
