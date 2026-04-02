# 🌐 Elastic DCA v4 - Complete Integration Documentation

This document serves as the **strict contract** for both the MetaTrader 5 (EA) developer and the Frontend Dashboard developer.

### 🏗 Architecture Overview (Decoupled State Machine)

1. **The Backend (FastAPI)** is the brain. It holds all grid logic, crossover math, limits, and dynamic calculations.
2. **The EA (MetaTrader 5)** is the muscle. It knows _nothing_ about grids, PnL math, or gaps. It reports the raw MT5 account state 1x per second and blindly loops through the array of commands the backend gives it.
3. **The Frontend (Web UI)** is the monitor. It calculates _nothing_. It streams the backend's state via WebSockets to paint the UI, and sends REST requests to update settings or trigger actions.

---

# 🤖 PART 1: MetaTrader 5 (EA) Developer Guide

The EA's job is to run an infinite loop (using `OnTimer` set to 1 second). Every second, it sends the account state to the server, receives an array of actions, and executes them concurrently.

## 1. The Heartbeat Endpoint (REST)

**`POST /api/v1/ea/tick`**

This endpoint must be pinged exactly **once per second**. If the EA stops pinging for >`EA_TIMEOUT_SECONDS` (e.g., 10s), the Server triggers a hard disconnect and halts trading.

### Request Payload (`TickData`)

Gather all positions currently open on the account. Send them all. The server will filter out the ones it doesn't own.

```json
{
  "account_id": "893412",
  "equity": 10500.5,
  "balance": 10000.0,
  "symbol": "EURUSD",
  "ask": 1.0501,
  "bid": 1.05,
  "trend_h1": "up", // EA calculates this (e.g., Moving Average) -> "up", "down", "neutral"
  "trend_h4": "down", // EA calculates this
  "positions": [
    {
      "ticket": 1234567,
      "symbol": "EURUSD",
      "type": "BUY", // Strictly "BUY" or "SELL"
      "volume": 0.01,
      "price": 1.0495,
      "profit": 5.5, // Floating PnL of this specific trade
      "comment": "buy_a1b2c3d4_idx0" // CRITICAL: Server maps rows using this
    }
  ]
}
```

### Response Payload (Bulk Action Commands)

To prevent latency and missed trades during massive volatility, the Server sends **an array of actions**. The EA must loop through this `actions` array and execute them all in a single `OnTimer` cycle.

#### Case A: Empty Queue (No Actions)

The grid is waiting/paused. Do nothing.

```json
{ "actions": [] }
```

#### Case B: Multi-Row Gap Execution (News Event)

The market dropped violently, crossing multiple grid rows simultaneously.

```json
{
  "actions": [
    { "action": "BUY", "volume": 0.01, "comment": "buy_a1b2_idx0" },
    { "action": "BUY", "volume": 0.02, "comment": "buy_a1b2_idx1" }
  ]
}
```

- **EA Rule:** Loop through the array. Fire `OrderSend` for both trades instantly. `SL` and `TP` must be `0` (Server manages soft limits). Apply the exact `comment`.

#### Case C: Cycle Complete & Zombie Cleanup

The cycle hit TP/SL, or the server detected leftover "zombie" trades from an old session.

```json
{
  "actions": [
    { "action": "CLOSE_ALL", "comment": "buy_old111" },
    { "action": "BUY", "volume": 0.01, "comment": "buy_new222_idx0" }
  ]
}
```

- **EA Rule:**
  1. For `CLOSE_ALL`: Loop through all open MT5 positions. If the MT5 position's comment **contains** `"buy_old111"`, close it immediately at market price.
  2. Continue to the next array item and execute the new `BUY` order.

#### Case D: `HEDGE` (Emergency Risk Lock)

The grid hit maximum drawdown. The server calculates precise TP/SL.

```json
{
  "actions": [
    {
      "action": "HEDGE",
      "side": "buy",
      "type": "SELL",
      "volume": 0.15,
      "tp": 1.045,
      "sl": 1.055,
      "comment": "hedge_buy_a1b2c3d4"
    }
  ]
}
```

