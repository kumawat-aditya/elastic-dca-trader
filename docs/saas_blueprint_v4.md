# Elastic DCA Cloud — SaaS Platform Blueprint v4

**Document Version:** 4.0  
**Date:** 2026-03-01  
**Status:** Comprehensive Technical Blueprint  
**Market Focus:** XAUUSD (Gold) Only  
**Architecture:** Master-Slave Grid Trading via Centralized Python Server

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Component Specifications](#3-component-specifications)
4. [The Balance Tier System](#4-the-balance-tier-system)
5. [The 4-Grid Engine](#5-the-4-grid-engine)
6. [Session Management](#6-session-management)
7. [Virtual Execution Engine (Master Logic)](#7-virtual-execution-engine-master-logic)
8. [Client Sync Protocol (Slave Logic)](#8-client-sync-protocol-slave-logic)
9. [Database Schema](#9-database-schema)
10. [Authentication & Subscription](#10-authentication--subscription)
11. [API Reference](#11-api-reference)
12. [Admin Dashboard](#12-admin-dashboard)
13. [Client Dashboard](#13-client-dashboard)
14. [Edge Cases & Error Handling](#14-edge-cases--error-handling)
15. [Development Phases](#15-development-phases)
16. [Cross-Check & Validation Matrix](#16-cross-check--validation-matrix)

---

## 1. Executive Summary

We are building a subscription-based SaaS platform that allows a single Admin to manage algorithmic Gold (XAUUSD) trading for hundreds of client accounts simultaneously.

**Key Principles:**

- **The Admin** does NOT trade on their own account. They manage a "Virtual Grid" — a signal engine that tracks market data and marks execution levels.
- **The Server** is the central brain. It receives price feeds from a Master EA, calculates all grid levels for every balance tier, tracks virtual execution state, and serves sync instructions to client EAs.
- **The Client** subscribes, attaches a "slave" EA to their MT5 chart, and the EA polls the server to replicate the virtual grid signals as real trades.
- **The Grid Engine** has 4 independent grids per tier: **Buy Grid 1 (B1)**, **Buy Grid 2 (B2)**, **Sell Grid 1 (S1)**, **Sell Grid 2 (S2)**. Each grid has its own controls, inputs, session, and execution state.
- **Trade tracking** uses unique comment IDs embedded in every MT5 trade, enabling precise matching between the server's virtual state and the client's actual positions.

**What Changed from the Current System (v3.4.2):**

| Aspect           | Current (v3.4.2)                 | New SaaS (v4)                                |
| ---------------- | -------------------------------- | -------------------------------------------- |
| Grids            | 2 (1 Buy, 1 Sell)                | 4 (2 Buy, 2 Sell)                            |
| Trade Execution  | Server tells Admin's EA to trade | Server marks rows virtually; Clients execute |
| First Row        | Has a gap value                  | Gap = 0, executes immediately on activation  |
| Users            | Single admin                     | Admin + N subscriber clients                 |
| Grid State       | In-memory + state.json           | In-memory + PostgreSQL persistence           |
| Tiers            | None                             | Balance-range tiers (1k-4k, 4k-8k, etc.)     |
| IronClad Hedge   | Auto-opens opposite trade        | Removed — admin manages risk manually        |
| Client Dashboard | N/A                              | Read-only view of grid state + personal P&L  |

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     ADMIN'S VPS                              │
│  ┌─────────────────┐                                         │
│  │   Master EA      │ ── (1 tick/sec) ──► POST /api/master   │
│  │   (Data Feeder)  │      price feed                        │
│  │   XAUUSD Chart   │      only                              │
│  └─────────────────┘                                         │
└────────────────────────────────┬─────────────────────────────┘
                                 │ HTTP POST (Bid, Ask)
                                 ▼
┌──────────────────────────────────────────────────────────────┐
│                   CENTRAL SERVER (Python/FastAPI)             │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Auth Module  │  │  Tier Engine  │  │  Grid Engine  │      │
│  │  (JWT/Login)  │  │  (Routing)    │  │  (4-Grid x N) │     │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐  ┌──────────────┐                          │
│  │  Client Sync  │  │  Dashboard    │                         │
│  │  (Slave Logic)│  │  API          │                         │
│  └──────────────┘  └──────────────┘                          │
│                         │                                     │
│                    PostgreSQL DB                               │
└─────────┬────────────────┬───────────────────────────────────┘
          │                │
     HTTP POST         HTTP GET/POST
  /api/client-ping    /api/* (dashboard)
          │                │
          ▼                ▼
┌─────────────────┐  ┌──────────────────┐
│  Client EA #1   │  │  Web Frontend     │
│  Client EA #2   │  │  (React/Next.js)  │
│  Client EA #N   │  │  Admin + Client   │
│  (MT5 Charts)   │  │  Dashboards       │
└─────────────────┘  └──────────────────┘
```

**Data Flow Summary:**

1. **Master EA → Server**: Price feed (bid, ask) every 1 second. No trade execution.
2. **Server (Grid Engine)**: On each price tick, iterates all tiers and all 4 grids per tier. Marks rows as "executed" when price crosses gap thresholds. Checks TP and end_limit.
3. **Client EA → Server**: Every 1 second, sends `{mt5_id, balance, positions[]}`. Server authenticates, finds tier, compares client positions to virtual grid state, returns sync instructions.
4. **Server → Client EA**: Returns an array of actions: `[{action, volume, comment}, ...]`.
5. **Web Dashboard → Server**: Admin and clients fetch grid state, P&L data via REST API.

---

## 3. Component Specifications

### 3.1 Master EA (Data Feeder)

**Role:** The sole source of market truth. Runs on the Admin's VPS, attached to an XAUUSD chart.

**What it sends (every 1 second):**

```json
{
  "ask": 2030.5,
  "bid": 2030.1,
  "contract_size": 100.0,
  "server_time": "2026-03-01T10:00:00"
}
```

**How `contract_size` is obtained (MQL5):**

```cpp
double contractSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE);
// For XAUUSD this returns 100.0 (1 lot = 100 troy ounces)
```

The Master EA reads this from the broker on every tick and includes it in the payload. The server uses this value for accurate virtual P&L calculation instead of hardcoding it.

**What it does NOT do:**

- Does NOT execute any trades.
- Does NOT send account data (equity, balance, positions).
- Does NOT receive trade commands.

**Configuration (MQL5 inputs):**

```cpp
input string InpServerURL = "http://YOUR_SERVER_IP:8000";
input string InpAdminKey  = "ADMIN_SECRET_KEY_FROM_ENV";  // Auth header
input int    InpTimeout   = 5000;
```

**Authentication:** Every request includes the `X-Admin-Key` header. Server validates against `.env` value. If mismatch, request is rejected.

**Endpoint:** `POST /api/master-tick`

**Failure behavior:** If the server is unreachable, the Master EA retries silently on the next tick. It logs connectivity errors every 20 failures to avoid journal spam (same pattern as current `automation.mq5`).

---

### 3.2 Central Server (Brain)

**Technology:** Python 3.11+, FastAPI, Uvicorn, PostgreSQL, SQLAlchemy  
**Role:** All-knowing state machine. Handles:

- Market data ingestion from Master EA
- Virtual grid execution for all tiers
- Client sync instructions
- Admin/Client dashboard APIs
- Authentication and subscription validation

**In-Memory State (per tier):** The active grid runtime state is kept in memory for speed and persisted to PostgreSQL on every state change (same pattern as current `state.json`, but per-tier and DB-backed).

**Key Design Rule:** The server never directly executes trades. It computes virtual grid state and serves instructions. All actual trade execution happens on client EAs.

---

### 3.3 Client EA (Slave Executor)

**Role:** Dumb executor. Polls server, receives commands, executes trades.

**What it sends (every 1 second):**

```json
{
  "mt5_id": "883921",
  "balance": 5200.0,
  "positions": [
    {
      "ticket": 1001,
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.01,
      "price": 2035.0,
      "profit": -5.0,
      "comment": "B1_a1b2c3d4_0"
    }
  ]
}
```

**What it receives:**

```json
{
  "status": "ok",
  "actions": [
    { "action": "BUY", "volume": 0.02, "comment": "B1_a1b2c3d4_1" },
    { "action": "CLOSE_ALL", "comment": "S2_oldoldol" }
  ]
}
```

**What it does NOT do:**

- Does NOT send price data (server gets that from Master EA).
- Does NOT make trading decisions.
- Does NOT display grid UI (that's the web dashboard).

**Configuration (MQL5 inputs):**

```cpp
input string InpServerURL = "http://YOUR_SERVER_IP:8000";
input int    InpTimeout   = 5000;
input int    InpMagicNumber = 789456;
input int    InpSlippage  = 10;    // Points
input bool   InpDebugMode = true;
```

**On-Chart Panel (Simple text display):**

```
Status: CONNECTED ✓
MT5 ID: 883921
Tier: 4k-8k
Subscription: Active (Expires: 2026-04-01)
Active Grids: B1 ✓ | B2 ✗ | S1 ✓ | S2 ✗
```

**Endpoint:** `POST /api/client-ping`

---

### 3.4 Web Frontend

**Technology:** React (Vite) or Next.js  
**Pages:**

| Page         | Access      | Purpose                                      |
| ------------ | ----------- | -------------------------------------------- |
| `/`          | Public      | Landing, Pricing, PayPal Subscribe           |
| `/login`     | Public      | Auth portal                                  |
| `/admin`     | Admin only  | Grid management, Tier controls, User monitor |
| `/dashboard` | Client only | Read-only view of grids, personal P&L        |
| `/account`   | Client only | MetaID input, subscription status            |

---

### 3.5 Database (PostgreSQL)

Detailed schema in [Section 9](#9-database-schema).

---

## 4. The Balance Tier System

### 4.1 Concept

Clients are grouped by account balance into "Tiers." Each tier has its own complete set of 4 grids with independent configurations and execution state.

**Example Tiers:**

| Tier Name | Balance Range     | Typical Lots |
| --------- | ----------------- | ------------ |
| `1k-4k`   | $1,000 – $3,999   | 0.01 – 0.02  |
| `4k-8k`   | $4,000 – $7,999   | 0.02 – 0.05  |
| `8k-12k`  | $8,000 – $11,999  | 0.05 – 0.10  |
| `12k-20k` | $12,000 – $19,999 | 0.10 – 0.20  |
| `20k+`    | $20,000+          | 0.20+        |

Tier names and ranges are Admin-configurable. There is no hardcoded limit on the number of tiers.

### 4.2 Tier Assignment Logic

1. **On first client ping** (client has no active sessions in any grid): Server checks `client.balance` against all tier ranges. Assigns the tier where `tier.min_balance <= balance < tier.max_balance`.
2. **Once assigned** (client has at least one active session): The tier is **LOCKED** for the duration of any active grid session. Balance fluctuations do NOT cause mid-session tier changes.
3. **On full session reset** (all 4 grids have no active sessions for this client): Tier assignment is re-evaluated on the next ping.

**Why lock the tier?** If a client's balance drops from $5,000 to $3,800 during active trading, switching them from "4k-8k" to "1k-4k" mid-session would cause:

- Grid row mismatch (different lots, gaps)
- Orphaned trades (positions tagged with old tier's session IDs)
- Mathematical safety violations

### 4.3 Edge Case: Balance Outside All Tiers

If a client's balance doesn't fit any configured tier (e.g., balance is $500 and the smallest tier starts at $1,000):

- Server returns `{"status": "no_tier", "message": "Account balance below minimum tier."}`.
- Client EA enters idle mode, displays "No matching tier" on chart.

### 4.4 Tier Storage

Each tier is a database record containing:

- Tier metadata (name, min/max balance, symbol)
- 4 grid configurations (settings for B1, B2, S1, S2)
- 4 grid runtime states (execution maps, session IDs, flags)

---

## 5. The 4-Grid Engine

### 5.1 Grid Identifiers

Each tier has exactly 4 grids:

| Grid ID | Full Name               | Trade Direction | Pair   |
| ------- | ----------------------- | --------------- | ------ |
| `B1`    | Buy Grid 1 (Primary)    | BUY             | Pair A |
| `S1`    | Sell Grid 1 (Primary)   | SELL            | Pair A |
| `B2`    | Buy Grid 2 (Secondary)  | BUY             | Pair B |
| `S2`    | Sell Grid 2 (Secondary) | SELL            | Pair B |

### 5.2 Grid Pairs & Relationships

Grids are organized into two **Pairs**:

- **Pair A:** B1 ↔ S1
- **Pair B:** B2 ↔ S2

Pairing is a logical grouping — Pair A grids (B1, S1) are intended to be used together for the same market view, and Pair B (B2, S2) for another. **All 4 grids are fully independent.** Each grid has its own session, controls, and execution state. There is no automatic interaction between grids.

### 5.3 Per-Grid Controls & Inputs

Each grid has its own independent set of controls. These are displayed above each grid table in the Admin dashboard.

#### 5.3.1 Toggle Buttons (per grid)

| Control        | Type          | Description                                                                                                                                   |
| -------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **ON/OFF**     | Toggle switch | Activates or deactivates the grid. Turning OFF triggers session close.                                                                        |
| **Cyclic Run** | Toggle switch | If ON, when a session completes (TP hit or manual close), a new session automatically starts immediately. If OFF, grid stays off after close. |

#### 5.3.2 Value Inputs (per grid)

| Input           | Type          | Description                                                                                                                                                                                                                                                                       |
| --------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **start_limit** | Float (price) | The anchor price. `0` = use current market price when grid is turned ON. `> 0` = wait for price to reach this level before activating. For BUY grids: wait for ask ≤ start_limit. For SELL grids: wait for bid ≥ start_limit.                                                     |
| **end_limit**   | Float (price) | Safety boundary. `0` = disabled (no boundary). For BUY grids: stop expanding if ask drops below end_limit. For SELL grids: stop expanding if bid rises above end_limit. The grid will NOT mark any new rows as executed beyond this price. Existing executed rows are unaffected. |

#### 5.3.3 Profit (Take Profit) Settings (per grid)

| Input        | Type  | Description                                        |
| ------------ | ----- | -------------------------------------------------- |
| **tp_type**  | Enum  | One of: `equity_pct`, `balance_pct`, `fixed_money` |
| **tp_value** | Float | The target value. `0` = TP disabled.               |

**How TP types work in the virtual engine:**

Since the master doesn't have real equity/balance, TP calculations use the **tier's reference balance** (the midpoint of the tier's balance range):

| TP Type       | Calculation                                          |
| ------------- | ---------------------------------------------------- |
| `equity_pct`  | `target = tier_reference_balance × (tp_value / 100)` |
| `balance_pct` | `target = tier_reference_balance × (tp_value / 100)` |
| `fixed_money` | `target = tp_value` (direct dollar amount)           |

> **Note:** `equity_pct` and `balance_pct` produce the same result in the virtual engine since there's no distinction between virtual equity and balance. They are kept as separate options for semantic clarity and future flexibility. The **recommended default** for the SaaS is `fixed_money` for precision.

**Example:** Tier "4k-8k" → reference balance = $6,000. If `tp_type = balance_pct` and `tp_value = 1.5`, then `target = 6000 × 0.015 = $90`.

### 5.4 Grid Row Structure

Each grid contains up to 100 rows (strata levels). Row structure:

```typescript
interface GridRow {
  index: number; // 0-based position in the grid
  dollar: number; // Gap distance from previous level (in price units, e.g., $2.00 for XAUUSD)
  lots: number; // Volume to trade at this level
  alert: boolean; // If true, triggers UI/audio alert when executed
  executed: boolean; // Managed by server. True when market crosses this level.
  entry_price: number; // Set by server when executed. The ask/bid at execution moment.
  executed_at: string; // ISO timestamp of virtual execution. Empty if not executed.
}
```

**Server-managed fields:** `executed`, `entry_price`, `executed_at` — The admin can edit `dollar`, `lots`, `alert` for non-executed rows. Executed rows have `dollar` and `lots` locked.

### 5.5 First Row Behavior (Row 0)

**Critical Rule:** Row 0 of every grid has `dollar = 0` and is **non-editable** for the gap field.

- When the admin turns a grid ON, Row 0 is immediately marked as `executed = true`.
- The `entry_price` is set to the current market price (ask for BUY grids, bid for SELL grids).
- This means: **the first trade fires instantly** when the grid activates.
- Row 0's `lots` value IS editable by the admin (it defines the initial position size).

**Why?** In the previous system, the first row had a gap value, meaning nothing happened until price moved away from the anchor. In the new system, activation = immediate entry. This gives the admin instant control.

### 5.6 Data Model Summary (Per Grid)

```python
class GridConfig(BaseModel):
    """Per-grid settings (admin-editable)"""
    grid_id: str              # "B1", "B2", "S1", "S2"
    on: bool = False
    cyclic: bool = False
    start_limit: float = 0.0
    end_limit: float = 0.0
    tp_type: str = "fixed_money"
    tp_value: float = 0.0
    rows: List[GridRow] = []

class GridRuntime(BaseModel):
    """Per-grid runtime state (server-managed)"""
    grid_id: str
    session_id: str = ""       # e.g., "B1_a1b2c3d4"
    is_active: bool = False
    waiting_limit: bool = False
    start_ref: float = 0.0    # The anchor price for this session
    last_order_ts: float = 0.0 # For Sync-Shield grace period
```

---

## 6. Session Management

### 6.1 Session ID Format

Every grid session gets a unique identifier used to tag trades in MT5.

**Format:** `{GRID_ID}_{8_HEX_CHARS}`

| Component    | Example    | Description                 |
| ------------ | ---------- | --------------------------- |
| Grid ID      | `B1`       | Which grid (B1, B2, S1, S2) |
| Separator    | `_`        | Underscore                  |
| Session Hash | `a1b2c3d4` | 8-character hex from UUID4  |

**Full session ID examples:**

- `B1_a1b2c3d4`
- `S2_f9e8d7c6`

**Trade comment format (for MT5 position comments):**

`{SESSION_ID}_{ROW_INDEX}`

Examples:

- `B1_a1b2c3d4_0` → Buy Grid 1, session a1b2c3d4, row 0
- `S1_f9e8d7c6_5` → Sell Grid 1, session f9e8d7c6, row 5
- `B2_11223344_12` → Buy Grid 2, session 11223344, row 12

**Max length:** `B2_a1b2c3d4_99` = 15 characters. Well within MT5's comment field limit.

**Regex pattern for validation:**

```
^(B[12]|S[12])_[0-9a-fA-F]{8}_\d+$
```

### 6.2 Session Lifecycle

A grid session goes through these states:

```
[OFF] ──(admin turns ON)──► [WAITING_LIMIT] or [ACTIVE]
                                     │
                            (price hits start_limit)
                                     │
                                     ▼
                                 [ACTIVE]
                                     │
                            ┌────────┴────────┐
                            │                 │
                       (TP hit)          (admin OFF)
                            │                 │
                            ▼                 ▼
                       ┌─────────┐      [OFF]
                       │         │      (grid stopped,
                  (cyclic ON) (cyclic OFF) clients detect
                       │         │       stale session)
                       ▼         ▼
                   [ACTIVE]    [OFF]
                  (new session) (grid stopped)
```

**Key design:** There is NO intermediate "closing" state. When a TP is hit or admin turns OFF:

- **If cyclic ON:** Server immediately generates a new session_id, resets rows, and starts fresh. The old session_id is simply abandoned.
- **If cyclic OFF:** Server sets `on = false` and clears the session_id.

**Clients handle the transition themselves:** On each ping, the client compares its open trade comments against the current session_id. If the client has trades from an old session_id that no longer matches, the client closes them. If there's a new session, the client starts joining it. No server-side "closing" coordination needed.

**State descriptions:**

| State         | `on`  | `session_id` | Description                                                                      |
| ------------- | ----- | ------------ | -------------------------------------------------------------------------------- |
| OFF           | false | `""`         | Grid inactive. No session. Clients with stale trades close them on next ping.    |
| WAITING_LIMIT | true  | set          | Session created, waiting for price to hit `start_limit`. `waiting_limit = true`. |
| ACTIVE        | true  | set          | Session running. Rows are being executed as price moves.                         |

### 6.3 Session Activation (Turning ON)

When admin turns a grid ON:

1. Generate new session ID: `{GRID_ID}_{uuid4().hex[:8]}`.
2. Reset execution state: Clear all `executed` flags on rows, clear `entry_price` and `executed_at`.
3. **If `start_limit > 0`:** Set `waiting_limit = true`. Set `start_ref = start_limit`. Wait for price.
4. **If `start_limit == 0`:** Set `waiting_limit = false`. Set `start_ref = current_ask` (for BUY) or `current_bid` (for SELL). **Immediately execute Row 0** (mark `executed = true`, record `entry_price`).

### 6.4 Session Close (Turning OFF / TP Hit)

When a close is triggered (admin turns OFF or TP is hit):

**If cyclic ON (TP hit):**

1. Generate new session_id immediately.
2. Reset all row execution state.
3. Start fresh session (same as turning ON).
4. Clients will detect the session_id change on their next ping:
   - Close all trades tagged with the OLD session_id.
   - Start executing trades for the NEW session_id.

**If cyclic OFF (TP hit or admin turns OFF):**

1. Set `on = false`, clear `session_id` to `""`.
2. Clients will detect their trade comments don't match any active session.
3. Clients close trades tagged with the now-gone session_id.

**There is no server-side waiting or acknowledgment.** The server makes its decision instantly and moves on. Clients are responsible for cleaning up stale trades.

### 6.5 Cyclic Restart Flow

When cyclic is ON and TP is hit:

1. Generate new session_id immediately.
2. Reset all row execution state (`executed = false` for all rows).
3. Set `start_ref` to current market price (or `start_limit` if set and > 0).
4. If `start_limit == 0`: Execute Row 0 immediately.
5. Grid continues as a brand new session.

Clients discover the session change on their next ping. They see trades with old session_id that doesn't match the current one → they close the old trades (Scenario 4 in sync protocol). Then on subsequent pings, they join the new session normally.

---

## 7. Virtual Execution Engine (Master Logic)

This is the core of the server. It runs on every Master EA tick (1/second).

### 7.1 How Rows Get Marked "Executed"

**For BUY grids (B1, B2):**

Price moves DOWN to trigger execution. Each row's target price is calculated by subtracting cumulative gaps from the start_ref.

```
row[0].target = start_ref - row[0].dollar  (= start_ref, since row[0].dollar = 0)
row[1].target = start_ref - row[0].dollar - row[1].dollar
row[2].target = start_ref - row[0].dollar - row[1].dollar - row[2].dollar
...
row[N].target = start_ref - sum(row[0..N].dollar)
```

**Execution condition:** `current_ask <= row[N].target`

When triggered:

- `row[N].executed = true`
- `row[N].entry_price = current_ask`
- `row[N].executed_at = datetime.now().isoformat()`

**For SELL grids (S1, S2):**

Price moves UP to trigger execution. Each row's target price is calculated by adding cumulative gaps.

```
row[0].target = start_ref + row[0].dollar  (= start_ref, since row[0].dollar = 0)
row[1].target = start_ref + row[0].dollar + row[1].dollar
...
row[N].target = start_ref + sum(row[0..N].dollar)
```

**Execution condition:** `current_bid >= row[N].target`

When triggered:

- `row[N].executed = true`
- `row[N].entry_price = current_bid`
- `row[N].executed_at = datetime.now().isoformat()`

### 7.2 Sequential Execution Rule

Rows MUST execute in order. Row N cannot execute before Row N-1.

On each tick, the server looks at the **next un-executed row** (the first row where `executed == false`). Only that row is checked against the price. If its condition is met, it is marked executed, and on the NEXT tick, the following row becomes the candidate.

**Exception:** If price moves so fast that it skips multiple levels in one tick (e.g., a $10 spike), the server still only executes ONE row per tick. This is intentional — it prevents burst-execution and gives clients time to process each level. At 1 tick/second, the server can execute up to 1 row per second, which is more than sufficient for normal market conditions.

### 7.3 Start Limit (Anchor) Behavior

When `start_limit > 0` and `waiting_limit == true`:

**For BUY grids:** Wait until `current_ask <= start_limit`. Then:

- Set `waiting_limit = false`
- Set `start_ref = current_ask`
- Immediately execute Row 0

**For SELL grids:** Wait until `current_bid >= start_limit`. Then:

- Set `waiting_limit = false`
- Set `start_ref = current_bid`
- Immediately execute Row 0

### 7.4 End Limit (Safety Boundary) Behavior

When `end_limit > 0`:

**For BUY grids:** If `current_ask < end_limit`, **do not execute any more rows**. The grid expansion is paused. If price recovers above `end_limit`, expansion resumes. Already-executed rows are unaffected.

**For SELL grids:** If `current_bid > end_limit`, **do not execute any more rows**. Same pause/resume logic.

**End limit does NOT close the session.** It only pauses new execution. The session remains active, existing virtual positions remain, TP checks continue. The admin can manually close or adjust.

### 7.5 Virtual P&L Calculation

The server calculates theoretical profit/loss for each grid using the virtual entry prices and current market price.

**XAUUSD Contract Specification:**

- 1 Standard Lot = 100 troy ounces
- $1 price movement = $100 per lot

The `contract_size` value is sent by the Master EA on every tick (read from the broker via `SymbolInfoDouble`). The server stores it in memory and uses it for all P&L calculations. This ensures accuracy even if the broker uses a non-standard contract size.

```python
# contract_size comes from master tick payload (e.g., 100.0 for XAUUSD)

def calculate_virtual_pnl(grid: GridConfig, runtime: GridRuntime, current_bid: float, current_ask: float, contract_size: float) -> float:
    """Calculate the theoretical P&L of a grid's executed rows."""
    total_pnl = 0.0
    for row in grid.rows:
        if not row.executed:
            continue
        if grid.grid_id.startswith("B"):
            # BUY position: profit when bid > entry_price
            pnl = (current_bid - row.entry_price) * row.lots * contract_size
        else:
            # SELL position: profit when entry_price > ask
            pnl = (row.entry_price - current_ask) * row.lots * contract_size
        total_pnl += pnl
    return total_pnl
```

**Per-row P&L** is also calculated and stored for dashboard display:

```python
row.virtual_pnl = pnl  # Updated on every tick, transient (not persisted)
```

**Cumulative P&L** is the running total across all executed rows in a grid.

### 7.6 Take Profit (Snap-Back) Logic

On every tick, after updating virtual P&L:

```python
def check_tp(grid: GridConfig, runtime: GridRuntime, tier_ref_balance: float, virtual_pnl: float) -> bool:
    if grid.tp_value <= 0:
        return False  # TP disabled

    if grid.tp_type == "fixed_money":
        target = grid.tp_value
    elif grid.tp_type in ("equity_pct", "balance_pct"):
        target = tier_ref_balance * (grid.tp_value / 100.0)
    else:
        return False

    return virtual_pnl >= target
```

**When TP is hit:**

1. Log: `[SNAP-BACK] Grid {grid_id} TP hit. Virtual P&L: ${virtual_pnl:.2f} >= Target: ${target:.2f}`
2. **If cyclic ON:** Immediately generate new session_id, reset rows, start fresh session. Clients detect old session mismatch on next ping and close old trades, then join new session.
3. **If cyclic OFF:** Set `on = false`, clear session_id. Clients detect stale session on next ping and close trades.

### 7.7 Complete Tick Processing Flow (Master Tick Handler)

```
RECEIVE master tick (ask, bid, contract_size)
│
├─ Validate admin key → reject if invalid
│
├─ Update market state (current_ask, current_bid, contract_size, price_direction)
│
├─ FOR EACH tier:
│   ├─ Calculate tier_reference_balance = (tier.min_balance + tier.max_balance) / 2
│   │
│   ├─ FOR EACH grid in [B1, B2, S1, S2]:
│   │   │
│   │   ├─ SKIP if grid.on == false
│   │   │
│   │   ├─ [PHASE 1: LIMIT WAIT]
│   │   │   If grid.waiting_limit:
│   │   │     - BUY: if ask <= start_limit → activate, execute row 0
│   │   │     - SELL: if bid >= start_limit → activate, execute row 0
│   │   │     - CONTINUE to next grid
│   │   │
│   │   ├─ [PHASE 2: VIRTUAL P&L UPDATE]
│   │   │   Calculate virtual_pnl for all executed rows (using contract_size)
│   │   │
│   │   ├─ [PHASE 3: TP CHECK]
│   │   │   If virtual_pnl >= tp_target:
│   │   │     - If cyclic: generate new session, reset rows, activate
│   │   │     - Else: set on = false, clear session
│   │   │     - CONTINUE to next grid
│   │   │
│   │   ├─ [PHASE 4: END LIMIT CHECK]
│   │   │   BUY: if ask < end_limit → skip expansion
│   │   │   SELL: if bid > end_limit → skip expansion
│   │   │
│   │   ├─ [PHASE 5: GRID EXPANSION]
│   │   │   Find next un-executed row
│   │   │   Calculate target price
│   │   │   BUY: if ask <= target → mark executed
│   │   │   SELL: if bid >= target → mark executed
│   │   │
│   │   └─ Save state
│   │
│   └─ END FOR grids
│
└─ END FOR tiers

RETURN { "status": "ok" }
```

---

## 8. Client Sync Protocol (Slave Logic)

### 8.1 Client Ping Payload

Every 1 second, the client EA sends:

```json
{
  "mt5_id": "883921",
  "balance": 5200.0,
  "positions": [
    {
      "ticket": 1001,
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.01,
      "price": 2035.0,
      "profit": -5.0,
      "comment": "B1_a1b2c3d4_0"
    },
    {
      "ticket": 1002,
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.02,
      "price": 2033.0,
      "profit": -3.5,
      "comment": "B1_a1b2c3d4_1"
    }
  ]
}
```

### 8.2 Authentication Flow

```
RECEIVE client ping
│
├─ Look up user by mt5_id in database
│   ├─ NOT FOUND → return {"status": "error", "message": "Unknown account"}
│   └─ FOUND → continue
│
├─ Check subscription status
│   ├─ EXPIRED → return {"status": "expired", "message": "Subscription expired"}
│   ├─ BANNED → return {"status": "banned"}
│   └─ ACTIVE → continue
│
├─ Save user snapshot (balance, positions, last_seen timestamp)
│
└─ Continue to tier assignment
```

### 8.3 Tier Assignment

```
├─ Check if user has any active sessions (positions with recognized comments)
│   ├─ YES (has active trades) → use previously assigned tier (locked)
│   └─ NO (clean slate) → evaluate balance:
│       ├─ Find tier where min_balance <= balance < max_balance
│       ├─ FOUND → assign tier, store tier_id on user record
│       └─ NOT FOUND → return {"status": "no_tier", "message": "Balance outside ranges"}
│
└─ Load tier's 4 grid states
```

### 8.4 The 3 Synchronization Scenarios

For EACH of the 4 grids, the server compares the client's reported positions against the grid's virtual execution state and determines what actions the client needs to take.

#### Scenario 1: Late Join (2+ rows already executed, client has 0 matching positions)

**Condition:**

- Grid has an active session with ≥ 2 rows executed
- Client has ZERO positions matching this grid's session_id

**Action:** WAIT (skip this grid). The client missed the safe entry window.

**Reasoning:** Entering at row 0 when rows 0-4 are already executed would ruin the mathematical safety of the DCA spacing. The client must wait for:

- A new session (cyclic restart after TP)
- A manual restart by admin

```python
if grid_executed_count >= 2 and client_positions_for_grid == 0:
    action = None  # Skip, wait for next session
```

#### Scenario 2: Fresh Join (exactly 1 row executed, client has 0 matching positions)

**Condition:**

- Grid has an active session with exactly 1 row executed (Row 0, the immediate entry)
- Client has ZERO positions matching this grid's session_id

**Action:** Tell client to execute Row 0.

```python
if grid_executed_count == 1 and client_positions_for_grid == 0:
    row_0 = grid.rows[0]
    action = {
        "action": "BUY" if grid_id.startswith("B") else "SELL",
        "volume": row_0.lots,
        "comment": f"{session_id}_{row_0.index}"
    }
```

**Important:** The client executes at their current market price, not at the master's virtual entry_price. Minor slippage is expected and acceptable.

#### Scenario 3: Catchup / Normal Sync (client has some positions, grid has more executed)

**Condition:**

- Grid has N rows executed
- Client has positions matching this session, but fewer than N

**Action:** Tell client to execute the MISSING rows (one at a time, per ping).

```python
# Find which row indices the client has
client_row_indices = extract_indices_from_comments(client_positions, session_id)
# e.g., client has [0, 1], grid has [0, 1, 2, 3] executed

# Find the first missing row
for row in grid.rows:
    if row.executed and row.index not in client_row_indices:
        action = {
            "action": "BUY" if grid_id.startswith("B") else "SELL",
            "volume": row.lots,
            "comment": f"{session_id}_{row.index}"
        }
        break  # Only one action per grid per ping
```

**Rate limiting:** Only ONE new trade instruction per grid per ping. If client is 5 rows behind, it takes 5 pings (5 seconds) to catch up. This prevents overwhelming the broker with simultaneous orders.

#### Scenario 4: Session Mismatch (client has OLD session trades)

**Condition:**

- Client has positions with comments matching this grid's ID (e.g., `B1_...`) but with a DIFFERENT session hash than the current active session.

**Action:** Close the stale trades first.

```python
stale_session_ids = find_stale_sessions(client_positions, grid_id, current_session_id)
# e.g., client has trades with "B1_oldoldol" but current session is "B1_newnew00"

if stale_session_ids:
    for stale_id in stale_session_ids:
        actions.append({
            "action": "CLOSE_ALL",
            "comment": stale_id
        })
```

After the client closes stale trades, on the next ping, Scenario 1, 2, or 3 applies for the current session.

**This is also how TP hit and admin-OFF transitions are handled.** When TP triggers a cyclic restart, the server generates a new session_id — clients still holding old-session trades will hit this scenario and close them. When admin turns a grid OFF (non-cyclic), the session_id is cleared — clients detect their trades belong to a session that no longer exists and close them.

#### Scenario 5: Grid is OFF, client has orphan trades

**Condition:**

- Grid is OFF (`on == false`, `session_id == ""`) and client has positions with comments matching this grid's ID (e.g., `B1_...`).

**Action:** Close all trades for this grid. Since there's no active session, any trade from any previous session is stale.

```python
if not grid.on and client_has_any_positions_for_grid:
    # Find all unique session IDs from client's positions for this grid
    orphan_session_ids = extract_session_ids_for_grid(client_positions, grid_id)
    for orphan_id in orphan_session_ids:
        actions.append({
            "action": "CLOSE_ALL",
            "comment": orphan_id
        })
```

#### Scenario 6: Everything in Sync

**Condition:**

- Client has positions for all executed rows, no missing rows, no stale sessions.

**Action:** None. Return nothing for this grid.

### 8.5 Response Format

The client ping response aggregates actions across all 4 grids:

```json
{
  "status": "ok",
  "tier": "4k-8k",
  "actions": [
    { "action": "BUY", "volume": 0.02, "comment": "B1_a1b2c3d4_2" },
    { "action": "CLOSE_ALL", "comment": "S2_oldoldol" },
    { "action": "SELL", "volume": 0.05, "comment": "S1_b5c6d7e8_0" }
  ]
}
```

**If no actions needed:**

```json
{
  "status": "ok",
  "tier": "4k-8k",
  "actions": []
}
```

### 8.6 Trade Comment Format

| Trade Direction | Grid | Session  | Row | Comment String  |
| --------------- | ---- | -------- | --- | --------------- |
| BUY             | B1   | a1b2c3d4 | 0   | `B1_a1b2c3d4_0` |
| BUY             | B1   | a1b2c3d4 | 5   | `B1_a1b2c3d4_5` |
| BUY             | B2   | 11223344 | 0   | `B2_11223344_0` |
| SELL            | S1   | f9e8d7c6 | 3   | `S1_f9e8d7c6_3` |
| SELL            | S2   | aabbccdd | 0   | `S2_aabbccdd_0` |

### 8.7 Multiple Actions per Ping

The client EA receives an array and processes ALL actions sequentially in a single tick:

```cpp
// MQL5 Pseudocode
for (int i = 0; i < actionsCount; i++) {
    string action = actions[i].action;
    if (action == "BUY") ExecuteBuyOrder(actions[i].volume, actions[i].comment);
    if (action == "SELL") ExecuteSellOrder(actions[i].volume, actions[i].comment);
    if (action == "CLOSE_ALL") ClosePositionsByComment(actions[i].comment);
}
```

**Order of processing:**

1. `CLOSE_ALL` actions first (clean up stale positions)
2. `BUY` / `SELL` actions second (open new positions)

The server should sort the actions array accordingly.

### 8.8 Disconnect / Reconnect Handling

**Client EA disconnects (network loss, MT5 restart):**

- The server doesn't know. No action needed server-side.
- Client's positions remain open in MT5.
- When client reconnects, the sync protocol handles it:
  - If session is still the same → Scenario 3 (catchup) or Scenario 6 (in sync)
  - If session changed → Scenario 4 (close stale) + Scenario 2/3 (join new)

**Master EA disconnects (VPS issue):**

- No price feed → no grid rows get executed → system pauses naturally.
- Client EAs keep pinging but server has no new state → actions array stays empty.
- When Master EA reconnects, grid processing resumes from where it left off.

---

## 9. Database Schema

### 9.1 `users` Table

```sql
CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    phone           VARCHAR(20),
    mt5_id          VARCHAR(50) UNIQUE,              -- MetaTrader 5 Account Number
    assigned_tier_id INTEGER REFERENCES tiers(id),   -- Currently locked tier (NULL if no active session)
    role            VARCHAR(20) DEFAULT 'client',     -- 'client' or 'admin'
    status          VARCHAR(20) DEFAULT 'pending',    -- 'pending', 'active', 'banned'
    email_verified  BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_users_mt5_id ON users(mt5_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_status ON users(status);
```

**Updatable fields:** email, name, phone, mt5_id, status, password_hash  
**Non-updatable fields:** id, created_at, role (admin sets these)

### 9.2 `subscriptions` Table

```sql
CREATE TABLE subscriptions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plan_name       VARCHAR(50) NOT NULL,             -- "monthly", "quarterly", etc.
    status          VARCHAR(20) DEFAULT 'active',     -- 'active', 'cancelled', 'expired'
    paypal_sub_id   VARCHAR(100),                     -- PayPal subscription reference
    start_date      TIMESTAMP NOT NULL,
    end_date        TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX idx_subscriptions_status ON subscriptions(status);
CREATE INDEX idx_subscriptions_end_date ON subscriptions(end_date);
```

### 9.3 `tiers` Table

```sql
CREATE TABLE tiers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) NOT NULL UNIQUE,      -- "1k-4k", "4k-8k", etc.
    symbol          VARCHAR(20) DEFAULT 'XAUUSD',
    min_balance     DECIMAL(15,2) NOT NULL,           -- Lower bound (inclusive)
    max_balance     DECIMAL(15,2) NOT NULL,           -- Upper bound (exclusive)
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.4 `tier_grids` Table

Each tier has exactly 4 grid records. This stores both configuration AND runtime state.

```sql
CREATE TABLE tier_grids (
    id              SERIAL PRIMARY KEY,
    tier_id         INTEGER REFERENCES tiers(id) ON DELETE CASCADE,
    grid_id         VARCHAR(2) NOT NULL,              -- "B1", "B2", "S1", "S2"

    -- Configuration (Admin-editable)
    config          JSONB NOT NULL DEFAULT '{}',
    /* config structure:
    {
        "on": false,
        "cyclic": false,
        "start_limit": 0.0,
        "end_limit": 0.0,
        "tp_type": "fixed_money",
        "tp_value": 0.0,
        "rows": [
            {"index": 0, "dollar": 0, "lots": 0.01, "alert": false, "executed": false, "entry_price": 0, "executed_at": ""},
            {"index": 1, "dollar": 2.0, "lots": 0.02, "alert": true, "executed": false, "entry_price": 0, "executed_at": ""},
            ...
        ]
    }
    */

    -- Runtime State (Server-managed)
    runtime         JSONB NOT NULL DEFAULT '{}',
    /* runtime structure:
    {
        "session_id": "",
        "is_active": false,
        "waiting_limit": false,
        "start_ref": 0.0,
        "last_order_ts": 0.0
    }
    */

    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(tier_id, grid_id)
);

CREATE INDEX idx_tier_grids_tier ON tier_grids(tier_id);
```

### 9.5 `user_snapshots` Table

Stores the latest data from each client's EA ping. Used for dashboard display and monitoring.

```sql
CREATE TABLE user_snapshots (
    user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    equity          DECIMAL(15,2),
    balance         DECIMAL(15,2),
    positions       JSONB DEFAULT '[]',               -- Full positions array from latest ping
    last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.6 `market_state` Table (or in-memory)

Stores the latest price data from the Master EA. Can be a single-row table or kept purely in memory.

```sql
CREATE TABLE market_state (
    id              INTEGER PRIMARY KEY DEFAULT 1,    -- Always 1 row
    symbol          VARCHAR(20) DEFAULT 'XAUUSD',
    ask             DECIMAL(15,5),
    bid             DECIMAL(15,5),
    mid             DECIMAL(15,5),
    contract_size   DECIMAL(10,2) DEFAULT 100,        -- From Master EA (SymbolInfoDouble)
    direction       VARCHAR(10) DEFAULT 'neutral',    -- 'up', 'down', 'neutral'
    last_update     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 10. Authentication & Subscription

### 10.1 Admin Authentication

Admin credentials are stored in `.env` file (NOT in the database):

```env
ADMIN_EMAIL=admin@elasticdca.com
ADMIN_PASSWORD_HASH=$2b$12$...
ADMIN_KEY=a-long-random-secret-key-for-master-ea
JWT_SECRET=another-random-secret-for-jwt-tokens
```

- **Web Login:** Admin logs in with email + password → receives JWT token.
- **Master EA Auth:** Master EA sends `X-Admin-Key` header → validated against `ADMIN_KEY`.

### 10.2 User Registration & Login

**Registration Flow:**

1. User visits website → enters email, name, phone, password.
2. Server creates user with `status = 'pending'`, `email_verified = false`.
3. Server sends verification email with a token link.
4. User clicks link → `email_verified = true`, `status = 'active'` (or 'pending' until subscription).
5. User logs in → receives JWT token.

**Login Flow:**

1. `POST /api/auth/login` with `{email, password}`.
2. Server validates credentials → returns `{token, user}`.
3. Frontend stores JWT in localStorage/cookie.
4. All subsequent API calls include `Authorization: Bearer {token}`.

### 10.3 MetaID Management

- User enters their MT5 Account Number (MetaID) on the dashboard.
- `PATCH /api/user/meta-id` with `{mt5_id: "883921"}`.
- Server validates: must be numeric, must not be already claimed by another user.
- Stored in `users.mt5_id`.
- **One MT5 ID per user.** Updated anytime (old ID is released).

### 10.4 Subscription Lifecycle

```
[No Subscription] ──(PayPal payment)──► [Active]
       ▲                                     │
       │                               (end_date passes)
       │                                     │
       │                                     ▼
       └──────────────────────────── [Expired]
```

**PayPal Integration:**

1. User clicks "Subscribe" → redirected to PayPal.
2. PayPal processes payment → sends webhook to `POST /api/webhook/paypal`.
3. Server creates/updates subscription record: `status = 'active'`, `end_date = now + plan_duration`.
4. On each client EA ping, server checks: `subscription.end_date > now()`.

**Subscription Check (on client ping):**

```python
def is_subscription_active(user_id: int) -> bool:
    sub = db.query(Subscription).filter(
        Subscription.user_id == user_id,
        Subscription.status == 'active',
        Subscription.end_date > datetime.utcnow()
    ).first()
    return sub is not None
```

---

## 11. API Reference

### 11.1 Master EA Endpoints

#### `POST /api/master-tick`

**Auth:** `X-Admin-Key` header required.

**Request:**

```json
{
  "ask": 2030.5,
  "bid": 2030.1,
  "contract_size": 100.0
}
```

**Response:**

```json
{ "status": "ok" }
```

**Server Processing:** Runs the complete virtual execution engine (Section 7.7) for all tiers.

**Error Responses:**

- `401 Unauthorized`: Invalid admin key.
- `422 Validation Error`: Missing or invalid ask/bid.

---

### 11.2 Client EA Endpoints

#### `POST /api/client-ping`

**Auth:** None via header. mt5_id is the identifier. Subscription check is done server-side.

**Request:**

```json
{
  "mt5_id": "883921",
  "balance": 5200.0,
  "positions": [
    {
      "ticket": 1001,
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.01,
      "price": 2035.0,
      "profit": -5.0,
      "comment": "B1_a1b2c3d4_0"
    }
  ]
}
```

**Response (Success):**

```json
{
  "status": "ok",
  "tier": "4k-8k",
  "actions": [
    { "action": "BUY", "volume": 0.02, "comment": "B1_a1b2c3d4_1" },
    { "action": "CLOSE_ALL", "comment": "S2_oldoldol" }
  ]
}
```

**Response (No Actions):**

```json
{
  "status": "ok",
  "tier": "4k-8k",
  "actions": []
}
```

**Response (Errors):**

```json
{ "status": "error", "message": "Unknown account" }
{ "status": "expired", "message": "Subscription expired" }
{ "status": "banned", "message": "Account banned" }
{ "status": "no_tier", "message": "Balance outside configured ranges" }
{ "status": "no_meta_id", "message": "No MT5 ID configured" }
```

---

### 11.3 Auth Endpoints

#### `POST /api/auth/register`

```json
// Request
{ "email": "user@example.com", "name": "John Doe", "phone": "+1234567890", "password": "securepass" }

// Response (201)
{ "status": "ok", "message": "Verification email sent" }
```

#### `POST /api/auth/login`

```json
// Request
{ "email": "user@example.com", "password": "securepass" }

// Response (200)
{ "token": "eyJhb...", "user": { "id": 1, "email": "...", "name": "...", "role": "client", "mt5_id": "883921" } }
```

#### `POST /api/auth/verify-email`

```json
// Request
{ "token": "verification-token-from-email" }

// Response (200)
{ "status": "ok", "message": "Email verified" }
```

#### `POST /api/auth/forgot-password`

```json
{ "email": "user@example.com" }
```

#### `POST /api/auth/reset-password`

```json
{ "token": "reset-token", "new_password": "newsecurepass" }
```

---

### 11.4 Admin Endpoints

All admin endpoints require JWT with `role == 'admin'`.

#### `GET /api/admin/tiers`

List all tiers.

```json
// Response
{
  "tiers": [
    {
      "id": 1,
      "name": "1k-4k",
      "min_balance": 1000,
      "max_balance": 4000,
      "is_active": true
    },
    {
      "id": 2,
      "name": "4k-8k",
      "min_balance": 4000,
      "max_balance": 8000,
      "is_active": true
    }
  ]
}
```

#### `POST /api/admin/tiers`

Create a new tier.

```json
// Request
{ "name": "1k-4k", "min_balance": 1000, "max_balance": 4000 }

// Response (201)
{ "tier": { "id": 1, "name": "1k-4k", ... }, "grids_created": ["B1", "B2", "S1", "S2"] }
```

Creating a tier automatically creates 4 empty grid records in `tier_grids`.

#### `PUT /api/admin/tiers/{tier_id}`

Update tier metadata (name, balance range, active status).

#### `DELETE /api/admin/tiers/{tier_id}`

Delete a tier and all associated grids. **Only allowed if no active sessions.**

#### `GET /api/admin/tiers/{tier_id}/grids`

Get all 4 grid configs + runtime states for a tier.

```json
// Response
{
  "tier": { "id": 1, "name": "1k-4k" },
  "grids": [
    {
      "grid_id": "B1",
      "config": { "on": true, "cyclic": false, "start_limit": 0, "end_limit": 0, "tp_type": "fixed_money", "tp_value": 25, "rows": [...] },
      "runtime": { "session_id": "B1_a1b2c3d4", "is_active": true, "waiting_limit": false, "start_ref": 2050.00 }
    },
    { "grid_id": "B2", ... },
    { "grid_id": "S1", ... },
    { "grid_id": "S2", ... }
  ],
  "market": { "ask": 2030.50, "bid": 2030.10, "mid": 2030.30, "direction": "up" }
}
```

#### `PUT /api/admin/tiers/{tier_id}/grids/{grid_id}/config`

Update a specific grid's configuration (rows, TP, limits).

```json
// Request
{
  "start_limit": 2050.0,
  "end_limit": 1950.0,
  "tp_type": "fixed_money",
  "tp_value": 50.0,
  "rows": [
    { "index": 0, "dollar": 0, "lots": 0.01, "alert": false },
    { "index": 1, "dollar": 2.0, "lots": 0.02, "alert": true },
    { "index": 2, "dollar": 3.0, "lots": 0.03, "alert": false }
  ]
}
```

**Merge logic on update:**

- If a row is already executed (`executed == true`), its `dollar` and `lots` cannot be changed. Only `alert` can be toggled.
- New rows can be appended at the end.
- Non-executed rows can be freely edited.

#### `POST /api/admin/tiers/{tier_id}/grids/{grid_id}/control`

Toggle grid ON/OFF or cyclic.

```json
// Turn ON
{ "on": true }

// Turn OFF
{ "on": false }

// Toggle cyclic
{ "cyclic": true }
```

**Turning OFF behavior:**

1. If grid has active session: set `on = false`, clear session_id.
2. Clients detect stale session on next ping and close their trades.

**Turning ON behavior:**

1. Generate new session ID.
2. Follow Session Activation (Section 6.3).

#### `GET /api/admin/tiers/{tier_id}/clients`

List all clients currently assigned to this tier.

```json
// Response
{
  "clients": [
    {
      "user_id": 5,
      "name": "John Doe",
      "mt5_id": "883921",
      "balance": 5200.0,
      "last_seen": "2026-03-01T10:00:05",
      "connected": true,
      "position_count": 3
    }
  ]
}
```

`connected` is determined by: `last_seen` within the last 10 seconds.

#### `GET /api/admin/tiers/{tier_id}/clients/{user_id}/positions`

Get a specific client's current positions mapped to grid rows.

```json
// Response
{
  "user": { "name": "John Doe", "mt5_id": "883921", "balance": 5200.00 },
  "grids": {
    "B1": {
      "session_id": "B1_a1b2c3d4",
      "rows": [
        {
          "index": 0,
          "master_entry_price": 2050.00,
          "master_executed": true,
          "client_ticket": 1001,
          "client_entry_price": 2049.85,
          "client_lots": 0.01,
          "client_profit": -5.00
        },
        {
          "index": 1,
          "master_entry_price": 2048.00,
          "master_executed": true,
          "client_ticket": 1002,
          "client_entry_price": 2047.95,
          "client_lots": 0.02,
          "client_profit": -3.50
        },
        {
          "index": 2,
          "master_entry_price": 2045.00,
          "master_executed": true,
          "client_ticket": null,
          "client_entry_price": null,
          "client_lots": null,
          "client_profit": null
        }
      ],
      "total_client_profit": -8.50,
      "total_virtual_profit": -12.30
    },
    "S1": { ... },
    "B2": { ... },
    "S2": { ... }
  },
  "combined_profit": -15.20
}
```

**Row matching logic:**
For each executed master row, find the client position where `comment == f"{session_id}_{row.index}"`.

- If found: display client's actual trade data (ticket, price, profit).
- If NOT found: display `null` values — the client hasn't executed this row (late join or lag). **Do not show an error. Do not halt. Just omit data.**

#### `GET /api/admin/market`

Get current market state.

```json
{ "ask": 2030.50, "bid": 2030.10, "mid": 2030.30, "direction": "up", "history": [...] }
```

#### `GET /api/admin/users`

List all users with subscription status.

#### `PUT /api/admin/users/{user_id}`

Update user status (activate, ban, etc.).

#### `PUT /api/admin/users/{user_id}/subscription`

Manually extend or adjust subscription.

---

### 11.5 Client Dashboard Endpoints

All require JWT with `role == 'client'`.

#### `GET /api/client/dashboard`

Get the client's grid data and P&L.

```json
// Response
{
  "tier": { "name": "4k-8k" },
  "account": { "balance": 5200.00, "mt5_id": "883921" },
  "grids": {
    "B1": {
      "config": {
        "on": true,
        "session_id": "B1_a1b2c3d4",
        "tp_type": "fixed_money",
        "tp_value": 50.0
      },
      "rows": [
        {
          "index": 0,
          "dollar": 0,
          "lots": 0.01,
          "executed": true,
          "master_entry_price": 2050.00,
          "my_ticket": 1001,
          "my_entry_price": 2049.85,
          "my_profit": -5.00,
          "cumulative_profit": -5.00
        },
        {
          "index": 1,
          "dollar": 2.0,
          "lots": 0.02,
          "executed": true,
          "master_entry_price": 2048.00,
          "my_ticket": 1002,
          "my_entry_price": 2047.95,
          "my_profit": -3.50,
          "cumulative_profit": -8.50
        },
        {
          "index": 2,
          "dollar": 3.0,
          "lots": 0.03,
          "executed": false,
          "master_entry_price": null,
          "my_ticket": null,
          "my_entry_price": null,
          "my_profit": null,
          "cumulative_profit": null
        }
      ],
      "grid_total_profit": -8.50
    },
    "B2": { ... },
    "S1": { ... },
    "S2": { ... }
  },
  "combined_total_profit": -15.20,
  "market": { "mid": 2030.30, "direction": "up" }
}
```

**Data assembly logic:**

1. Load client's assigned tier → get all 4 grid configs + runtime.
2. Load client's latest snapshot (positions from last ping).
3. For each grid, for each executed row: match client position by comment string.
4. Calculate per-row profit from client's actual position data.
5. Sum cumulative profits per grid and combined.
6. If a row is executed on master but client has no matching position: `my_profit = null`. **Do not raise an error. Do not stop. Just skip.**

#### `GET /api/client/account`

```json
{
  "email": "user@example.com",
  "name": "John Doe",
  "phone": "+1234567890",
  "mt5_id": "883921",
  "subscription": { "status": "active", "end_date": "2026-04-01T00:00:00" }
}
```

#### `PATCH /api/client/account`

Update account fields (name, phone, mt5_id).

#### `PATCH /api/client/meta-id`

Update MT5 account number.

```json
{ "mt5_id": "883921" }
```

---

## 12. Admin Dashboard

### 12.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [HEADER BAR]                                                    │
│  Connection: ● CONNECTED  |  Mid: 2030.30 ▲  |  Ask/Bid        │
├─────────────────────────────────────────────────────────────────┤
│  [DROPDOWN 1: Tier Selector]  ▼  "4k-8k"                        │
│  [DROPDOWN 2: Client Viewer]  ▼  "John Doe (883921)" or "None" │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  BUY GRID 1 (B1)    │  │  SELL GRID 1 (S1)   │  ← Pair A    │
│  │  [Controls & Inputs] │  │  [Controls & Inputs] │              │
│  │  [Grid Table]        │  │  [Grid Table]        │              │
│  └─────────────────────┘  └─────────────────────┘               │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  BUY GRID 2 (B2)    │  │  SELL GRID 2 (S2)   │  ← Pair B    │
│  │  [Controls & Inputs] │  │  [Controls & Inputs] │              │
│  │  [Grid Table]        │  │  [Grid Table]        │              │
│  └─────────────────────┘  └─────────────────────┘               │
│                                                                  │
│  ┌──────────────────────────────────────────────┐               │
│  │  [COMBINED P&L SECTION]                       │               │
│  │  B1: -$8.50  |  S1: +$3.20  |  B2: $0  |  S2: -$1.00       │
│  │  TOTAL: -$6.30                                │               │
│  └──────────────────────────────────────────────┘               │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 12.2 Tier & Grid Management

**Dropdown 1 (Tier Selector):**

- Lists all tiers by name.
- On selection: loads that tier's 4 grid configs, runtime states, and market data.
- Admin can edit any grid for the selected tier.

**Dropdown 2 (Client Viewer):**

- Lists clients currently connected to the selected tier.
- "None" = show master virtual data only (default).
- On selecting a client: overlays that client's ACTUAL trade data onto the grid tables, showing:
  - Master entry price vs. Client entry price
  - Client's real P&L per row
  - Rows where client has no matching position (shown as empty/grey)

### 12.3 Per-Grid Controls (Above Each Grid Table)

```
┌─────────────────────────────────────────────────────────┐
│  BUY GRID 1   [ON/OFF Toggle]   [Cyclic Toggle]         │
│                                                          │
│  Start Limit: [_____]  End Limit: [_____]               │
│                                                          │
│  TP Mode: (●) Equity %  ( ) Balance %  ( ) Fixed $      │
│  TP Target: [_______]                                    │
│                                                          │
│  Session: B1_a1b2c3d4  |  Status: ACTIVE  |  3 Executed │
├─────────────────────────────────────────────────────────┤
│  │ Idx │ Gap($) │ Lots │ Alert │ Exec │ Price   │ P&L  ││
│  │  0  │  0.00  │ 0.01 │  ☐   │  ✓   │ 2050.00 │-$5   ││
│  │  1  │  2.00  │ 0.02 │  ☑   │  ✓   │ 2048.00 │-$3.5 ││
│  │  2  │  3.00  │ 0.03 │  ☐   │  ✓   │ 2045.00 │-$1.2 ││
│  │  3  │  4.00  │ 0.05 │  ☐   │  ✗   │   -     │  -   ││
│  │  4  │  5.00  │ 0.08 │  ☐   │  ✗   │   -     │  -   ││
│  │ ... │  ...   │ ...  │ ...  │ ...  │   ...   │ ...  ││
└─────────────────────────────────────────────────────────┘
```

**Grid table columns:**

| Column | Description                                                  |
| ------ | ------------------------------------------------------------ |
| Idx    | Row index (0-based)                                          |
| Gap($) | Dollar gap from previous level. Row 0 is always 0.00.        |
| Lots   | Volume for this level                                        |
| Alert  | Checkbox. Triggers audio alert on execution.                 |
| Exec   | ✓/✗ indicator. Server-managed.                               |
| Price  | Virtual entry price (from server) when executed. `-` if not. |
| P&L    | Virtual profit/loss for this row. `-` if not executed.       |

When a client is selected in Dropdown 2, extra columns appear:

| Column       | Description                            |
| ------------ | -------------------------------------- |
| Client Price | Actual entry price from client's trade |
| Client P&L   | Actual profit from client's broker     |
| Status       | `Synced` / `Missing` / `Stale`         |

### 12.4 Emergency Procedures

There is no dedicated emergency button. Admin manages risk by toggling individual grids OFF:

1. Turn off the desired grid(s) via ON/OFF switch.
2. Server clears the session immediately.
3. Clients detect stale session on next ping and close their trades (Scenario 4).
4. To shut down an entire tier: turn off all 4 grids one by one.

---

## 13. Client Dashboard

### 13.1 Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  [HEADER BAR]                                                    │
│  Status: CONNECTED  |  Tier: 4k-8k  |  Subscription: Active    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  BUY GRID 1 (B1)    │  │  SELL GRID 1 (S1)   │              │
│  │  Status: ACTIVE      │  │  Status: OFF         │              │
│  │  [Grid Table]        │  │  [Grid Table]        │              │
│  └─────────────────────┘  └─────────────────────┘               │
│                                                                  │
│  ┌─────────────────────┐  ┌─────────────────────┐               │
│  │  BUY GRID 2 (B2)    │  │  SELL GRID 2 (S2)   │              │
│  │  Status: OFF         │  │  Status: OFF         │              │
│  │  [Grid Table]        │  │  [Grid Table]        │              │
│  └─────────────────────┘  └─────────────────────┘               │
│                                                                  │
│  ┌──────────────────────────────────────────────┐               │
│  │  MY TOTAL P&L: -$8.50                         │               │
│  │  B1: -$8.50 | S1: $0.00 | B2: $0.00 | S2: $0.00            │
│  └──────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
```

### 13.2 Grid Viewer (Read-Only)

Client sees the SAME grid table as admin but:

- **ALL inputs are disabled.** Client cannot edit anything.
- **No control toggles.** ON/OFF, cyclic, etc. are admin-only.
- **P&L shows client's actual profit** (from their MT5 positions), not the virtual P&L.
- Rows where client has no matching position: P&L column shows `-` (no error, no warning).

### 13.3 P&L Display

- **Per-grid P&L:** Sum of client's actual profits for all positions matching that grid's session.
- **Combined P&L:** Sum across all 4 grids.
- **Cumulative P&L per row:** Running total down the grid (row 0 P&L, row 0+1 P&L, row 0+1+2 P&L, etc.).
- Updated every 1 second via polling (same as admin dashboard).

### 13.4 Account Management Page

- View/edit: Name, Phone, MT5 ID.
- View (read-only): Email (change requires email verification flow), Subscription status, Expiry date.
- **NOT editable:** Subscription dates (managed via PayPal), Created at.

---

## 14. Edge Cases & Error Handling

### 14.1 Network Failures

| Scenario                               | Behavior                                                                                                       |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Master EA loses connection             | Grid state freezes. No new rows execute. Clients get empty `actions[]`. System resumes when Master reconnects. |
| Client EA loses connection             | Client's positions stay open. On reconnect, sync protocol catches up (Scenario 3).                             |
| Server crashes                         | On restart, state is restored from PostgreSQL. Master and Client EAs retry automatically.                      |
| Client EA slow (> 3 sec between pings) | No issue. Client just syncs less frequently.                                                                   |

### 14.2 Balance Fluctuation Mid-Session

- **Rule:** Tier is locked while any grid has an active session for the client.
- **Scenario:** User starts in "4k-8k" tier. Balance drops to $3,500 during active trading.
- **Behavior:** Client remains in "4k-8k" tier until ALL sessions are cleared.
- **After all sessions clear:** Next ping re-evaluates balance. If $3,500 → assigned to "1k-4k" tier.

### 14.3 Multiple Clients in Same Tier

- All clients in a tier receive the SAME grid signals.
- Each client's sync is independent. Client A may be caught up while Client B is still syncing row 2.
- The server handles each client ping individually. No client-to-client interference.

### 14.4 Client Positions from Unknown Source

If a client's positions include trades with comments that DON'T match any known grid pattern (e.g., manually opened trades, trades from other EAs):

- **Server ignores them completely.** Only positions matching the regex `^(B[12]|S[12])_[0-9a-fA-F]{8}_\d+$` are considered.
- This allows clients to run other EAs or trade manually alongside the slave EA.

### 14.5 Client Opens Trades with Wrong Comment

If somehow a position has a comment like `B1_a1b2c3d4_5` but the session hash or grid doesn't match the current state:

- Treated as a stale session (Scenario 4) → server tells client to close it.
- Not a critical error. No system halt.

### 14.6 Race Condition: Row Executes While Client is Processing Previous Action

- Client ping at T=0: Gets action to open row 1.
- Master tick at T=0.5: Row 2 triggers.
- Client ping at T=1: Has row 0+1, master has rows 0+1+2 → Client gets action for row 2.
- **No issue.** Sequential sync naturally handles this via catchup (Scenario 3).

### 14.7 Admin Changes Grid Config While Session is Active

**Editing rows:**

- Executed rows: `dollar` and `lots` are locked. Only `alert` can change.
- Non-executed rows: All fields editable. This includes rows that are "next" in queue.
- Adding new rows at the end: Allowed at any time.
- Removing rows: Only non-executed rows can be removed. Executed rows persist until session ends.

**Changing limits/TP:**

- `start_limit`: Only effective when starting a new session. Ignored if already active.
- `end_limit`: Takes effect immediately. If end_limit is set to a price that's already breached, expansion stops.
- `tp_value` / `tp_type`: Takes effect immediately. Next TP check uses new values.

### 14.8 Master EA Sends Stale/Duplicate Prices

- If `ask` and `bid` are identical to the previous tick, the server still processes (for TP checks).
- No deduplication needed. The engine is idempotent — processing the same price twice won't cause double execution (already-executed rows stay executed).

### 14.9 What Happens When Subscription Expires Mid-Trade

- Client has open positions from an active grid session.
- Subscription expires.
- **Next ping:** Server returns `{"status": "expired"}`.
- **Client EA behavior:** Stops requesting new actions. Does NOT auto-close existing positions (that would be dangerous).
- **Open positions remain until:**
  - Admin turns off the grid → session clears → client detects stale session and closes (but expired client won't receive the update).
  - Client manually closes in MT5.
  - **Recommendation:** Client EA should include a configurable option: "Close positions on subscription expiry: YES/NO." Default: NO.

### 14.10 Client Tries to Open Trade but Broker Rejects

- E.g., insufficient margin, market closed, etc.
- **Client EA:** Logs the error. Does NOT crash. On next ping, server will again instruct the same action (row is still executed on master but client is missing it).
- **Result:** Client will keep retrying every ping until successful or until the session changes.
- **Dashboard:** The row will show "Missing" status for that client.

### 14.11 Admin Creates Overlapping Tier Ranges

- E.g., Tier A: 1k-5k, Tier B: 4k-8k → $4,500 is in both.
- **Prevention:** Server validates tier creation/update. Balance ranges must NOT overlap. Return 400 error if overlap detected.

### 14.12 Zero Rows Configured in a Grid

- Admin turns on a grid that has no rows with valid `dollar > 0` (except row 0 with dollar=0).
- **Behavior:** Row 0 executes immediately (gap=0). Then nothing more happens (no row 1 with a gap to cross).
- This is a valid use case: a single entry with no DCA layers.

### 14.13 Concurrent Master Ticks

- If two master ticks arrive within the same processing window (unlikely but possible):
- Use a lock/mutex on the grid processing to prevent double-execution of the same row.
- `asyncio.Lock()` per tier is sufficient for FastAPI.

---

## 15. Development Phases

### Phase 1: Core Backend + Master EA

**Goal:** Master EA feeds prices → Server calculates virtual grid for all tiers → State persisted to PostgreSQL.

**Deliverables:**

1. Master EA (MQL5): Simplified data feeder. Sends `{ask, bid}` with `X-Admin-Key`.
2. Server: FastAPI app with:
   - `POST /api/master-tick` endpoint
   - In-memory tier state loaded from PostgreSQL on startup
   - Virtual grid execution engine (all 4 grids per tier)
   - State persistence to DB on every change
   - `GET /api/admin/tiers/{id}/grids` for testing
3. Database: PostgreSQL with `tiers`, `tier_grids`, `market_state` tables.
4. Admin can manually create tiers and configure grids via direct API calls (curl/Postman).

**Testing:** Verify grid rows execute correctly as price crosses levels. Verify TP triggers. Verify cyclic restart.

### Phase 2: Authentication + User Management

**Goal:** Login system for admin and clients.

**Deliverables:**

1. Database: `users`, `subscriptions` tables.
2. Server endpoints: Register, Login, Email verification, Password reset.
3. JWT token generation and middleware.
4. Admin: `.env` credentials. Can manage users via API.
5. **No PayPal yet.** Admin manually creates/extends subscriptions.

**Testing:** Register user, login, get JWT, access protected endpoints.

### Phase 3: Client EA + Sync Protocol

**Goal:** Client EAs poll server, receive trade instructions, execute.

**Deliverables:**

1. Client EA (MQL5): Sends `{mt5_id, balance, positions[]}`, processes `actions[]` array.
2. Server: `POST /api/client-ping` endpoint with full sync logic (5 scenarios).
3. Database: `user_snapshots` table for latest client data.
4. Tier assignment logic (balance-range routing with locking).

**Testing:** Connect multiple test clients to same tier. Verify sync across all scenarios. Test late join, session mismatch, catchup.

### Phase 4: Web Dashboard (Client + Admin)

**Goal:** Full web UI for admin grid management and client P&L viewing.

**Deliverables:**

1. Admin Dashboard: Tier selector, 4-grid controller, user monitor, client viewer.
2. Client Dashboard: Read-only grid view, P&L display, account management.
3. All dashboard API endpoints from Section 11.
4. Real-time polling (1 second intervals).
5. Alert system (audio beep when alert rows execute).

**Testing:** Visual verification. Match dashboard data to actual MT5 positions. Test with multiple tiers and clients.

### Phase 5: PayPal Integration + Polish

**Goal:** Self-service subscription management.

**Deliverables:**

1. PayPal REST API or Standard integration.
2. `POST /api/webhook/paypal` endpoint for payment events.
3. Pricing page on website.
4. Automatic subscription creation/renewal/cancellation.
5. Email notifications (welcome, subscription expiring, expired).
6. Performance optimization, error logging, monitoring.

---

## 16. Cross-Check & Validation Matrix

This section validates that every feature mentioned in the requirements is addressed.

### 16.1 Requirements from prompt.txt

| Requirement                                           | Section          | Status                         |
| ----------------------------------------------------- | ---------------- | ------------------------------ |
| 4 grids: 2 buy, 2 sell                                | 5.1              | ✅ B1, B2, S1, S2              |
| Grids divided by account balance range                | 4.1              | ✅ Balance Tier System         |
| 4 grids combined as one range (tier)                  | 4.1, 5.1         | ✅ Each tier has all 4 grids   |
| Per-grid ON/OFF                                       | 5.3.1            | ✅ Independent toggle per grid |
| Per-grid Cyclic Run                                   | 5.3.1            | ✅ Independent cyclic per grid |
| Per-grid start_limit                                  | 5.3.2            | ✅ Anchor price per grid       |
| Per-grid end_limit                                    | 5.3.2, 7.4       | ✅ Safety boundary per grid    |
| Per-grid risk management                              | 12.4             | ✅ Admin toggles grids OFF     |
| Per-grid TP (equity/balance/fixed + value)            | 5.3.3, 7.6       | ✅ Three TP types per grid     |
| Grid row data: index, dollar, lots, alert, executed   | 5.4              | ✅ Full row structure          |
| First row gap = 0, non-editable, executes immediately | 5.5              | ✅ Documented                  |
| Unique ID per grid and session                        | 6.1              | ✅ `{GRID_ID}_{8_HEX}` format  |
| Use market feed to mark rows as executed              | 7.1              | ✅ Virtual execution engine    |
| Don't care about actual trade execution               | 7.1              | ✅ Pure virtual tracking       |
| Master EA: data feed only                             | 3.1              | ✅ No trade execution          |
| Client EA: ping with mt5_id, balance, positions       | 3.3, 8.1         | ✅ Full payload defined        |
| Subscription validation on every ping                 | 8.2              | ✅ Auth flow documented        |
| Balance-range tier routing                            | 8.3              | ✅ With locking                |
| Scenario: 2+ rows executed, client has 0 → skip       | 8.4 Scenario 1   | ✅                             |
| Scenario: 1 row executed → fresh entry                | 8.4 Scenario 2   | ✅                             |
| Scenario: new session → close old, start new          | 8.4 Scenario 3/4 | ✅                             |
| Client dashboard: read-only, shows master grids       | 13.2             | ✅                             |
| Client dashboard: actual P&L from client trades       | 13.3             | ✅                             |
| Match trades by unique ID (grid + session + index)    | 8.6              | ✅ Comment format defined      |
| Missing rows → don't show P&L, don't error            | 13.2, 14.10      | ✅ Graceful nulls              |
| Admin dashboard: tier dropdown                        | 12.2             | ✅                             |
| Admin dashboard: client dropdown per tier             | 12.2             | ✅                             |
| Admin dashboard: client P&L view                      | 12.4, 11.4       | ✅                             |
| Login system                                          | 10.2             | ✅ JWT-based                   |
| User data: email, phone, name, password, mt5_id, etc. | 9.1              | ✅ Full schema                 |
| Everything updatable except created_at, subscription  | 10.3, 13.4       | ✅                             |
| Phase 2: Login system, DB, user management            | 15 Phase 2       | ✅                             |
| Phase 3: Client EA sync                               | 15 Phase 3       | ✅                             |
| Phase 4: Client dashboard                             | 15 Phase 4       | ✅                             |
| Phase 5: Admin dashboard with dropdowns               | 15 Phase 4       | ✅                             |

### 16.2 Requirements from saas.md

| Requirement                         | Section          | Status                   |
| ----------------------------------- | ---------------- | ------------------------ |
| Email verification                  | 10.2             | ✅                       |
| Email notifications                 | 15 Phase 5       | ✅                       |
| PayPal integration                  | 10.4, 15 Phase 5 | ✅                       |
| MetaID-based auth (no license keys) | 10.3             | ✅                       |
| On-chart panel in Client EA         | 3.3              | ✅                       |
| Slippage tolerance in Client EA     | 3.3              | ✅ (InpSlippage)         |
| Safety mode on EA disconnect        | 14.1             | ✅ (Positions stay open) |

### 16.3 Consistency Checks Against Current Codebase

| Current Feature (v3.4.2)              | New System Equivalent                              | Breaking Change?          |
| ------------------------------------- | -------------------------------------------------- | ------------------------- |
| `buy_on` / `sell_on` flags            | Per-grid `on` flag (×4)                            | Yes: restructured         |
| `buy_id` / `sell_id` session hashes   | Per-grid `session_id` (×4)                         | Yes: new format `B1_xxx`  |
| `rows_buy` / `rows_sell` arrays       | Per-grid `rows` array (×4)                         | Yes: 4 independent arrays |
| `buy_exec_map` / `sell_exec_map`      | `executed` flag + metadata on row itself           | Yes: simplified           |
| `buy_tp_type/value`                   | Per-grid `tp_type/value` (×4)                      | Yes: 4 independent sets   |
| `buy_hedge_value`                     | Removed — admin manages risk manually              | Yes: feature removed      |
| `buy_limit_price`                     | Per-grid `start_limit` (×4)                        | Yes: renamed + per-grid   |
| `TRADE_ID_PATTERN` regex              | New pattern: `^(B[12]\|S[12])_[0-9a-fA-F]{8}_\d+$` | Yes: updated              |
| `state.json` persistence              | PostgreSQL JSONB columns                           | Yes: database-backed      |
| Single admin EA executes trades       | Master EA is data-only; clients execute            | Yes: fundamental shift    |
| `IronClad` auto-hedge (open opposite) | Removed — admin manages risk manually              | Yes: feature removed      |
| `cyclic_on` (global)                  | Per-grid `cyclic` flag                             | Yes: independent per grid |
| `emergency_close` (global)            | Removed — admin turns off grids manually           | Yes: feature removed      |

### 16.4 Flow Integrity Validation

**Test Case 1: Fresh start, single client**

1. Admin creates tier "4k-8k" with B1 configured (5 rows). ✅
2. Admin turns B1 ON. Row 0 executes immediately (gap=0). ✅
3. Client with $5000 balance connects. Assigned to "4k-8k". ✅
4. Client has 0 positions. Grid has 1 executed row → Scenario 2 → Client gets `BUY row 0`. ✅
5. Price drops. Server marks row 1 executed. ✅
6. Client pings. Has row 0, grid has rows 0+1 → Scenario 3 → Client gets `BUY row 1`. ✅
7. Price drops more. Rows 2, 3, 4 execute over time. Client catches up 1 per ping. ✅
8. Virtual P&L hits TP target. Server immediately swaps to new session (cyclic) or turns grid off (non-cyclic). ✅
9. Client pings with old session_id → Scenario 4 → closes old positions. ✅
10. If cyclic ON: new session already running. Row 0 executed. Client gets Scenario 2 for new session. ✅

**Test Case 2: Late joiner**

1. Grid B1 has been running. Rows 0, 1, 2, 3 executed. ✅
2. New client connects. Has 0 positions for B1. ✅
3. Grid has 4 executed rows (≥ 2) → Scenario 1 → SKIP. Client waits. ✅
4. Admin closes B1 (TP hit). Cyclic restarts new session. Row 0 executes. ✅
5. Now grid has 1 executed row → Scenario 2 → Client joins new session. ✅

**Test Case 3: Admin turns off active grid**

1. B1 running, 3 rows executed. Virtual P&L = -$75. ✅
2. Admin decides to cut risk and turns B1 OFF. ✅
3. Server clears session_id, sets `on = false`. ✅
4. Client pings with old session_id → Scenario 4 → closes positions. ✅
5. Grid is now OFF. No new session starts (regardless of cyclic setting). ✅
6. Admin can turn B1 back ON later to start fresh. ✅

**Test Case 4: End limit hit**

1. B1 running, start_ref = 2050. Rows executing as price drops. ✅
2. end_limit = 1980. Price drops to 1978. ✅
3. Next row target is 1975 → but ask (1978) < end_limit (1980) → expansion paused. ✅
4. Price recovers to 1985 → above end_limit → expansion resumes. ✅
5. Existing executed rows unaffected throughout. ✅

**Test Case 5: Multi-tier, multi-client**

1. Tier A ("1k-4k"): Client X ($2000). Tier B ("4k-8k"): Client Y ($6000). ✅
2. Same master price feed. Both tiers process independently. ✅
3. Tier A grid B1 has different rows (smaller lots) than Tier B grid B1. ✅
4. Client X receives actions based on Tier A state. Client Y based on Tier B. ✅
5. No interference between tiers or clients. ✅

---

**END OF BLUEPRINT v4**

This document covers every component, every scenario, every edge case, and every API endpoint needed to build the Elastic DCA Cloud SaaS platform. Each section can be used as a direct implementation guide by developers.
