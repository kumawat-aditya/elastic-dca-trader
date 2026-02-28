"""
PostgreSQL database layer using asyncpg.

Handles:
  - Connection pool management
  - Schema initialization (DDL from Blueprint Section 9.3, 9.4, 9.6)
  - CRUD for tiers, tier_grids, market_state
  - State persistence (save/load in-memory tier state)

Blueprint references:
  - Section 9.3 : tiers table
  - Section 9.4 : tier_grids table (config JSONB + runtime JSONB)
  - Section 9.6 : market_state table
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import asyncpg

from app.config import settings
from app.models import (
    GRID_IDS,
    GridConfig,
    GridRow,
    GridRuntime,
    MarketState,
    Tier,
    TierState,
)

logger = logging.getLogger("elastic_dca.db")

# ── Module-level pool reference ──────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def init_db() -> None:
    """Create the connection pool and ensure schema exists."""
    global _pool
    logger.info("Connecting to PostgreSQL …")
    _pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=2, max_size=10)
    async with _pool.acquire() as conn:
        await _create_schema(conn)
    logger.info("Database ready.")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")


# ── Schema DDL ───────────────────────────────────────────────────────────────

async def _create_schema(conn: asyncpg.Connection) -> None:
    """Create tables if they don't exist (idempotent)."""

    # Section 9.3 — tiers
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tiers (
            id              SERIAL PRIMARY KEY,
            name            VARCHAR(50) NOT NULL UNIQUE,
            symbol          VARCHAR(20) DEFAULT 'XAUUSD',
            min_balance     DECIMAL(15,2) NOT NULL,
            max_balance     DECIMAL(15,2) NOT NULL,
            is_active       BOOLEAN DEFAULT TRUE,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Section 9.4 — tier_grids
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS tier_grids (
            id              SERIAL PRIMARY KEY,
            tier_id         INTEGER REFERENCES tiers(id) ON DELETE CASCADE,
            grid_id         VARCHAR(2) NOT NULL,

            config          JSONB NOT NULL DEFAULT '{}',
            runtime         JSONB NOT NULL DEFAULT '{}',

            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            UNIQUE(tier_id, grid_id)
        );
    """)
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_tier_grids_tier ON tier_grids(tier_id);
    """)

    # Section 9.6 — market_state
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS market_state (
            id              INTEGER PRIMARY KEY DEFAULT 1,
            symbol          VARCHAR(20) DEFAULT 'XAUUSD',
            ask             DECIMAL(15,5),
            bid             DECIMAL(15,5),
            mid             DECIMAL(15,5),
            contract_size   DECIMAL(10,2) DEFAULT 100,
            direction       VARCHAR(10) DEFAULT 'neutral',
            last_update     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Ensure the singleton market_state row exists
    await conn.execute("""
        INSERT INTO market_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
    """)

    logger.info("Schema verified / created.")


# ── Tier CRUD ────────────────────────────────────────────────────────────────

async def create_tier(name: str, min_balance: float, max_balance: float) -> Tier:
    """
    Insert a new tier and auto-create 4 empty grid records.
    Blueprint Section 11.4 — POST /api/admin/tiers
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check for overlapping ranges (Section 14.11)
        overlap = await conn.fetchrow("""
            SELECT id, name FROM tiers
            WHERE NOT ($1 >= max_balance OR $2 <= min_balance)
        """, min_balance, max_balance)
        if overlap:
            raise ValueError(
                f"Balance range [{min_balance}, {max_balance}) overlaps with "
                f"tier '{overlap['name']}' (id={overlap['id']})"
            )

        row = await conn.fetchrow("""
            INSERT INTO tiers (name, min_balance, max_balance)
            VALUES ($1, $2, $3)
            RETURNING id, name, symbol, min_balance, max_balance, is_active,
                      created_at::text, updated_at::text
        """, name, min_balance, max_balance)

        tier = _row_to_tier(row)

        # Auto-create 4 empty grids (Section 11.4)
        for grid_id in GRID_IDS:
            default_config = GridConfig(grid_id=grid_id).model_dump()
            default_runtime = GridRuntime(grid_id=grid_id).model_dump()
            await conn.execute("""
                INSERT INTO tier_grids (tier_id, grid_id, config, runtime)
                VALUES ($1, $2, $3::jsonb, $4::jsonb)
            """, tier.id, grid_id, json.dumps(default_config), json.dumps(default_runtime))

        return tier


async def get_all_tiers() -> list[Tier]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, symbol, min_balance, max_balance, is_active,
                   created_at::text, updated_at::text
            FROM tiers ORDER BY min_balance
        """)
        return [_row_to_tier(r) for r in rows]


