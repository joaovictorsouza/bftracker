"""API HTTP e entrega da interface web."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from .api import admin, auth, notifications, radar, watches
from .config import get_settings
from .db import init_db, session_scope
from .models import Heartbeat, utcnow
from .notify.webpush import ensure_keys
from .security import ensure_admin

log = logging.getLogger("bftracker")

CSP = (
    "default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    with session_scope() as db:
        ensure_admin(db)
        ensure_keys(db)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="BFTracker", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD"):
            # cabeçalho que só o próprio app consegue enviar (proteção contra CSRF)
            if request.headers.get("x-requested-with") != "bftracker":
                return JSONResponse({"detail": "Requisição não permitida"}, status_code=403)
            if int(request.headers.get("content-length") or 0) > 100_000:
                return JSONResponse({"detail": "Requisição grande demais"}, status_code=413)
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for module in (auth, watches, radar, notifications, admin):
        app.include_router(module.router)

    @app.get("/api/health")
    def health():
        with session_scope() as db:
            db.execute(text("SELECT 1"))
            beat = db.get(Heartbeat, "worker")
        online = bool(beat and utcnow() - beat.at < timedelta(seconds=90))
        return {"status": "ok", "worker": online}

    dist = get_settings().web_dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Rota não encontrada")
        index = dist / "index.html"
        if not index.is_file():
            return JSONResponse({"detail": "Interface não compilada"}, status_code=503)
        target = (dist / path).resolve()
        if path and target.is_relative_to(dist) and target.is_file():
            cache = (
                "public, max-age=31536000, immutable" if path.startswith("assets/")
                else "no-cache"
            )
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
