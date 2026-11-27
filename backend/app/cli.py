"""Utilitários de linha de comando.

    python -m app.cli reset-password <usuario>
    python -m app.cli check-sources [termo]
"""

from __future__ import annotations

import asyncio
import getpass
import secrets
import sys

from sqlalchemy import select

from .core import matching
from .db import init_db, session_scope
from .models import User
from .security import MIN_PASSWORD, hash_password
from .sources.base import Fetcher, NotConfigured, SearchParams
from .sources.registry import feed_sources, store_sources


def reset_password(username: str) -> int:
    init_db()
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            print("Usuário não encontrado")
            return 1
        typed = ""
        if sys.stdin.isatty():
            typed = getpass.getpass("Nova senha (vazio = gerar): ")
        if typed and len(typed) < MIN_PASSWORD:
            print(f"A senha precisa de ao menos {MIN_PASSWORD} caracteres")
            return 1
        password = typed or secrets.token_urlsafe(12)
        user.password_hash = hash_password(password)
        user.token_version += 1
    if not typed:
        print(f"Senha gerada para {username}: {password}")
    else:
        print("Senha alterada")
    return 0


async def check_sources(query: str) -> int:
    """Testa de verdade cada fonte a partir deste servidor."""
    init_db()
    with session_scope() as db:
        stores, feeds = store_sources(db), feed_sources(db)
    criteria = matching.Criteria(query)
    params = SearchParams(
        query=query, include_used=True,
        is_relevant=lambda title: matching.matches(title, criteria),
    )
    failures = optional = 0
    async with Fetcher() as fetcher:

        async def store(source):
            try:
                offers = await asyncio.wait_for(source.search(fetcher, params), 120)
                offers = [o for o in offers if matching.matches(o.match_title or o.title, criteria)]
                best = min(offers, key=lambda o: o.price, default=None)
                sample = f" · menor R$ {best.price:.2f} ({best.store})" if best else ""
                return "ok", f"loja  {source.key:26} {len(offers):4} ofertas{sample}"
            except NotConfigured as exc:
                return "opt", f"loja  {source.key:26} OPCIONAL (não configurada): {exc}"
            except Exception as exc:  # noqa: BLE001
                return "err", f"loja  {source.key:26} FALHOU: {exc or type(exc).__name__}"

        async def feed(source):
            try:
                deals, coupons = await asyncio.wait_for(source.fetch(fetcher), 90)
                return "ok", (f"radar {source.key:26} {len(deals):4} ofertas, "
                              f"{len(coupons)} cupons")
            except NotConfigured as exc:
                return "opt", f"radar {source.key:26} OPCIONAL (não configurada): {exc}"
            except Exception as exc:  # noqa: BLE001
                return "err", f"radar {source.key:26} FALHOU: {exc or type(exc).__name__}"

        jobs = [store(s) for s in stores] + [feed(s) for s in feeds]
        for state, line in await asyncio.gather(*jobs):
            if state == "err":
                failures += 1
            elif state == "opt":
                optional += 1
            print(line)
    active_total = len(jobs) - optional
    print(
        f"\n{active_total - failures} de {active_total} fontes ativas responderam "
        f"({optional} opcionais aguardando chave)"
    )
    return 0


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["reset-password"] and len(args) == 2:
        raise SystemExit(reset_password(args[1]))
    if args[:1] == ["check-sources"]:
        raise SystemExit(asyncio.run(check_sources(" ".join(args[1:]) or "ps5")))
    print(__doc__)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