async def get_tier(tier_id: int) -> Optional[Tier]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, symbol, min_balance, max_balance, is_active,
                   created_at::text, updated_at::text
            FROM tiers WHERE id = $1
        """, tier_id)
        return _row_to_tier(row) if row else None


async def update_tier(tier_id: int, **kwargs) -> Optional[Tier]:
    """Update tier metadata. Only provided fields are changed."""
    pool = await get_pool()
    allowed = {"name", "min_balance", "max_balance", "is_active"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return await get_tier(tier_id)

    # Overlap check if balance range changed
    if "min_balance" in updates or "max_balance" in updates:
        async with pool.acquire() as conn:
            current = await conn.fetchrow("SELECT min_balance, max_balance FROM tiers WHERE id = $1", tier_id)
            if not current:
                return None
            new_min = updates.get("min_balance", float(current["min_balance"]))
            new_max = updates.get("max_balance", float(current["max_balance"]))
            overlap = await conn.fetchrow("""
                SELECT id, name FROM tiers
                WHERE id != $1 AND NOT ($2 >= max_balance OR $3 <= min_balance)
            """, tier_id, new_min, new_max)
            if overlap:
                raise ValueError(
                    f"Balance range [{new_min}, {new_max}) overlaps with "
                    f"tier '{overlap['name']}' (id={overlap['id']})"
                )

    set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    set_clauses += f", updated_at = CURRENT_TIMESTAMP"
    values = [tier_id] + list(updates.values())

    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            UPDATE tiers SET {set_clauses}
            WHERE id = $1
            RETURNING id, name, symbol, min_balance, max_balance, is_active,
                      created_at::text, updated_at::text
        """, *values)
        return _row_to_tier(row) if row else None


async def delete_tier(tier_id: int) -> bool:
    """Delete tier. Only allowed if no active sessions (Section 11.4)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check for active sessions
        active = await conn.fetchval("""
            SELECT COUNT(*) FROM tier_grids
            WHERE tier_id = $1 AND (runtime->>'session_id') != ''
        """, tier_id)
        if active and active > 0:
            raise ValueError("Cannot delete tier with active sessions. Turn off all grids first.")

        result = await conn.execute("DELETE FROM tiers WHERE id = $1", tier_id)
        return result == "DELETE 1"


# ── Grid State Persistence ───────────────────────────────────────────────────

async def save_grid_state(tier_id: int, grid_id: str, config: GridConfig, runtime: GridRuntime) -> None:
    """Persist config + runtime JSONB to DB on every state change."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE tier_grids
            SET config = $1::jsonb, runtime = $2::jsonb, updated_at = CURRENT_TIMESTAMP
            WHERE tier_id = $3 AND grid_id = $4
        """, json.dumps(config.model_dump()), json.dumps(runtime.model_dump()), tier_id, grid_id)


async def load_all_tier_states() -> list[TierState]:
    """
    Load ALL tiers + their grid configs/runtimes from DB into memory.
    Called on server startup. Blueprint: "In-memory tier state loaded from PostgreSQL on startup."
    """
    pool = await get_pool()
    states: list[TierState] = []

    async with pool.acquire() as conn:
        tiers = await conn.fetch("""
            SELECT id, name, symbol, min_balance, max_balance, is_active,
                   created_at::text, updated_at::text
            FROM tiers ORDER BY min_balance
        """)

        for t in tiers:
            tier = _row_to_tier(t)
            configs: dict[str, GridConfig] = {}
            runtimes: dict[str, GridRuntime] = {}

            grids = await conn.fetch("""
                SELECT grid_id, config, runtime FROM tier_grids
                WHERE tier_id = $1
            """, tier.id)

            for g in grids:
                gid = g["grid_id"]
                cfg_data = json.loads(g["config"]) if isinstance(g["config"], str) else g["config"]
                rt_data = json.loads(g["runtime"]) if isinstance(g["runtime"], str) else g["runtime"]
                configs[gid] = GridConfig(**cfg_data)
                runtimes[gid] = GridRuntime(**rt_data)

            states.append(TierState(tier=tier, configs=configs, runtimes=runtimes))

    return states


# ── Market State Persistence ─────────────────────────────────────────────────

async def save_market_state(state: MarketState) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE market_state SET
                ask = $1, bid = $2, mid = $3, contract_size = $4,
                direction = $5, last_update = CURRENT_TIMESTAMP
            WHERE id = 1
        """, state.ask, state.bid, state.mid, state.contract_size, state.direction)


async def load_market_state() -> MarketState:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM market_state WHERE id = 1")
        if not row:
            return MarketState()
        return MarketState(
            symbol=row["symbol"] or "XAUUSD",
            ask=float(row["ask"] or 0),
            bid=float(row["bid"] or 0),
            mid=float(row["mid"] or 0),
            contract_size=float(row["contract_size"] or 100),
            direction=row["direction"] or "neutral",
            last_update=str(row["last_update"]) if row["last_update"] else None,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_tier(row: asyncpg.Record) -> Tier:
    return Tier(
        id=row["id"],
        name=row["name"],
        symbol=row["symbol"] or "XAUUSD",
        min_balance=float(row["min_balance"]),
        max_balance=float(row["max_balance"]),
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
