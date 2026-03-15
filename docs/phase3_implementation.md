# Phase 3 Implementation — Client EA Sync + Dashboard

**Version:** `4.0.0-phase3`  
**Blueprint:** `docs/saas_blueprint_v4.md` — Sections 3.3, 8, 9.5, 11.2, 11.4, 11.5, 13, 14, 15

---

## Overview

Phase 3 adds the **Client EA Sync Protocol** — the mechanism by which each client's MetaTrader 5 Expert Advisor stays synchronized with the server's virtual grid execution state. It also adds the **Client Dashboard** endpoint and **Admin Tier-Client** endpoints for monitoring.

### Scope

| Deliverable | Blueprint Section | Status |
|---|---|---|
| Sync engine (6 scenarios) | 8.1–8.8 | ✅ |
| POST `/api/client-ping` | 11.2 | ✅ |
| Client dashboard endpoint | 11.5, 13 | ✅ |
| Admin tier-client endpoints | 11.4 | ✅ |
| user_snapshots persistence | 9.5 | ✅ |
| Edge cases (14.x) | 14.2–14.10 | ✅ |

### Files Changed/Created

| File | Lines | Change |
|---|---|---|
| `app/sync.py` | 218 | **NEW** — Sync engine |
| `app/routes/ping.py` | 118 | **NEW** — Client-ping endpoint |
| `app/routes/client.py` | 246 | Extended — Added dashboard |
| `app/routes/admin.py` | 573 | Extended — Added tier-client endpoints |
| `app/database.py` | 747 | Extended — 5 new functions |
| `app/models.py` | 274 | Extended — 3 new models |
| `main.py` | 86 | Updated — Version bump, ping router |

---

## 1. Sync Engine (`app/sync.py`)

The sync engine implements the core logic from Blueprint Section 8.4. It compares each client's reported positions against the server's virtual grid state and produces actions.

### 1.1 Comment Format

Trade comments follow the format `{GRID_ID}_{8_HEX}_{ROW_INDEX}`:
- Example: `B1_a1b2c3d4_0` → grid_id=`B1`, session_id=`B1_a1b2c3d4`, row_index=`0`
- Regex: `^(B[12]|S[12])_[0-9a-fA-F]{8}_(\d+)$`
- Non-matching comments are silently ignored (Section 14.4)

### 1.2 The 6 Sync Scenarios

The `compute_sync_actions()` function iterates all 4 grids and applies:

| # | Scenario | Condition | Action |
|---|---|---|---|
| 1 | **Late Join** | Grid has ≥2 executed rows, client has 0 | Skip (wait for new session) |
| 2 | **Fresh Join** | Grid has exactly 1 executed row, client has 0 | `BUY`/`SELL` row 0 |
| 3 | **Catchup** | Client has fewer rows than grid | `BUY`/`SELL` first missing row (one per ping) |
| 4 | **Session Mismatch** | Client has positions from old session | `CLOSE_ALL` stale session |
| 5 | **Grid OFF Orphans** | Grid is OFF, client has positions | `CLOSE_ALL` orphan session |
| 6 | **In Sync** | Client row count ≥ grid executed count | No action |

### 1.3 Action Ordering (Section 8.7)

Actions are returned sorted: `CLOSE_ALL` first, then `BUY`/`SELL`. This ensures stale positions are cleaned before new ones are opened.

### 1.4 Tier Finding (Section 8.3)

`find_tier_for_balance()` finds the tier where `min_balance ≤ balance < max_balance`, skipping inactive tiers.

### 1.5 Tier Locking (Section 8.3, 14.2)

`client_has_active_session_trades()` checks if the client holds any positions with comments matching a current active session. If true, the tier assignment is **locked** — balance fluctuations won't reassign the client to a different tier mid-session.

---

## 2. Client-Ping Endpoint (`app/routes/ping.py`)

### POST `/api/client-ping`

**Auth:** None via header. Client is identified by `mt5_id` in the request body.

