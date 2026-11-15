"""Hosted ASGI entry point: Postgres when DATABASE_URL is set, plus health checks.

Render starts this factory:

    uvicorn --factory server.asgi:serve --host 0.0.0.0 --port $PORT

`server.app` stays the application; this module owns deployment concerns only: backend
selection, environment overrides, and `/healthz` + `/readyz`. It does not duplicate or
edit application routes.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config as config_mod
from .app import UI, create_app
from .pg import open_database, readiness

log = logging.getLogger("vexo.asgi")


def _env_overrides() -> dict:
    """Map deployment env vars onto the application's config dataclasses."""
    overrides: dict = {}

    demo_mode = os.environ.get("VEXO_DEMO_MODE") or os.environ.get("DEMO_MODE")
    if demo_mode:
        overrides["demo_mode"] = demo_mode.strip()

    provider = os.environ.get("SCORER_PROVIDER")
    if provider:
        overrides.setdefault("scorer", {})["provider"] = provider.strip()

    model = os.environ.get("ANTHROPIC_MODEL")
    if model:
        overrides.setdefault("scorer", {})["claude_model"] = model.strip()

    db_path = os.environ.get("VEXO_DB_PATH")
    if db_path:
        overrides["db_path"] = db_path

    roster = os.environ.get("VEXO_ROSTER")
    if roster:
        overrides["roster"] = [int(part) for part in roster.replace(" ", "").split(",") if part]

    interval = os.environ.get("VEXO_WORKER_INTERVAL_S")
    if interval:
        overrides["worker_interval_s"] = float(interval)

    return overrides


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def create_serving_app() -> FastAPI:
    cfg = config_mod.load(**_env_overrides())
    db = open_database(cfg.db_path)
    backend = getattr(db, "backend", "sqlite")

    # The application mounts ui/ at import time. Creating the directory keeps the service
    # bootable while the UI files are still being added; /phone and /operator return 404
    # until they exist, which readiness deliberately does not treat as a failure.
    UI.mkdir(parents=True, exist_ok=True)

    app = create_app(cfg=cfg, db=db, start_worker=True)
    existing = {getattr(route, "path", None) for route in app.routes}

    # Restart reconciliation before serving traffic: expire stale deadlines, lighting
    # leases and jobs so an old command cannot replay a colour after a deploy or wake.
    try:
        app.state.engine.sweep()
    except Exception:
        log.exception("startup reconciliation failed; the worker will keep retrying")

    # Same-origin production needs no CORS. Replit preview or any separate frontend origin
    # must be listed explicitly; never combine a wildcard with credentials.
    origins = _cors_origins()
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        )

    if "/healthz" not in existing:
        @app.get("/healthz")
        def healthz():
            return {"status": "ok"}

    if "/readyz" not in existing:
        @app.get("/readyz")
        def readyz():
            ok, detail = readiness(db)
            return JSONResponse(detail, status_code=200 if ok else 503)

    def _close_db() -> None:
        close = getattr(db, "close", None)
        if callable(close):
            close()

    # Compose with the application's own lifespan (worker startup/shutdown) instead of
    # replacing it. Older FastAPI exposed add_event_handler; current versions do not.
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan_with_close(inner_app):
        async with previous_lifespan(inner_app):
            try:
                yield
            finally:
                _close_db()

    app.router.lifespan_context = lifespan_with_close
    app.state.backend = backend

    log.info("serving app env=%s demo_mode=%s backend=%s scorer=%s",
             os.environ.get("APP_ENV", "local"), cfg.demo_mode, backend, cfg.scorer.provider)
    return app


def serve() -> FastAPI:
    """Uvicorn factory: `uvicorn --factory server.asgi:serve`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    return create_serving_app()