- **EA Rule:** Open the trade. **Unlike normal grid trades, you MUST set the hard MT5 `tp` and `sl` prices provided by the server.**

### 🛡️ EA Execution Rules & Slippage

1.  **Slippage Rejection:** If the EA tries to open a `BUY` command but the broker rejects it due to high slippage/off-quotes, **do not retry**. The Server will see it missing on the next tick, safely map `$0.00` PnL to that row, and continue the sequence.
2.  **Autonomous Cleanup:** If the EA sees open trades but the server keeps sending `[]` (empty actions), do nothing. The EA only acts when explicitly given an action in the array.

---

# 💻 PART 2: Frontend (UI) Developer Guide

The frontend is a strict monitor/terminal. **Do not calculate prices, cumulative lots, or cumulative PnL on the frontend.**

## 1. Live Data Stream (WebSocket)

**`ws://<HOST>:<PORT>/api/v1/ui/ws`**

Connect to this on mount. It streams the `SystemState` JSON every 1 second.

- **Market Data:** Bind UI to `current_ask`, `current_bid`, `current_mid`, `trend_h1`, `trend_h4`.
- **Grid Data:** Render tables using `buy_settings.rows` and `sell_settings.rows`.
- **Dynamic Math:** Bind your columns directly to the backend's `row.price`, `row.cumulative_lots`, and `row.cumulative_pnl`.
- **Emergency Banner:** If `buy_state.emergency_state == true`, show a massive red banner: _"Unknown Buy trades found on MT5. Please close them manually."_

## 2. Grid Controls (ON/OFF/Cyclic)

**`POST /api/v1/ui/control/{side}`** _(side = "buy" or "sell")_

```json
{
  "is_on": true,
  "is_cyclic": false
}
```

- **Behavior:** Sending `is_on: false` while running instantly commands the EA to close all active trades for that side and hard-resets the backend math.

## 3. Alerts (Crucial Flow)

**`POST /api/v1/ui/ack-alert/{side}/{index}`**

When the WebSocket sends a row where `alert == true`, `executed == true`, and `alert_executed == false`, the frontend must:

1. Play a notification sound or render a Toast popup.
2. Immediately `POST` to `/api/v1/ui/ack-alert/buy/3` (if it was buy row index 3).
3. The server will flip `alert_executed` to `true`. On the next WebSocket tick, you will see `alert_executed: true`, stopping the UI from re-playing the sound.

## 4. Updating Grid Settings (Runtime Modifications)

**`PUT /api/v1/ui/settings/{side}`**

Send the ENTIRE `GridSettings` object to update rules.

### 🚨 Strict Editing Rules (The "Lock")

Users can edit the grid while it is running (`is_on == true`), but **Executed Rows are mathematically locked**.

1. If Row 0 has `executed: true` in the WS stream, you **MUST** send Row 0 back with the exact same `index`, `gap`, and `lots`.
2. If you change the `gap`/`lots` of an executed row, or delete it, the server will return a **400 Bad Request**.
3. You _can_ safely change `gap`/`lots` of unexecuted rows.
4. You _can_ safely toggle the `alert` boolean on any row at any time.

_Example Payload:_

```json
{
  "is_on": true,
  "is_cyclic": true,
  "start_limit": 1.05,
  "row_stop_limit": null,
  "tp_type": "fixed",
  "tp_value": 50.0,
  "sl_type": "equity",
  "sl_value": 5.0,
  "hedging": 100.0,
  "rows": [
    { "index": 0, "gap": 10, "lots": 0.01, "alert": false }, // EXECUTED: Values locked
    { "index": 1, "gap": 25, "lots": 0.02, "alert": true } // UNEXECUTED: Gap safely changed to 25
  ]
}
```

_(Note: You do not need to send `price`, `cumulative_lots`, etc. The backend rebuilds them instantly)._

## 5. Presets (Database Management)

Presets **ONLY** store the grid rows. They do NOT store Limits, TP, SL, or Hedging data, because those vary depending on daily market conditions.

