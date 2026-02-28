"""
Elastic DCA Cloud — Phase 1 FastAPI Application.

This is the main entry point. Sets up:
  - Lifespan: DB init + state loading on startup, DB close on shutdown
  - Routes: master-tick + admin endpoints
  - Logging

Blueprint reference:
  - Phase 1: "Server: FastAPI app with POST /api/master-tick, in-memory tier state
    loaded from PostgreSQL on startup, virtual grid execution engine, state
    persistence to DB on every change, GET /api/admin/tiers/{id}/grids for testing."
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_db, init_db
from app.routes.admin import router as admin_router
from app.routes.master import router as master_router
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
    logger.info("  Elastic DCA Cloud — Phase 1 Server Starting")
    logger.info("═" * 60)

    await init_db()
    await load_state_from_db()

    logger.info("Server ready. Waiting for Master EA ticks …")
    logger.info("═" * 60)
    yield

    logger.info("Shutting down …")
    await close_db()


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Elastic DCA Cloud",
    version="4.0.0-phase1",
    description="Phase 1: Core Backend + Master EA integration",
    lifespan=lifespan,
)

app.include_router(master_router)
app.include_router(admin_router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "4.0.0-phase1"}
