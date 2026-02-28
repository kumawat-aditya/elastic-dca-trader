# Phase 1 — Implementation Document

**Project:** Elastic DCA Trading SaaS  
**Blueprint:** `docs/saas_blueprint_v4.md`  
**Phase:** 1 — Core Backend + Master EA  
**Total Source:** ~1,576 lines across 12 files + 1 MQL5 script

---

## 1. Architecture Overview

Phase 1 implements the **server backbone** and **Master EA data feeder**. There is no client dashboard, no user authentication (JWT), and no WebSocket sync — those are Phase 2–4.

```
┌─────────────────┐       HTTP POST         ┌──────────────────────┐
│  Master EA      │  ───────────────────▶   │  FastAPI Server      │
│  (MetaTrader 5) │   /api/master-tick      │  apps/server/        │
│  scripts/       │   {ask,bid,contract_size}│                      │
│  MasterEA_v4.mq5│   X-Admin-Key header    │  ┌────────────────┐  │
└─────────────────┘                         │  │  Virtual Engine │  │
                                            │  │  (engine.py)    │  │
       ┌─────────────┐   Admin REST API     │  └────────┬───────┘  │
       │  Admin       │  ◀──────────────▶   │           │          │
       │  (curl/      │   /api/admin/*      │  ┌────────▼───────┐  │
       │   Postman)   │                     │  │  In-Memory      │  │
       └─────────────┘                      │  │  State          │  │
                                            │  │  (state.py)     │  │
                                            │  └────────┬───────┘  │
                                            │           │          │
                                            │  ┌────────▼───────┐  │
                                            │  │  PostgreSQL     │  │
                                            │  │  (database.py)  │  │
                                            │  └────────────────┘  │
                                            └──────────────────────┘
```

---

## 2. File-by-File Breakdown

### 2.1 `apps/server/main.py` (71 lines)

**Blueprint ref:** Section 14.1 (Crash Recovery)

- FastAPI app with **lifespan** context manager
- On startup: initializes database connection pool, creates schema tables, loads all tier states and market state from PostgreSQL into memory
- On shutdown: closes database pool
- Includes `master_router` and `admin_router`
- Health endpoint: `GET /health` → `{"status": "ok", "version": "4.0.0-phase1"}`
- Structured logging with format: `timestamp | logger_name | level | message`

### 2.2 `apps/server/app/config.py` (28 lines)

**Blueprint ref:** Phase 1 server configuration

- Loads settings from `.env` using `python-dotenv`
- Settings: `DATABASE_URL`, `ADMIN_KEY`, `HOST`, `PORT`
- Singleton `settings` instance exported

### 2.3 `apps/server/app/models.py` (142 lines)

**Blueprint ref:** Sections 4, 5, 9

All Pydantic v2 `BaseModel` classes:

| Model                     | Fields                                                                  | Purpose                         |
| ------------------------- | ----------------------------------------------------------------------- | ------------------------------- |
| `GridRow`                 | index, dollar, lots, alert, executed, entry_price, executed_at          | Single grid row (virtual order) |
| `GridConfig`              | grid_id, on, cyclic, start_limit, end_limit, tp_type, tp_value, rows    | Grid admin configuration        |
| `GridRuntime`             | grid_id, session_id, is_active, waiting_limit, start_ref, last_order_ts | Grid session runtime state      |
| `Tier`                    | id, name, symbol, min/max_balance, is_active, created_at, updated_at    | Balance-range tier              |
| `MarketState`             | symbol, ask, bid, mid, contract_size, direction, last_update            | Current market snapshot         |
| `TierState`               | tier, configs (dict), runtimes (dict)                                   | Aggregated tier + all 4 grids   |
| `MasterTickRequest`       | ask, bid, contract_size                                                 | Master EA payload               |
| `CreateTierRequest`       | name, symbol, min_balance, max_balance                                  | Admin create tier               |
| `UpdateTierRequest`       | name?, symbol?, min_balance?, max_balance?, is_active?                  | Admin update tier               |
| `GridRowInput`            | index, dollar, lots, alert                                              | Admin row configuration         |
| `UpdateGridConfigRequest` | start_limit?, end_limit?, tp_type?, tp_value?, rows?                    | Admin grid update               |
| `GridControlRequest`      | on, cyclic?                                                             | Admin ON/OFF control            |

Constant: `GRID_IDS = ["B1", "B2", "S1", "S2"]`

### 2.4 `apps/server/app/engine.py` (335 lines)

**Blueprint ref:** Sections 5, 6, 7, 14

The core virtual execution engine. Key functions:

#### `generate_session_id(grid_id)` → `"{GRID_ID}_{8_hex}"` (Section 6.1)

- Format: `B1_a1b2c3d4` using `uuid4().hex[:8]`

#### `calculate_virtual_pnl(config, bid, ask, contract_size)` → float (Section 7.5)

- BUY: `Σ (bid − entry_price) × lots × contract_size` for all executed rows
- SELL: `Σ (entry_price − ask) × lots × contract_size` for all executed rows

