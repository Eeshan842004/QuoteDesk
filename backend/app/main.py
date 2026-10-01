"""FastAPI application.

    cd backend && uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import REPO_ROOT, get_settings

if str(REPO_ROOT) not in sys.path:  # `datagen` (bundle builder) is imported by the retrain orchestrator
    sys.path.insert(0, str(REPO_ROOT))

from .api import admin, misc, quotes  # noqa: E402
from .api.deps import limiter  # noqa: E402
from .db import get_state, init_db, session_scope  # noqa: E402
from .models import get_registry  # noqa: E402
from .retrain.orchestrator import seed_initial_version  # noqa: E402
from .tools import get_catalog  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("quotedesk")


def load_live_student(block: bool = False) -> None:
    """Load the live version (DB state if promoted/rolled back, else env) in the background."""
    s = get_settings()
    target = None
    try:
        with session_scope() as db:
            target = get_state(db, "live_version")
    except Exception:
        log.exception("could not read live version")
    repo = (target or {}).get("repo") or s.hf_model_repo
    rev = (target or {}).get("revision") or s.student_adapter_revision
    if not (s.student_local_adapter or (repo and rev)):
        log.info("student disabled (no adapter configured): teacher-only mode")
        return
    job = lambda: get_registry().load(repo, rev, local_path=s.student_local_adapter)  # noqa: E731
    if block:
        job()
    else:
        threading.Thread(target=job, daemon=True, name="student-load").start()


def ensure_live_version() -> None:
    """If a model was preloaded (e.g. Modal snapshot) but the DB says another version is live (promotion or
    rollback happened after deploy), hot-swap to the DB's version in the background."""
    reg = get_registry()
    if reg.state != "ready":
        return
    try:
        with session_scope() as db:
            target = get_state(db, "live_version")
    except Exception:
        return
    if target and target.get("revision") and target.get("revision") != reg.version:
        threading.Thread(target=reg.load, args=(target.get("repo"), target.get("revision")), daemon=True).start()


def create_app(load_student: bool | None = None, with_mcp: bool = True) -> FastAPI:
    s = get_settings()
    mcp_app = None
    if with_mcp:
        try:
            from .mcp_server import mcp, mcp_asgi_app
            mcp_app = mcp_asgi_app()
        except Exception:  # MCP is optional (v1.2)
            log.exception("MCP server disabled")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        get_catalog()
        with session_scope() as db:
            seed_initial_version(db)
        if load_student if load_student is not None else s.load_student_on_startup:
            load_live_student()
        else:
            ensure_live_version()
        if mcp_app is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield

    app = FastAPI(title="QuoteDesk API", version="1.0.0", lifespan=lifespan,
                  description="Messy customer emails to draft quotes. Demo with synthetic data and a fictional company.")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(CORSMiddleware, allow_origins=s.allowed_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])
    app.include_router(misc.router)
    app.include_router(quotes.router)
    app.include_router(admin.router)
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

    @app.get("/")
    def root():
        return {"service": "QuoteDesk API", "docs": "/docs", "health": "/api/health", "mcp": "/mcp/",
                "notice": "Demo with synthetic data and a fictional company."}

    return app


app = create_app()
