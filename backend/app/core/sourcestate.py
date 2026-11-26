"""Saúde de cada fonte e recuo progressivo quando ela bloqueia ou falha."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import SourceStatus, utcnow

MAX_BACKOFF = timedelta(hours=6)


def get_status(db: Session, key: str, name: str, kind: str) -> SourceStatus:
    status = db.get(SourceStatus, key)
    if status is None:
        status = SourceStatus(source=key, name=name, kind=kind, enabled=True, failures=0,
                              state="unknown", message="", last_items=0, baseline_done=False)
        db.add(status)
        db.flush()
    elif status.name != name:
        status.name = name
    return status


def is_waiting(status: SourceStatus) -> bool:
    return status.blocked_until is not None and status.blocked_until > utcnow()


def mark_ok(db: Session, key: str, name: str, kind: str, items: int) -> None:
    status = get_status(db, key, name, kind)
    status.state, status.message, status.failures = "ok", "", 0
    status.blocked_until = None
    status.last_ok_at = status.last_run_at = utcnow()
    status.last_items = items


def mark_failure(db: Session, key: str, name: str, kind: str, state: str, message: str) -> None:
    status = get_status(db, key, name, kind)
    status.failures += 1
    status.state, status.message = state, message[:500]
    status.last_run_at = utcnow()
    # bloqueio recua já na primeira vez; erros comuns só a partir da terceira
    if state == "blocked":
        delay = timedelta(minutes=15 * 2 ** (status.failures - 1))
    elif status.failures >= 3:
        delay = timedelta(minutes=5 * 2 ** (status.failures - 3))
    else:
        return
    status.blocked_until = utcnow() + min(delay, MAX_BACKOFF)
