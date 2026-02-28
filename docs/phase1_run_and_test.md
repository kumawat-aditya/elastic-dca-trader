# Phase 1 — Run & Test Guide

**Project:** Elastic DCA Trading SaaS  
**Phase:** 1 — Core Backend + Master EA

---

## 1. Prerequisites

| Requirement       | Minimum Version | Check Command                  |
| ----------------- | --------------- | ------------------------------ |
| Python            | 3.12+           | `python3 --version`            |
| PostgreSQL        | 15+             | `psql --version` or use Docker |
| Docker (optional) | 20+             | `docker --version`             |
| curl              | any             | `curl --version`               |

---

## 2. Setup

### 2.1 Clone & Navigate

```bash
cd Elastic_DCA_Trading/apps/server
```

### 2.2 Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2.3 Install Dependencies

```bash
pip install -r requirements.txt
```

### 2.4 Start PostgreSQL

**Option A: Docker (recommended)**

```bash
docker run -d \
  --name elastic_dca_pg \
  -e POSTGRES_USER=elastic_dca \
  -e POSTGRES_PASSWORD=elastic_dca_pass \
  -e POSTGRES_DB=elastic_dca \
  -p 5432:5432 \
  postgres:16-alpine
```

**Option B: Local PostgreSQL**

```sql
CREATE USER elastic_dca WITH PASSWORD 'elastic_dca_pass';
CREATE DATABASE elastic_dca OWNER elastic_dca;
```

### 2.5 Configure Environment

```bash
cp .env.example .env
# Edit .env if needed:
#   DATABASE_URL=postgresql://elastic_dca:elastic_dca_pass@localhost:5432/elastic_dca
#   ADMIN_KEY=test_admin_key_12345
#   HOST=0.0.0.0
#   PORT=8000
```

### 2.6 Start Server

```bash
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info
```

Expected output:

```
INFO:     Started server process
INFO:     Waiting for application startup.
... Loaded 0 tier(s) into memory.
... Market state loaded: ask=0.00000 bid=0.00000 contract_size=0.00
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2.7 Verify Health

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok","version":"4.0.0-phase1"}`

---

## 3. Test Scenarios

Set these shell variables for convenience:

```bash
ADMIN_KEY="test_admin_key_12345"
BASE="http://localhost:8000"
```

---

### Test 1: Authentication

**Reject invalid key:**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: wrong_key" \
  -H "Content-Type: application/json" \
  -d '{"ask":2050,"bid":2049.50,"contract_size":100}'
```

Expected: `{"detail":"Invalid admin key"}`

**Reject missing key:**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "Content-Type: application/json" \
  -d '{"ask":2050,"bid":2049.50,"contract_size":100}'
```

Expected: `{"detail":"Missing X-Admin-Key header"}`

---

### Test 2: Tier CRUD

**Create tier:**

```bash
curl -s -X POST $BASE/api/admin/tiers \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"4k-8k","symbol":"XAUUSD","min_balance":4000,"max_balance":8000}'
```

Expected: Tier created with 4 grids (`B1, B2, S1, S2`). Note the tier `id` from the response.

**List tiers:**

```bash
curl -s $BASE/api/admin/tiers -H "X-Admin-Key: $ADMIN_KEY"
```

**Overlap rejection:**

```bash
curl -s -X POST $BASE/api/admin/tiers \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"overlap","symbol":"XAUUSD","min_balance":5000,"max_balance":10000}'
```

Expected: `400` error about overlapping range.

**Update tier:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/1 \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"4k-8k-updated"}'
```

**Delete tier (only when no active sessions):**

```bash
curl -s -X DELETE $BASE/api/admin/tiers/1 \
  -H "X-Admin-Key: $ADMIN_KEY"
```

---

### Test 3: Grid Configuration

Replace `{TIER_ID}` with the actual tier ID from Test 2.

**Configure B1 with 5 rows:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/B1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "tp_type": "fixed_money",
    "tp_value": 25.0,
    "start_limit": 0,
    "end_limit": 0,
    "rows": [
      {"index":0, "dollar":0, "lots":0.01, "alert":false},
      {"index":1, "dollar":2, "lots":0.02, "alert":false},
      {"index":2, "dollar":3, "lots":0.04, "alert":false},
      {"index":3, "dollar":4, "lots":0.06, "alert":false},
      {"index":4, "dollar":5, "lots":0.08, "alert":false}
    ]
  }'
```

