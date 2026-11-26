from __future__ import annotations

import pytest
from sqlalchemy import select

from app import config, db
from app.models import User
from app.security import ensure_admin, limiter

PASSWORD = "senha-de-teste-123"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Cada teste usa um banco próprio e nenhuma configuração do ambiente."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("SECRET_KEY", "chave-de-teste-com-tamanho-suficiente-0123456789")
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    config.get_settings.cache_clear()
    db.reset_engine()
    limiter.failures.clear()
    db.init_db()
    yield
    db.reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture
def session():
    with db.session_scope() as s:
        yield s


@pytest.fixture
def user(session) -> User:
    ensure_admin(session)
    return session.scalar(select(User))
