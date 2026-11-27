from __future__ import annotations

import hashlib
import logging
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ApiToken, User, utcnow

log = logging.getLogger(__name__)

COOKIE = "bft_session"
MIN_PASSWORD = 8
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def check_credentials(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None:
        verify_password(password, _DUMMY_HASH)  # mesmo tempo de resposta
        return None
    return user if verify_password(password, user.password_hash) else None


class LoginLimiter:
    """No máximo `limit` falhas por chave dentro da janela."""

    def __init__(self, limit: int = 8, window: int = 900):
        self.limit, self.window = limit, window
        self.failures: dict[str, deque] = defaultdict(deque)

    def _prune(self, key: str) -> deque:
        queue = self.failures[key]
        while queue and queue[0] < time.monotonic() - self.window:
            queue.popleft()
        return queue

    def check(self, *keys: str) -> None:
        if any(len(self._prune(k)) >= self.limit for k in keys):
            raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos.")

    def fail(self, *keys: str) -> None:
        if len(self.failures) > 10_000:
            self.failures.clear()
        for key in keys:
            self.failures[key].append(time.monotonic())

    def reset(self, *keys: str) -> None:
        for key in keys:
            self.failures.pop(key, None)


limiter = LoginLimiter()


def is_https_request(request: Request) -> bool:
    """Detecta HTTPS direto ou atrás de Cloudflare / Traefik (Dokploy)."""
    if request.url.scheme == "https":
        return True
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if proto == "https":
        return True
    cf_visitor = (request.headers.get("cf-visitor") or "").lower()
    return '"https"' in cf_visitor


def client_ip(request: Request) -> str:
    """IP real do visitante atrás da Cloudflare e do proxy reverso do Dokploy."""
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf_ip:
        return cf_ip[:64]
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff[:64]
    return request.client.host if request.client else "?"


def set_session_cookie(response: Response, request: Request, user: User) -> None:
    settings = get_settings()
    lifetime = timedelta(days=settings.session_days)
    token = jwt.encode(
        {"sub": str(user.id), "ver": user.token_version, "exp": utcnow() + lifetime},
        settings.secret,
        algorithm="HS256",
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=is_https_request(request),
        path="/",
    )


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_token() -> tuple[str, str, str]:
    raw = f"bft_{secrets.token_urlsafe(28)}"
    return raw, raw[:12], hash_api_token(raw)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        raw_token = auth[7:].strip()
        if not raw_token.startswith("bft_"):
            raise HTTPException(401, "Chave de acesso inválida")
        row = db.scalar(
            select(ApiToken).where(ApiToken.token_hash == hash_api_token(raw_token))
        )
        if row is None or row.user is None:
            raise HTTPException(401, "Chave de acesso inválida ou revogada")
        now = utcnow()
        if row.last_used_at is None or (now - row.last_used_at) > timedelta(seconds=60):
            row.last_used_at = now
            db.commit()
        return row.user

    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Faça login para continuar")
    try:
        data = jwt.decode(token, get_settings().secret, algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Sessão expirada") from None
    if user is None or data.get("ver") != user.token_version:
        raise HTTPException(401, "Sessão expirada")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Apenas administradores")
    return user


def ensure_admin(db: Session) -> None:
    """Cria o primeiro administrador. Sem ADMIN_PASSWORD, gera uma senha e mostra no log."""
    from .core.radar import default_interests

    if db.scalar(select(func.count(User.id))):
        return
    settings = get_settings()
    password = settings.admin_password
    generated = False
    if len(password) < MIN_PASSWORD:
        if password:
            log.warning("ADMIN_PASSWORD tem menos de %s caracteres e foi ignorada", MIN_PASSWORD)
        password, generated = secrets.token_urlsafe(12), True
    user = User(
        username=settings.admin_username.strip() or "admin",
        password_hash=hash_password(password),
        is_admin=True,
        email=settings.admin_email.strip(),
        prefs={},
    )
    db.add(user)
    try:
        db.flush()
        default_interests(db, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        return
    if generated:
        log.warning(
            "\n%s\n  Usuário: %s\n  Senha gerada: %s\n  Troque a senha no primeiro acesso.\n%s",
            "=" * 60, user.username, password, "=" * 60,
        )