#### `check_tp(config, tier_ref_balance, virtual_pnl)` → bool (Section 7.6)

- `fixed_money`: target = `tp_value`
- `equity_pct` / `balance_pct`: target = `tier_ref_balance × (tp_value / 100)`
- Returns `True` if `virtual_pnl >= target`

#### `activate_grid(config, runtime, current_ask, current_bid)` (Section 6.3)

1. Generate new session_id
2. Reset all rows (executed=False, entry_price=0, executed_at="")
3. If `start_limit > 0` and price hasn't reached it → `waiting_limit = True`
4. Else → set `start_ref` to current ask (buy) or bid (sell), execute Row 0

#### `close_session(config, runtime, ask, bid, reason)` (Section 6.4)

- **Cyclic ON:** Immediately calls `activate_grid()` → new session starts
- **Cyclic OFF:** Sets `on=False`, clears session/runtime

#### `process_tick(tier_state, market)` → async (Section 7.7)

- Acquires per-tier `asyncio.Lock` (Section 14.13)
- Delegates to `_process_tick_sync()`

#### `_process_tick_sync(tier_state, market)` → bool (Section 7.7)

5-phase tick processing for each of the 4 grids:

| Phase         | Section  | Logic                                                                                                                         |
| ------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 1. Limit Wait | 7.3      | If waiting, check if ask/bid hit start_limit. If yes → activate, execute Row 0, **skip to next grid** (one-row-per-tick rule) |
| 2. P&L Update | 7.5      | Calculate virtual P&L across all executed rows                                                                                |
| 3. TP Check   | 7.6      | If P&L ≥ target → close session (cyclic restart or off)                                                                       |
| 4. End Limit  | 7.4      | If ask < end_limit (buy) → block expansion (don't close)                                                                      |
| 5. Expansion  | 7.1, 7.2 | Find next un-executed row, check `cumulative_gap`, execute if target met. **One row per tick per grid.**                      |

### 2.5 `apps/server/app/state.py` (102 lines)

**Blueprint ref:** Phase 1 state management

Global in-memory state:

- `tier_states: dict[int, TierState]` — keyed by tier ID
- `market: MarketState` — singleton, shared across all modules

Key functions:

- `load_state_from_db()` — Startup loader. **Mutates** the existing `market` object (never reassigns) to preserve cross-module references.
- `update_market(ask, bid, contract_size)` — Mutates market, calculates direction (up/down/neutral), persists to DB
- `persist_grid(tier_id, grid_id)` — Saves single grid config+runtime to DB
- `add_tier_state()`, `remove_tier_state()`, `get_tier_state()` — Dict mutations

### 2.6 `apps/server/app/database.py` (337 lines)

**Blueprint ref:** Section 9

asyncpg-based PostgreSQL layer:

**Schema (auto-created on startup):**

```sql
-- Section 9.3
CREATE TABLE tiers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'XAUUSD',
    min_balance DOUBLE PRECISION NOT NULL,
    max_balance DOUBLE PRECISION NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Section 9.4
CREATE TABLE tier_grids (
    id SERIAL PRIMARY KEY,
    tier_id INTEGER NOT NULL REFERENCES tiers(id) ON DELETE CASCADE,
    grid_id TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}',
    runtime JSONB NOT NULL DEFAULT '{}',
    UNIQUE(tier_id, grid_id)
);
CREATE INDEX idx_tier_grids_tier ON tier_grids(tier_id);

-- Section 9.6
CREATE TABLE market_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    data JSONB NOT NULL DEFAULT '{}'
);
```

**CRUD operations:**

- `create_tier()` — With overlap validation (Section 14.11): checks `NOT (new.max <= existing.min OR new.min >= existing.max)`
- `get_all_tiers()`, `get_tier()`, `update_tier()`, `delete_tier()`
- `save_grid_state()` — Upserts config+runtime JSONB
- `load_all_tier_states()` — Joins tiers + tier_grids, reconstructs TierState objects
- `save_market_state()` / `load_market_state()` — Singleton row upsert/load

### 2.7 `apps/server/app/dependencies.py` (18 lines)

**Blueprint ref:** Section 11.4 (Phase 1 simplified auth)

- `verify_admin_key()` — FastAPI dependency that checks `X-Admin-Key` header against `settings.ADMIN_KEY`
- Returns 401 if missing/invalid
- JWT auth deferred to Phase 2

### 2.8 `apps/server/app/routes/master.py` (52 lines)

**Blueprint ref:** Section 11.1

`POST /api/master-tick`

- Auth: `X-Admin-Key` header required
- Request: `{ ask, bid, contract_size }`
- Updates global market state
- Processes all tiers through the virtual engine
- Persists changed grid states to DB
- Response: `{ status: "ok" }`

### 2.9 `apps/server/app/routes/admin.py` (335 lines)

**Blueprint ref:** Sections 11.2, 11.3

All endpoints require `X-Admin-Key` header.

| Method   | Path                                                 | Description                                            | Blueprint     |
| -------- | ---------------------------------------------------- | ------------------------------------------------------ | ------------- |
| `GET`    | `/api/admin/tiers`                                   | List all tiers                                         | §11.2         |
| `POST`   | `/api/admin/tiers`                                   | Create tier + auto-create 4 grids. Overlap validation. | §11.2, §14.11 |
| `PUT`    | `/api/admin/tiers/{tier_id}`                         | Update tier metadata                                   | §11.2         |
| `DELETE` | `/api/admin/tiers/{tier_id}`                         | Delete tier (only if no active sessions)               | §11.2         |
| `GET`    | `/api/admin/tiers/{tier_id}/grids`                   | Full grid state (config + runtime + market)            | §11.3         |
| `PUT`    | `/api/admin/tiers/{tier_id}/grids/{grid_id}/config`  | Update grid config with merge logic                    | §11.3, §14.7  |
| `POST`   | `/api/admin/tiers/{tier_id}/grids/{grid_id}/control` | ON/OFF + cyclic toggle                                 | §11.3         |
| `GET`    | `/api/admin/market`                                  | Current market state                                   | §11.3         |

**Grid config merge logic (Section 14.7):**

- Executed rows: dollar/lots locked, only `alert` editable
- Executed rows cannot be removed — auto-reinjected if omitted
- Non-executed rows: fully editable or removable
- Row 0 `dollar` forced to 0 (Section 5.5)
- Max 100 rows validated (Section 5.4)
- Sequential index validation (0,1,2,...N-1)

### 2.10 `scripts/MasterEA_v4.mq5` (154 lines)

**Blueprint ref:** Section 3.1

MQL5 Expert Advisor for MetaTrader 5:

- **Inputs:** `InpServerURL` (server URL), `InpAdminKey` (admin key), `InpTimeout` (HTTP timeout)
- Sends `{ask, bid, contract_size}` every 1 second via `OnTimer() + EventSetTimer(1)`
- HTTP POST to `/api/master-tick` with `X-Admin-Key` header and JSON body
- `contract_size` from `SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE)`
- Error logging every 20 consecutive failures
- Does NOT execute trades, does NOT send account data

---

## 3. Blueprint Compliance Summary

### Fully Implemented (Pass)

- ✅ Master EA data feed protocol (Section 3.1)
- ✅ Tier system with overlap validation (Section 4, 14.11)
- ✅ 4-Grid engine with B1/B2/S1/S2 (Section 5)
- ✅ Session lifecycle: activate → execute → TP → close/restart (Section 6)
- ✅ 5-phase tick processing (Section 7.7)
- ✅ Start limit (waiting mode) (Section 7.3)
- ✅ End limit (expansion blocking) (Section 7.4)
- ✅ Virtual P&L calculation (Section 7.5)
- ✅ Take profit (fixed_money, equity_pct, balance_pct) (Section 7.6)
- ✅ Cyclic ON: auto-restart on TP (Section 6.5)
- ✅ Cyclic OFF: grid turns off on TP (Section 6.4)
- ✅ Sequential row execution (one row per tick per grid) (Section 7.2)
- ✅ Database schema (tiers, tier_grids, market_state) (Section 9)
- ✅ State persistence on every change (Phase 1 requirement)
- ✅ Crash recovery via DB reload on startup (Section 14.1)
- ✅ Per-tier asyncio.Lock (Section 14.13)
- ✅ Grid config merge with executed row protection (Section 14.7)
- ✅ All REST API endpoints (Section 11)
- ✅ Admin auth via X-Admin-Key (Phase 1 scope)

### Known Deviations (Intentional for Phase 1)

- `server_time` not included in Master EA payload (blueprint Section 3.1 example vs Section 11.1 formal spec — server uses own timestamp)
- Per-row `virtual_pnl` not computed (needed for Phase 4 dashboard)
- Admin auth uses X-Admin-Key, not JWT (JWT is Phase 2)

---

## 4. Bugs Fixed During Implementation

| Bug                                          | Description                                                                                                                                                                          | Fix                                                                            |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| **Market state propagation**                 | `load_state_from_db()` reassigned module-level `market` object, breaking cross-module `from app.state import market` references. Admin routes/engine saw stale (zeroed) market data. | Changed to mutate existing object instead of reassigning.                      |
| **Double row execution on limit activation** | When start_limit triggered, code fell through to Phase 5 (expansion), potentially executing Row 1 on the same tick as Row 0.                                                         | Added `continue` after limit activation to skip Phases 2–5 on activation tick. |
| **Executed row deletion**                    | Admin could accidentally drop executed rows by omitting them in config update payload.                                                                                               | Auto-reinject any omitted executed rows after merge.                           |

---

## 5. Dependencies

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
asyncpg>=0.30.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

Python 3.12+ required. PostgreSQL 15+ recommended (tested with 16).
