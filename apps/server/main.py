"""
Elastic DCA Cloud — Phase 3 FastAPI Application.

This is the main entry point. Sets up:
  - Lifespan: DB init + state loading on startup, DB close on shutdown
  - Routes: master-tick + admin + auth + client + client-ping endpoints
  - Logging

Blueprint reference:
  - Phase 1: "Server: FastAPI app with POST /api/master-tick, in-memory tier state
    loaded from PostgreSQL on startup, virtual grid execution engine, state
    persistence to DB on every change, GET /api/admin/tiers/{id}/grids for testing."
  - Phase 2: "Login system for admin and clients. JWT auth, user management."
  - Phase 3: "Client EA sync protocol. POST /api/client-ping, dashboard, tier
    client management."
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_db, init_db
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.client import router as client_router
from app.routes.master import router as master_router
from app.routes.ping import router as ping_router
from app.state import load_state_from_db

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-5s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("elastic_dca")


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect DB + load state. Shutdown: close DB."""
    logger.info("═" * 60)
    logger.info("  Elastic DCA Cloud — Phase 3 Server Starting")
    logger.info("═" * 60)

    await init_db()
    await load_state_from_db()

    logger.info("Server ready. Auth + User management + Client sync enabled.")
    logger.info("═" * 60)
    yield

    logger.info("Shutting down …")
    await close_db()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Elastic DCA Cloud",
    version="4.0.0-phase3",
    description="Phase 3: Client EA Sync Protocol + Dashboard",
    lifespan=lifespan,
)

app.include_router(master_router)      # POST /api/master-tick (X-Admin-Key auth)
app.include_router(auth_router)        # POST /api/auth/* (no auth required)
app.include_router(admin_router)       # /api/admin/* (JWT role='admin')
app.include_router(client_router)      # /api/client/* (JWT role='client')
app.include_router(ping_router)        # POST /api/client-ping (no header auth, mt5_id based)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "4.0.0-phase3"}


if __name__ == "__main__":
    import uvicorn
    from app.config import settings
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