**Request body (Section 8.1):**
```json
{
  "mt5_id": "883921",
  "balance": 5000.0,
  "positions": [
    {
      "ticket": 1001,
      "symbol": "XAUUSD",
      "type": "BUY",
      "volume": 0.01,
      "price": 2050.50,
      "profit": -2.0,
      "comment": "B1_a1b2c3d4_0"
    }
  ]
}
```

**Processing flow (Section 8.2):**

1. **Lookup** — Find user by `mt5_id` → "Unknown account" if not found
2. **Status check** — "banned" if banned, "error" if not active
3. **Subscription check** — "expired" if subscription not active
4. **Save snapshot** — Upsert into `user_snapshots` table (balance + positions JSONB)
5. **Tier assignment** — With locking logic:
   - If client has active session trades → stay in current tier (locked)
   - Otherwise → re-evaluate balance against tier ranges
   - If no tier matches → "no_tier"
6. **Compute sync** — Run `compute_sync_actions()` for all 4 grids
7. **Return actions** — `CLOSE_ALL` first, then `BUY`/`SELL`

**Response format (Section 8.5):**
```json
{
  "status": "ok",
  "tier": "4k-8k",
  "actions": [
    {"action": "CLOSE_ALL", "comment": "B1_deadbeef"},
    {"action": "BUY", "volume": 0.02, "comment": "B1_a1b2c3d4_1"}
  ]
}
```

**Error status codes:**
- `"error"` — Unknown account, account not active
- `"banned"` — Account banned
- `"expired"` — Subscription expired
- `"no_tier"` — Balance outside all configured tier ranges

---

## 3. Client Dashboard (`app/routes/client.py`)

### GET `/api/client/dashboard`

**Auth:** JWT with `role=client`

Returns a comprehensive view of the client's trading state, matching their actual positions against the master's virtual execution.

**Response structure (Section 13):**
```json
{
  "tier": {"name": "4k-8k"},
  "account": {"balance": 5200.0, "mt5_id": "883921"},
  "grids": {
    "B1": {
      "config": {"on": true, "session_id": "B1_a1b2c3d4", "tp_type": "fixed_money", "tp_value": 500.0},
      "rows": [
        {
          "index": 0, "dollar": 0.0, "lots": 0.01, "executed": true,
          "master_entry_price": 2050.50,
          "my_ticket": 1001, "my_entry_price": 2050.50, "my_profit": -2.0,
          "cumulative_profit": -2.0
        },
        {
          "index": 1, "dollar": 2.0, "lots": 0.02, "executed": false,
          "master_entry_price": null,
          "my_ticket": null, "my_entry_price": null, "my_profit": null,
          "cumulative_profit": null
        }
      ],
      "grid_total_profit": -2.0
    }
  },
  "combined_total_profit": -2.0,
  "market": {"mid": 2050.30, "direction": "neutral"}
}
```

**Key behaviors:**
- Shows **all rows** (executed + non-executed) — not just executed ones
- Position matching by comment: `{session_id}_{row_index}`
- Missing positions → `null` values (no error, per Section 14.10)
- P&L is from client's **actual** broker positions, not virtual calculations
- `cumulative_profit` is a running total of matched positions only
- If no tier assigned → returns minimal response with `tier: null`

---

## 4. Admin Tier-Client Endpoints (`app/routes/admin.py`)

### GET `/api/admin/tiers/{tier_id}/clients`

**Auth:** JWT with `role=admin`

Lists all clients assigned to a specific tier.

**Response:**
```json
{
  "clients": [
    {
      "user_id": 14,
      "name": "Client One",
      "mt5_id": "883921",
      "balance": 5200.0,
      "last_seen": "2026-03-01T08:46:11",
      "connected": true,
      "position_count": 1
    }
  ]
}
```

- `connected` = `true` if `last_seen` is within 10 seconds (approximates live EA connection)
- `position_count` = number of positions in the client's latest snapshot

### GET `/api/admin/tiers/{tier_id}/clients/{user_id}/positions`

**Auth:** JWT with `role=admin`

Detailed comparison of master grid state vs. client's actual positions for each grid.

