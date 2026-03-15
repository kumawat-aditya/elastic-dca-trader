"""
PostgreSQL database layer using asyncpg.

Handles:
  - Connection pool management
  - Schema initialization (DDL from Blueprint Section 9.1–9.6)
  - CRUD for tiers, tier_grids, market_state (Phase 1)
  - CRUD for users, subscriptions, user_snapshots (Phase 2)
  - State persistence (save/load in-memory tier state)

Blueprint references:
  - Section 9.1 : users table
  - Section 9.2 : subscriptions table
  - Section 9.3 : tiers table
  - Section 9.4 : tier_grids table (config JSONB + runtime JSONB)
  - Section 9.5 : user_snapshots table
  - Section 9.6 : market_state table
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import asyncpg

from app.config import settings
from app.models import (
    GRID_IDS,
    GridConfig,
    GridRow,
    GridRuntime,
    MarketState,
    Position,
    Subscription,
    Tier,
    TierState,
    User,
    UserSnapshot,
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

    # ── Phase 2 Tables ───────────────────────────────────────────────────────

    # Section 9.1 — users
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              SERIAL PRIMARY KEY,
            email           VARCHAR(255) UNIQUE NOT NULL,
            password_hash   VARCHAR(255) NOT NULL,
            name            VARCHAR(100) NOT NULL,
            phone           VARCHAR(20),
            mt5_id          VARCHAR(50) UNIQUE,
            assigned_tier_id INTEGER REFERENCES tiers(id),
            role            VARCHAR(20) DEFAULT 'client',
            status          VARCHAR(20) DEFAULT 'pending',
            email_verified  BOOLEAN DEFAULT FALSE,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_mt5_id ON users(mt5_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);")

    # Section 9.2 — subscriptions
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id              SERIAL PRIMARY KEY,
            user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
            plan_name       VARCHAR(50) NOT NULL,
            status          VARCHAR(20) DEFAULT 'active',
            paypal_sub_id   VARCHAR(100),
            start_date      TIMESTAMP NOT NULL,
            end_date        TIMESTAMP NOT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);")
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_end_date ON subscriptions(end_date);")

    # Section 9.5 — user_snapshots (Phase 3 prep)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS user_snapshots (
            user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            equity          DECIMAL(15,2),
            balance         DECIMAL(15,2),
            positions       JSONB DEFAULT '[]',
            last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
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


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — User CRUD (Section 9.1)
# ═══════════════════════════════════════════════════════════════════════════════

async def create_user(email: str, password_hash: str, name: str, phone: str | None = None) -> User:
    """Insert a new user with status='pending', email_verified=False."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check for duplicate email
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", email)
        if existing:
            raise ValueError("Email already registered")

        row = await conn.fetchrow("""
            INSERT INTO users (email, password_hash, name, phone)
            VALUES ($1, $2, $3, $4)
            RETURNING id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                      role, status, email_verified, created_at::text, updated_at::text
        """, email, password_hash, name, phone)
        return _row_to_user(row)


async def get_user_by_email(email: str) -> User | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                   role, status, email_verified, created_at::text, updated_at::text
            FROM users WHERE email = $1
        """, email)
        return _row_to_user(row) if row else None


async def get_user_by_id(user_id: int) -> User | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                   role, status, email_verified, created_at::text, updated_at::text
            FROM users WHERE id = $1
        """, user_id)
        return _row_to_user(row) if row else None


async def get_all_users() -> list[User]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                   role, status, email_verified, created_at::text, updated_at::text
            FROM users ORDER BY id
        """)
        return [_row_to_user(r) for r in rows]


async def update_user(user_id: int, **kwargs) -> User | None:
    """Update user fields. Only provided (non-None) fields are changed."""
    pool = await get_pool()
    allowed = {"email", "name", "phone", "mt5_id", "status", "password_hash",
               "email_verified", "assigned_tier_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return await get_user_by_id(user_id)

    # MT5 ID uniqueness check
    if "mt5_id" in updates and updates["mt5_id"]:
        async with pool.acquire() as conn:
            conflict = await conn.fetchrow(
                "SELECT id FROM users WHERE mt5_id = $1 AND id != $2",
                updates["mt5_id"], user_id,
            )
            if conflict:
                raise ValueError("MT5 ID already claimed by another user")

    set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates))
    set_clauses += ", updated_at = CURRENT_TIMESTAMP"
    values = [user_id] + list(updates.values())

    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            UPDATE users SET {set_clauses}
            WHERE id = $1
            RETURNING id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                      role, status, email_verified, created_at::text, updated_at::text
        """, *values)
        return _row_to_user(row) if row else None


