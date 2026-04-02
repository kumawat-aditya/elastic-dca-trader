# 🧠 Elastic DCA Engine (Server)

**Version:** `4.x`  
**Architecture:** Python 3.9+ / FastAPI / Uvicorn / SQLite  
**Role:** Central State Machine & Decision Engine

## 🎯 System Overview

The **Elastic DCA Server** is the brain of the trading system. All grid logic, risk math, and decision making run here. The MT5 Expert Advisor is a stateless HTTP client that reports market data every second and executes instructions it receives back. The React dashboard is a read-only monitor plus settings control.

```
MetaTrader 5 (EA)  ←──HTTP──→  FastAPI Server  ←──WebSocket──→  React UI
   (MQL5 script)                 (DcaEngine)                    (Dashboard)
                                       │
                                    SQLite
                                   (Presets)
```

---

## ⭐ Core Protocols

### 1. Elastic Grid (Accumulation)

Price moves against the anchor price trigger grid rows one by one. Each row opens a trade at the configured lot size. The anchor (`reference_point`) is set when the cycle starts — at the current ask (buy) or bid (sell) at that moment.

Row prices are computed as cumulative gaps from the anchor:

- **Buy:** `price = anchor − Σ(gaps up to that row)`
- **Sell:** `price = anchor + Σ(gaps up to that row)`

### 2. Take Profit — Snap-Back Exit

The engine monitors the **net aggregate floating P&L** of all active session trades. When `total_cumulative_pnl >= tp_target`, it sends `CLOSE_ALL` to the EA.

- **Cyclic mode ON:** A new session starts immediately after the close.
- **Cyclic mode OFF:** The grid is cleared but stays ON, waiting for the next trigger.

### 3. Stop Loss — Hard Stop

When `total_cumulative_pnl <= -sl_target`:

- `CLOSE_ALL` is issued to the EA.
- `is_cyclic` is automatically forced to `false`.
- `is_on` is set to `false` (hard stop).
- **The grid requires manual re-activation via the UI.**

### 4. IronClad Hedge Protection 🛡️

If `total_cumulative_pnl <= -hedging_threshold` (before SL is hit), a counter-trade is deployed on the opposite side with volume equal to `total_cumulative_lots`. TP/SL for the hedge trade are computed from the distance between the reference point and current price. The grid is locked from further accumulation (`is_hedged = true`).

### 5. Start Limit & Auto-Clear

`start_limit` is an optional price threshold that must be crossed before a new session begins. Once the **first row executes** in a session, `start_limit` is automatically cleared to `null` so that future sessions (cyclic or manual restart) begin immediately without re-crossing the original trigger price.

### 6. Row Stop Limit (`row_stop_limit`)

An optional integer cap on how many rows may execute in a session. Rows at index ≥ `row_stop_limit` are skipped. `null` = no cap.

### 7. Zombie & Emergency State Detection 🛡️

- **Emergency State:** If the server has no active session but open trades with the engine's session prefix exist on the MT5 account, `emergency_state` is set to `true`. The UI shows a banner instructing the user to close them manually.
- **Zombie Cleanup:** If trades from an _old_ session of the same side are found while a _new_ session is active, `CLOSE_ALL` commands are queued for those old sessions automatically.

### 8. EA Timeout Guard

If no tick is received for `EA_TIMEOUT_SECONDS`, both grids are hard-reset, `is_cyclic` is disabled, and `ea_connected` is set to `false`.

---

## 🔄 Per-Tick Processing Pipeline

Every EA heartbeat triggers this evaluation sequence (both buy and sell, independently):

| Step | Method                     | Purpose                                                                                        |
| ---- | -------------------------- | ---------------------------------------------------------------------------------------------- |
| 1    | `update_from_tick()`       | Update market prices, account data, tick queue                                                 |
| 2    | `_check_emergency_state()` | Detect orphaned/zombie trades                                                                  |
| 3    | `_map_positions_and_pnl()` | Sync floating P&L from EA positions into grid rows                                             |
| 4    | `_evaluate_tp_sl()`        | TP hit → cyclic restart or clear. SL hit → force `is_on=False`, `is_cyclic=False`, hard reset. |
| 5    | `_evaluate_hedging()`      | Deploy counter-trade if loss ≥ hedge threshold                                                 |
| 6    | `_evaluate_cycle_start()`  | Start new session if `is_on` and no active session (respects `start_limit` if set)             |
| 7    | `_evaluate_grid_rows()`    | Trigger BUY/SELL orders on price crossover; clear `start_limit` on first row execution         |

---

## 🔌 API Overview

### EA Heartbeat

**`POST /api/v1/ea/tick`** — 1-second ping from MT5.

**Request:** `{ account_id, equity, balance, symbol, ask, bid, trend_h1, trend_h4, positions[] }`  
**Response:** `{ "actions": [ {action, volume, comment, ...}, ... ] }`

Possible action types: `BUY`, `SELL`, `CLOSE_ALL`, `HEDGE`, `WAIT` (empty array).

### Dashboard WebSocket

**`WS /api/v1/ui/ws`** — Pushes full `SystemState` JSON once per second.

### Grid Controls

**`POST /api/v1/ui/control/{side}`** — `{ is_on: bool, is_cyclic: bool }`

### Grid Settings

**`PUT /api/v1/ui/settings/{side}`** — Full `GridSettings` object. Immutability of executed rows is enforced while grid is ON.

### Presets (SQLite CRUD)

- `GET /api/v1/ui/presets`
- `POST /api/v1/ui/presets`
- `PUT /api/v1/ui/presets/{id}`
- `DELETE /api/v1/ui/presets/{id}`
- `POST /api/v1/ui/presets/{id}/load/{side}`

> Presets store **rows only** (gap, lots, alert). TP/SL, limits, and hedging are not stored in presets.

See `docs/API_REFERENCE.md` for full schema and endpoint documentation.

---

## 🚀 Running the Server

### Requirements

- Python 3.9+
- Install dependencies: `pip install -r requirements.txt`

### Start

```bash
cd apps/server
source venv/bin/activate   # or your virtualenv
python main.py
```

Server starts on **port 8000** by default. EA connects to `http://<host>:8000/api/v1/ea/tick`. UI connects to `ws://<host>:8000/api/v1/ui/ws`.

### Environment Variables (`.env`)

| Variable             | Default | Description                                  |
| -------------------- | ------- | -------------------------------------------- |
| `EA_TIMEOUT_SECONDS` | `10`    | Seconds without a tick before disconnecting  |
| `HEDGE_TP_PCT`       | `100`   | Hedge TP as % of reference-to-price distance |
| `HEDGE_SL_PCT`       | `50`    | Hedge SL as % of TP distance                 |
| `LOG_LEVEL`          | `DEBUG` | Logging verbosity                            |

---

## ⚠️ Troubleshooting

**Emergency State Banner in UI**

- Open trades exist on MT5 that don't match any active server session.
- Close them manually in MT5. The banner clears automatically on the next tick.

**SL hit — grid won't restart**

- By design: SL hit forces `is_on=False` and `is_cyclic=False`. Manually turn the grid back ON in the UI after reviewing conditions.

**Orphan/Zombie trades after server restart**

- After a server restart, any trades still open on MT5 will trigger emergency state since the server has no session memory. Close them manually in MT5.