**Save a Preset:**
`POST /api/v1/ui/presets`

```json
{
  "name": "Aggressive Scalper",
  "rows": [
    { "index": 0, "gap": 5, "lots": 0.01, "alert": false },
    { "index": 1, "gap": 10, "lots": 0.02, "alert": false }
  ]
}
```

**Get Presets:**
`GET /api/v1/ui/presets`
Returns an array of preset objects for your dropdown menu.

**Load a Preset:**
`POST /api/v1/ui/presets/{preset_id}/load/{side}` (No body required)

- **Behavior:** The server will reject this (400 Bad Request) if the target grid is `is_on == true`. The user must turn the grid OFF before applying a preset. Once loaded, the WebSocket instantly updates the table with the pre-calculated `cumulative_lots`.

---

### UI Developer Checklist:

- [ ] **Row Highlighting:** Use `row.executed == true` to change row background colors so the user sees the market crossing grid levels.
- [ ] **Data Binding:** Never do math on the frontend. Bind your UI directly to `row.cumulative_lots` and `row.cumulative_pnl`.
- [ ] **Projected Prices:** `row.price` is `null` when the grid is OFF. Once it starts, `row.price` dynamically populates with the exact market prices the rows will trigger at. Show this in the table.

# 🎯 Elastic DCA v4 — **Final UI Draft (Strict + Refined)**

---

# 🧱 1. FULL PAGE STRUCTURE

```plaintext
---------------------------------------------------------
| Elastic DCA v4                                         |
|                                                       |
| EURUSD | Ask | Bid | Mid | Equity | Balance           |
|                                                       |
| 🟢 Server: Connected   🟢 EA: Connected                |
|                                                       |
| [ Create Preset ]                                     |
---------------------------------------------------------

---------------------------------------------------------
| BUY SECTION              | SELL SECTION               |
| (Independent)            | (Independent)              |
---------------------------------------------------------
```

---

# 🔝 2. TOP BAR

### LEFT

```plaintext
Elastic DCA v4
```

---

### CENTER (WebSocket Binding Only)

```plaintext
EURUSD

Ask: {current_ask}
Bid: {current_bid}
Mid: {current_mid}

Equity: {equity}
Balance: {balance}
```

---

### RIGHT

```plaintext
🟢 Server: Connected / 🔴 Disconnected
🟢 EA: Connected / 🔴 Disconnected

[ Create Preset ]
```

---

# 🔌 CONNECTION LOGIC

### Server:

- Based on WebSocket

### EA:

```plaintext
if (now - last_tick > 5s)
    → 🔴 Disconnected
else
    → 🟢 Connected
```

---

# 🟩 3. BODY SPLIT (IMPORTANT)

```plaintext
| BUY SIDE | SELL SIDE |
```

✔ Fully independent
✔ No shared state
✔ Same structure

---

# 🟢 4. BUY SECTION (LEFT SIDE)

---

## 🧩 STRUCTURE

```plaintext
-----------------------------------
| BUY GRID                        |
-----------------------------------

| ACTIONS                         |
| SETTINGS + PRESETS              |
| GRID TABLE                      |
-----------------------------------
```

---

# 🚨 4.1 EMERGENCY OVERLAY (BUY ONLY)

### Condition:

```plaintext
buy_state.emergency_state == true
```

---

### UI Behavior:

```plaintext
-----------------------------------
| 🔴 OVERLAY (COVERS BUY SECTION) |
|                                 |
| 🚨 Unknown BUY trades detected  |
| Please close them manually      |
|                                 |
-----------------------------------
```

---

### UX Rules:

- Entire BUY section becomes:
  - ❌ Disabled
  - 🌑 Darkened

- No interaction allowed underneath

---

# 🎛️ 4.2 ACTION CONTROLS

```plaintext
[ ON/OFF Toggle ]   → is_on
[ CYCLIC Toggle ]   → is_cyclic

[ Apply ]
```

---

### API:

```plaintext
POST /api/v1/ui/control/buy
```

---

# ⚙️ 4.3 SETTINGS + PRESET SELECTOR