**View all grids:**

```bash
curl -s $BASE/api/admin/tiers/{TIER_ID}/grids -H "X-Admin-Key: $ADMIN_KEY"
```

---

### Test 4: Basic Grid Lifecycle (Row Execution + TP)

**Step 1: Send a master tick**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2050.00, "bid":2049.50, "contract_size":100}'
```

**Step 2: Verify market state**

```bash
curl -s $BASE/api/admin/market -H "X-Admin-Key: $ADMIN_KEY"
```

Expected: `ask: 2050.0, bid: 2049.5, contract_size: 100.0`

**Step 3: Turn ON B1**

```bash
curl -s -X POST $BASE/api/admin/tiers/{TIER_ID}/grids/B1/control \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"on": true}'
```

Expected: Session created (e.g., `B1_a1b2c3d4`). Check logs for:

```
[ACTIVATE] Grid B1 → ACTIVE (start_ref=2050.00000) Row 0 executed.
```

**Step 4: Verify Row 0 executed**

```bash
curl -s $BASE/api/admin/tiers/{TIER_ID}/grids -H "X-Admin-Key: $ADMIN_KEY"
```

Check: Row 0 `executed: true`, `entry_price: 2050.0`, `start_ref: 2050.0`

**Step 5: Drop price to trigger Row 1 (target = 2050 − 2 = 2048)**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2048.00, "bid":2047.50, "contract_size":100}'
```

Verify Row 1: `executed: true`, `entry_price: 2048.0`

**Step 6: Drop further to trigger Row 2 (target = 2050 − 5 = 2045)**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2045.00, "bid":2044.50, "contract_size":100}'
```

Verify Row 2: `executed: true`, `entry_price: 2045.0`

**Step 7: Bounce price to trigger TP ($25)**

P&L with 3 executed rows at bid=2050.20:

- Row 0: (2050.20 − 2050) × 0.01 × 100 = $0.20
- Row 1: (2050.20 − 2048) × 0.02 × 100 = $4.40
- Row 2: (2050.20 − 2045) × 0.04 × 100 = $20.80
- **Total: $25.40 ≥ $25.00 → TP HIT**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2050.70, "bid":2050.20, "contract_size":100}'
```

Check logs for: `[SNAP-BACK] Grid B1 TP hit. Virtual P&L: $25.40 >= Target: $25.00`

Verify grid: `on: false`, `is_active: false`, `session_id: ""`

---

### Test 5: Cyclic Mode

**Turn ON with cyclic:**

```bash
curl -s -X POST $BASE/api/admin/tiers/{TIER_ID}/grids/B1/control \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"on": true, "cyclic": true}'
```

Now repeat Test 4 Steps 5–7. When TP hits, instead of turning off:

- Server log shows: `[SNAP-BACK] Grid B1 session ... TP hit → cyclic restart`
- A new session starts immediately
- All rows reset, Row 0 re-executes at current price
- Grid remains `on: true, cyclic: true`

---

### Test 6: Start Limit (Waiting Mode)

**Configure start_limit:**

```bash
# Turn off grid first
curl -s -X POST $BASE/api/admin/tiers/{TIER_ID}/grids/B1/control \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"on": false}'

# Set start_limit below current price
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/B1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"start_limit": 2040.0}'

# Turn ON
curl -s -X POST $BASE/api/admin/tiers/{TIER_ID}/grids/B1/control \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"on": true}'
```

Verify: `waiting_limit: true`, `start_ref: 2040.0`, no rows executed.

**Send tick at start_limit price:**

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2040.00, "bid":2039.50, "contract_size":100}'
```

Verify: `waiting_limit: false`, Row 0 `executed: true`, `entry_price: 2040.0`

Server log: `[LIMIT-HIT] Grid B1 start_limit reached (2040.00000). Row 0 executed at 2040.00000.`

---

### Test 7: End Limit

**Configure end_limit:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/B1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"start_limit": 0, "end_limit": 2038.0}'
```

Turn grid ON, then send ticks where price drops below 2038:

```bash
curl -s -X POST $BASE/api/master-tick \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"ask":2037.00, "bid":2036.50, "contract_size":100}'
```

Verify: Row 1 does NOT execute even though its target price is met. End limit blocks grid expansion but does NOT close the session.