async def verify_user_email(user_id: int) -> User | None:
    """Mark user email as verified and set status to 'active'."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE users SET email_verified = TRUE, status = 'active',
                             updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            RETURNING id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                      role, status, email_verified, created_at::text, updated_at::text
        """, user_id)
        return _row_to_user(row) if row else None


def _row_to_user(row: asyncpg.Record) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        phone=row["phone"],
        mt5_id=row["mt5_id"],
        assigned_tier_id=row["assigned_tier_id"],
        role=row["role"],
        status=row["status"],
        email_verified=row["email_verified"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — Subscription CRUD (Section 9.2)
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_dt(val: str) -> datetime:
    """Parse an ISO 8601 date/datetime string into a naive datetime for asyncpg."""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    # fromisoformat handles timezone offsets; strip tzinfo for naive datetime
    dt = datetime.fromisoformat(val)
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt

async def create_subscription(user_id: int, plan_name: str,
                               start_date: str, end_date: str) -> Subscription:
    """Admin manually creates a subscription (Phase 2: no PayPal yet)."""
    pool = await get_pool()
    sd = _parse_dt(start_date)
    ed = _parse_dt(end_date)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO subscriptions (user_id, plan_name, start_date, end_date)
            VALUES ($1, $2, $3, $4)
            RETURNING id, user_id, plan_name, status, paypal_sub_id,
                      start_date::text, end_date::text, created_at::text
        """, user_id, plan_name, sd, ed)
        return _row_to_subscription(row)


async def get_subscription_by_user(user_id: int) -> Subscription | None:
    """Get the latest active subscription for a user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, user_id, plan_name, status, paypal_sub_id,
                   start_date::text, end_date::text, created_at::text
            FROM subscriptions
            WHERE user_id = $1
            ORDER BY end_date DESC
            LIMIT 1
        """, user_id)
        return _row_to_subscription(row) if row else None


async def update_subscription(sub_id: int, **kwargs) -> Subscription | None:
    """Update subscription fields."""
    pool = await get_pool()
    allowed = {"plan_name", "status", "end_date", "start_date", "paypal_sub_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return None

    # Convert date strings to datetime objects for asyncpg
    for dk in ("end_date", "start_date"):
        if dk in updates and isinstance(updates[dk], str):
            updates[dk] = _parse_dt(updates[dk])

    set_parts = []
    values = [sub_id]
    for i, (k, v) in enumerate(updates.items()):
        set_parts.append(f"{k} = ${i+2}")
        values.append(v)

    set_clause = ", ".join(set_parts)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"""
            UPDATE subscriptions SET {set_clause}
            WHERE id = $1
            RETURNING id, user_id, plan_name, status, paypal_sub_id,
                      start_date::text, end_date::text, created_at::text
        """, *values)
        return _row_to_subscription(row) if row else None


async def upsert_subscription(user_id: int, plan_name: str,
                               start_date: str, end_date: str) -> Subscription:
    """Create or update subscription for a user (admin manages manually)."""
    existing = await get_subscription_by_user(user_id)
    if existing:
        updated = await update_subscription(
            existing.id, plan_name=plan_name,
            start_date=start_date, end_date=end_date, status="active",
        )
        return updated or existing
    return await create_subscription(user_id, plan_name, start_date, end_date)


async def is_subscription_active(user_id: int) -> bool:
    """
    Section 10.4: Check if user has an active subscription.
    Active = status=='active' AND end_date > now().
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id FROM subscriptions
            WHERE user_id = $1 AND status = 'active' AND end_date > CURRENT_TIMESTAMP
            LIMIT 1
        """, user_id)
        return row is not None


def _row_to_subscription(row: asyncpg.Record) -> Subscription:
    return Subscription(
        id=row["id"],
        user_id=row["user_id"],
        plan_name=row["plan_name"],
        status=row["status"],
        paypal_sub_id=row["paypal_sub_id"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        created_at=row["created_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — User Snapshots & Tier Client Queries (Section 8, 9.5, 11.4)
# ═══════════════════════════════════════════════════════════════════════════════

async def get_user_by_mt5_id(mt5_id: str) -> User | None:
    """Look up a user by MT5 account ID (Section 8.2: auth flow first step)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, email, password_hash, name, phone, mt5_id, assigned_tier_id,
                   role, status, email_verified, created_at::text, updated_at::text
            FROM users WHERE mt5_id = $1
        """, mt5_id)
        return _row_to_user(row) if row else None


async def upsert_user_snapshot(user_id: int, balance: float,
                                positions: list) -> None:
    """
    Save/update client EA snapshot on every ping (Section 8.2, 9.5).
    Stores balance, positions JSONB, and updates last_seen timestamp.
    """
    pool = await get_pool()
    positions_json = json.dumps(positions)
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_snapshots (user_id, balance, positions, last_seen)
            VALUES ($1, $2, $3::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id)
            DO UPDATE SET balance = $2, positions = $3::jsonb,
                          last_seen = CURRENT_TIMESTAMP
        """, user_id, balance, positions_json)