```plaintext
Start Limit: [ input ]
Stop Limit:  [ input ]

TP Type:  [ select ]
TP Value: [ input ]

SL Type:  [ select ]
SL Value: [ input ]

Hedging: [ input ]

-------------------------

Preset:
[ Dropdown ▼ ]
```

---

### Notes:

- Preset dropdown → `GET /presets`
- Load preset → `POST /presets/{id}/load/buy`
- Disable load if:

```plaintext
is_on == true
```

---

# 📊 4.4 GRID TABLE (BUY)

```plaintext
|Idx|Gap|Lots|Price  |CumLots|CumPnL|Alert|
------------------------------------------------
|0  |10 |0.01|1.0500 |0.01   |5.50  |false|
|1  |25 |0.02|1.0480 |0.03   |-3.20 |true |
```

---

## 🔒 EDITING RULES

### Executed row (UI internal only):

- gap ❌ locked
- lots ❌ locked
- alert ✔ editable

---

### Important:

❌ Do NOT show:

```plaintext
executed
alert_executed
```

---

# 🔔 4.5 ALERT SYSTEM (BUY)

---

## Trigger Condition:

```plaintext
row.alert == true
row.executed == true
row.alert_executed == false
```

---

## UI (POPUP CARD)

```plaintext
-----------------------------
🚨 BUY ALERT

Row: 1 triggered

[ Acknowledge ]
-----------------------------
```

---

## Behavior:

- 🔊 Continuous sound (loop)
- Blocks attention (top layer, not full screen)

---

## On Click:

```plaintext
POST /api/v1/ui/ack-alert/buy/{index}
```

- Stop sound
- Close popup

---

# 🔴 5. SELL SECTION (RIGHT SIDE)

⚠️ EXACT SAME STRUCTURE AS BUY
⚠️ FULLY INDEPENDENT

---

## 🚨 EMERGENCY OVERLAY (SELL ONLY)

```plaintext
sell_state.emergency_state == true
```

```plaintext
-----------------------------------
| 🔴 OVERLAY (SELL SECTION ONLY)  |
|                                 |
| 🚨 Unknown SELL trades detected |
| Please close them manually      |
-----------------------------------
```

---

## 🎛️ CONTROLS

```plaintext
POST /control/sell
```

---

## ⚙️ SETTINGS

```plaintext
PUT /settings/sell
```

---

## 📊 GRID TABLE

Same columns:

```plaintext
Idx | Gap | Lots | Price | CumLots | CumPnL | Alert
```

---

## 🔔 ALERT POPUP (SELL)

```plaintext
🚨 SELL ALERT

Row: 0 triggered

[ Acknowledge ]
```

---

### API:

```plaintext
POST /ack-alert/sell/{index}
```

---

# 💾 6. CREATE PRESET (NAVBAR FLOW)

---

## Button:

```plaintext
[ Create Preset ]
```

---

## On Click → POPUP CARD

```plaintext
-------------------------------
Create Preset

Name: [__________]

Rows:

|Idx|Gap|Lots|Alert|
--------------------
|0  |    |    |     |
|1  |    |    |     |

[ + Add Row ]

-------------------------------
[ Save Preset ]
-------------------------------
```

---

## API:

```plaintext
POST /api/v1/ui/presets
```

---

## Rules:

- Only send:

```plaintext
rows[]
```

- No settings
- No TP/SL
- No limits

---

# 🎨 7. VISUAL BEHAVIOR SUMMARY

---

## BUY SIDE

- Green highlights
- Green executed rows

## SELL SIDE

- Red highlights
- Red executed rows

---

## DISABLED STATE (Emergency)

- Dark overlay
- Blur / dim effect
- No clicks allowed

---

## ALERT

- Floating card
- Continuous sound
- Requires manual acknowledgement

---

# 🧠 FINAL SYSTEM ALIGNMENT

| Layer   | Responsibility           |
| ------- | ------------------------ |
| Backend | All logic                |
| EA      | Execution                |
| UI      | Rendering + User Actions |

---