---

### Test 8: Config Merge (Executed Row Protection)

While a grid has active session with some executed rows:

**Try modifying an executed row's lots:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/B1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rows": [
    {"index":0, "dollar":0, "lots":0.05, "alert":true},
    {"index":1, "dollar":2, "lots":0.02, "alert":false},
    {"index":2, "dollar":3, "lots":0.04, "alert":false},
    {"index":3, "dollar":4, "lots":0.06, "alert":false},
    {"index":4, "dollar":5, "lots":0.08, "alert":false}
  ]}'
```

Expected: Row 0 (if executed) keeps its original `dollar` and `lots`, only `alert` changes to `true`.

**Try omitting an executed row:**
Submit rows `[1,2,3,4]` omitting index 0 — the executed Row 0 is auto-reinserted.

---

### Test 9: Crash Recovery

1. Create a tier, configure a grid, turn it ON, execute some rows
2. Kill the server (`Ctrl+C`)
3. Restart the server
4. Verify: All tier states, grid configs/runtimes, and market state restored from PostgreSQL
5. Send a tick — processing continues from where it left off

---

### Test 10: Validation Errors

**Invalid grid_id:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/X1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tp_value": 10}'
```

Expected: `400 — Invalid grid_id`

**Invalid tp_type:**

```bash
curl -s -X PUT $BASE/api/admin/tiers/{TIER_ID}/grids/B1/config \
  -H "X-Admin-Key: $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tp_type": "invalid"}'
```

Expected: `400 — tp_type must be equity_pct, balance_pct, or fixed_money`

**More than 100 rows:**
Expected: `400 — Maximum 100 rows per grid`

**Non-sequential row indices:**
Expected: `400 — Row indices must be sequential`

**Delete tier with active session:**
Expected: `400 — Cannot delete tier with active sessions`

---

## 4. Understanding the Dollar Gap System

Rows use **cumulative gaps** from `start_ref`:

| Row | Dollar (gap from prev) | Cumulative Gap | Buy Target (start_ref − cumulative) |
| --- | ---------------------- | -------------- | ----------------------------------- |
| 0   | 0                      | 0              | Immediate (at start_ref)            |
| 1   | 2                      | 0+2 = 2        | start_ref − 2                       |
| 2   | 3                      | 0+2+3 = 5      | start_ref − 5                       |
| 3   | 4                      | 0+2+3+4 = 9    | start_ref − 9                       |
| 4   | 5                      | 0+2+3+4+5 = 14 | start_ref − 14                      |

For sell grids, the logic is reversed: `target = start_ref + cumulative_gap`, trigger when `bid >= target`.

---

## 5. Server Logs Reference

The server logs key events with these prefixes:

| Log Prefix        | Meaning                                                |
| ----------------- | ------------------------------------------------------ |
| `[ACTIVATE]`      | Grid activated (immediate or from limit)               |
| `[WAITING_LIMIT]` | Grid entered start_limit waiting mode                  |
| `[LIMIT-HIT]`     | Start limit price reached, grid transitioned to active |
| `[EXEC]`          | Row executed (entry_price and target logged)           |
| `[SNAP-BACK]`     | Take profit triggered (P&L and target logged)          |
| `[CLOSE]`         | Session closed (reason logged: tp_hit or manual)       |

---

## 6. Cleanup

```bash
# Stop the server
pkill -f "uvicorn main:app"

# Stop PostgreSQL Docker
docker stop elastic_dca_pg
docker rm elastic_dca_pg

# Deactivate virtual environment
deactivate
```

---

## 7. Troubleshooting

| Issue                           | Solution                                                                  |
| ------------------------------- | ------------------------------------------------------------------------- |
| `Connection refused` on startup | Ensure PostgreSQL is running on port 5432                                 |
| `Invalid admin key`             | Check `ADMIN_KEY` in `.env` matches your header                           |
| Market shows `ask: 0, bid: 0`   | Send a master tick first — market starts at 0 on fresh DB                 |
| Grid shows `entry_price: 0`     | Ensure you send a master tick BEFORE turning ON the grid                  |
| Row not executing               | Check cumulative gap math — the dollar field is gap from **previous** row |
| TP not triggering               | Use the P&L formula: `Σ (bid − entry) × lots × contract_size` for buys    |