async def get_user_snapshot(user_id: int) -> UserSnapshot | None:
    """Get the latest snapshot for a user (dashboard, admin views)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT user_id, equity, balance, positions, last_seen::text
            FROM user_snapshots WHERE user_id = $1
        """, user_id)
        if not row:
            return None
        positions_data = row["positions"]
        if isinstance(positions_data, str):
            positions_data = json.loads(positions_data)
        return UserSnapshot(
            user_id=row["user_id"],
            equity=float(row["equity"]) if row["equity"] is not None else None,
            balance=float(row["balance"]) if row["balance"] is not None else None,
            positions=positions_data or [],
            last_seen=row["last_seen"],
        )


async def get_clients_by_tier(tier_id: int) -> list[dict]:
    """
    Get all users assigned to a tier with their latest snapshot data.
    Section 11.4: GET /api/admin/tiers/{tier_id}/clients
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id, u.name, u.mt5_id,
                   s.balance, s.positions, s.last_seen
            FROM users u
            LEFT JOIN user_snapshots s ON u.id = s.user_id
            WHERE u.assigned_tier_id = $1 AND u.status = 'active'
            ORDER BY u.id
        """, tier_id)

        clients = []
        for r in rows:
            positions_data = r["positions"]
            if isinstance(positions_data, str):
                positions_data = json.loads(positions_data)
            position_count = len(positions_data) if positions_data else 0
            # Connected: last_seen within 10 seconds (Section 11.4)
            connected = False
            if r["last_seen"]:
                from datetime import datetime, timezone
                try:
                    last = r["last_seen"]
                    if isinstance(last, datetime):
                        if last.tzinfo is None:
                            last = last.replace(tzinfo=timezone.utc)
                        connected = (datetime.now(timezone.utc) - last).total_seconds() < 10
                except Exception:
                    pass
            clients.append({
                "user_id": r["id"],
                "name": r["name"],
                "mt5_id": r["mt5_id"],
                "balance": float(r["balance"]) if r["balance"] is not None else None,
                "last_seen": str(r["last_seen"]) if r["last_seen"] else None,
                "connected": connected,
                "position_count": position_count,
            })
        return clients


async def update_user_tier(user_id: int, tier_id: int | None) -> None:
    """Update user's assigned_tier_id (Section 8.3: tier assignment)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET assigned_tier_id = $1, updated_at = CURRENT_TIMESTAMP
            WHERE id = $2
        """, tier_id, user_id)