**Response:**
```json
{
  "user": {"name": "Client One", "mt5_id": "883921", "balance": 5200.0},
  "grids": {
    "B1": {
      "session_id": "B1_a1b2c3d4",
      "rows": [
        {
          "index": 0,
          "master_entry_price": 2050.50,
          "master_executed": true,
          "client_ticket": 1001,
          "client_entry_price": 2050.50,
          "client_lots": 0.01,
          "client_profit": -2.0
        }
      ],
      "total_client_profit": -2.0,
      "total_virtual_profit": -0.4
    }
  },
  "combined_profit": -2.0
}
```

- Only **executed** master rows are shown
- Each row shows both master and client data side by side
- `total_virtual_profit` = server's calculated P&L using current market prices
- `total_client_profit` = sum of client's actual broker P&L

---

## 5. Database Functions (`app/database.py`)

Five new async functions added:

| Function | Line | Purpose |
|---|---|---|
| `get_user_by_mt5_id(mt5_id)` | 642 | Look up user by MT5 account ID |
| `upsert_user_snapshot(user_id, balance, positions)` | 654 | INSERT or UPDATE snapshot (balance + positions JSONB) |
| `get_user_snapshot(user_id)` | 672 | Retrieve latest snapshot |
| `get_clients_by_tier(tier_id)` | 694 | JOIN users + snapshots, calculate connected status |
| `update_user_tier(user_id, tier_id)` | 740 | Set or clear assigned_tier_id |

### user_snapshots Table (Section 9.5)

```sql
CREATE TABLE IF NOT EXISTS user_snapshots (
    user_id    INTEGER PRIMARY KEY REFERENCES users(id),
    equity     DECIMAL(15,2),
    balance    DECIMAL(15,2),
    positions  JSONB DEFAULT '[]',
    last_seen  TIMESTAMP DEFAULT NOW()
);
```

- One row per user (upsert on conflict)
- `positions` stores the full array of Position objects as JSONB
- `last_seen` updated on every ping

---

## 6. Pydantic Models (`app/models.py`)

Three new models added:

```python
class Position(BaseModel):
    ticket: int
    symbol: str
    type: str          # "BUY" or "SELL"
    volume: float
    price: float
    profit: float
    comment: str

class ClientPingRequest(BaseModel):
    mt5_id: str
    balance: float
    positions: list[Position] = []

class SyncAction(BaseModel):
    action: str        # "BUY", "SELL", or "CLOSE_ALL"
    volume: float | None = None
    comment: str       # session_id for CLOSE_ALL, or session_id_rowIndex for trades
```

---

## 7. Cross-Check Summary

### Confirmed Correct (14 major areas)

- All 6 sync scenarios match blueprint Section 8.4 ✓
- Comment regex matches format (Section 8.6) ✓
- Action ordering: CLOSE_ALL first (Section 8.7) ✓
- user_snapshots schema (Section 9.5) ✓
- Client-ping auth flow (Section 8.2) ✓
- Tier assignment with locking (Section 8.3) ✓
- Ping response format (Section 8.5, 11.2) ✓
- Admin tier client list (Section 11.4) ✓
- Admin client positions (Section 11.4) ✓
- Client dashboard: all rows shown (Section 13) ✓
- P&L from actual positions, not virtual (Section 13.2) ✓
- Missing positions → null, no error (Section 14.10) ✓
- Unknown comments ignored (Section 14.4) ✓
- Disconnect/reconnect handled naturally (Section 8.8) ✓

### Minor Notes

1. **Blueprint heading inconsistency**: Section 8.4 heading says "3 scenarios" but describes 6. Code correctly implements all 6.
2. **`equity` column**: Present in schema but not populated (blueprint doesn't include equity in ping payload). Reserved for future use.
3. **Scenario 5 condition**: Code also handles `grid_on and no session_id` (defensive improvement over blueprint).

---

## Bug Fixed During Testing

**`calculate_virtual_pnl()` call signature** — The admin positions endpoint was calling `calculate_virtual_pnl(config, market)` instead of `calculate_virtual_pnl(config, bid, ask, contract_size)`. Fixed by passing individual market parameters.
