Here is the comprehensive **Frontend API & State Management Integration Guide** for Elastic DCA v4.

This document is written specifically for the Frontend Developer (React/Vue/Angular). It explains the exact flow of data, TypeScript interfaces, endpoint contracts, and the strict rules required to ensure the UI never desynchronizes from the backend engine.

---

# 🖥️ Frontend API & State Management Guide (Elastic DCA v4)

## 📌 Architectural Core Principle: "The Dumb Terminal"

The frontend is strictly a **Monitor and Remote Control**.

- **Do NOT calculate math** (prices, cumulative lots, PnL) on the frontend.
- **Do NOT mutate the main display state locally**.
- **Unidirectional Data Flow:** The WebSocket provides the absolute truth. When a user changes settings, send a REST request. Do _not_ update the UI manually—wait for the backend to recalculate and push the updated state via the WebSocket.

---

## 1️⃣ TypeScript Interfaces (The Data Dictionary)

Copy these interfaces into your frontend project. Pay close attention to the `readonly` fields—these are managed entirely by the server and will be ignored or cause errors if you try to mutate them in ways the server doesn't expect.

```typescript
export type Side = "buy" | "sell";

export interface GridRow {
  index: number;
  gap: number;
  lots: number;

  alert: boolean;

  // --- SERVER MANAGED (Read-Only for UI Display) ---
  readonly alert_executed: boolean;
  readonly executed: boolean;
  readonly price: number | null;
  readonly cumulative_lots: number;
  readonly pnl: number;
  readonly cumulative_pnl: number;
}

export interface GridSettings {
  is_on: boolean;
  is_cyclic: boolean;
  start_limit: number | null;
  row_stop_limit: number | null;
  tp_type: "fixed" | "equity" | "balance";
  tp_value: number;
  sl_type: "fixed" | "equity" | "balance";
  sl_value: number;
  hedging: number | null;
  rows: GridRow[];
}

export interface GridState {
  readonly session_id: string | null;
  readonly reference_point: number | null;
  readonly is_hedged: boolean;
  readonly emergency_state: boolean;
  readonly total_cumulative_lots: number;
  readonly total_cumulative_pnl: number;
}

export interface SystemState {
  readonly ea_connected: boolean;
  readonly last_ea_ping_ts: number;
  readonly account_id: string;
  readonly symbol: string;
  readonly equity: number;
  readonly balance: number;
  readonly current_mid: number;
  readonly current_ask: number;
  readonly current_bid: number;
  readonly trend_h1: string;
  readonly trend_h4: string;

  buy_settings: GridSettings;
  buy_state: GridState;
  sell_settings: GridSettings;
  sell_state: GridState;
}
```

---

## 2️⃣ Live Dashboard Stream (WebSockets)

**Endpoint:** `ws://<API_URL>/api/v1/ui/ws`

On component mount, connect to this WebSocket. It pushes the complete `SystemState` JSON object exactly **once per second**.

**Frontend Responsibilities:**

1. Store this incoming payload in your global state (e.g., Redux, Zustand, or React Context).
2. Bind your Dashboard UI directly to this state.
3. **Emergency Banner:** If `buy_state.emergency_state === true` (or sell), instantly render a large red warning banner telling the user to manually close orphan MT5 trades.

---

## 3️⃣ Grid Controls (ON / OFF / Cyclic)

**Endpoint:** `POST /api/v1/ui/control/{side}`

Controls the master switches for a grid.

**Request Body:**

```json
{
  "is_on": true,
  "is_cyclic": false
}
```

**Frontend Handling:**

- If the user clicks the "Power" toggle to turn the grid OFF, warn them: _"Turning off will immediately close all open trades for this grid. Proceed?"_
- On success, do not update local state. The next WebSocket tick will reflect `is_on: false` and the wiped session.

---

## 4️⃣ Updating Grid Settings (The "Lock" Rule)

**Endpoint:** `PUT /api/v1/ui/settings/{side}`

Updates the grid parameters. You must send the **entire** `GridSettings` object.

### ⚠️ CRITICAL: The Executed Row Lock

The backend enforces mathematical integrity. If the grid is currently running (`is_on === true`), you **cannot** modify the `gap` or `lots` of any row that has `executed === true`. If you try, the server returns a `400 Bad Request`.

**How the Frontend Form MUST Behave:**

1. When the user opens the "Settings Form", create a local copy of `buy_settings` from the WebSocket state.
2. In your rendering loop for the rows:

   ```tsx
   const isLocked = row.executed && systemState.buy_settings.is_on;

   <input
     type="number"
     disabled={isLocked} // Visually lock the inputs!
     value={row.gap}
   />;
   ```

3. The user can safely edit the `gap`/`lots` of _unexecuted_ rows, and can edit `start_limit`, `TP`, `SL`, and `alert` checkboxes at any time.
4. When they hit "Save", send the payload. The backend will instantly recalculate `cumulative_lots` and projected `price` and push them via WebSocket.

---

## 5️⃣ Alert Acknowledgment (Notification Flow)

**Endpoint:** `POST /api/v1/ui/ack-alert/{side}/{index}`

Because the WebSocket pulses every second, it will keep sending a triggered row to you. You must tell the backend to stop.

**Frontend Alert Engine Logic:**
Create a `useEffect` (or watcher) that monitors the WebSocket state:

```javascript
// Pseudo-logic for your state watcher
state.buy_settings.rows.forEach((row) => {
  if (
    row.alert === true &&
    row.executed === true &&
    row.alert_executed === false
  ) {
    // 1. Trigger the visual toast / audio chime
    toast.success(`Buy Row ${row.index} Executed at ${row.price}!`);

    // 2. IMMEDIATELY tell the backend we handled it so it doesn't ring again next second
    fetch(`/api/v1/ui/ack-alert/buy/${row.index}`, { method: "POST" });
  }
});
```

---

## 6️⃣ Presets Management (CRUD)

Presets only save the array of `GridRow` configurations. They ignore limits, TP, SL, etc.

### A. Save a Preset

**Endpoint:** `POST /api/v1/ui/presets`
**Request Body:**

```json
{
  "name": "Aggressive 5-Step",
  "rows": [
    { "index": 0, "gap": 10, "lots": 0.01, "alert": false },
    { "index": 1, "gap": 20, "lots": 0.02, "alert": true }
  ]
}
```

- **Handling:** Returns `400` if the name already exists. Show a toast on error/success.

### B. Fetch Presets

**Endpoint:** `GET /api/v1/ui/presets`
**Response:**

```json[
  {
    "id": 1,
    "name": "Aggressive 5-Step",
    "rows": [...] // Array of GridRows
  }
]
```

- **Handling:** Fetch this on component mount to populate your "Load Preset" dropdown.

### C. Load a Preset to Grid

**Endpoint:** `POST /api/v1/ui/presets/{preset_id}/load/{side}` (Empty Body)

- **CRITICAL CONSTRAINT:** The server will throw a `400 Bad Request` if `is_on === true` for that side.
- **Frontend Handling:**
  - Disable the "Load Preset" button if `systemState[side].is_on` is true.
  - If the user clicks it, show a tooltip: _"You must turn the grid OFF before applying a preset."_
  - On success, the backend will completely overwrite the grid rows, recalculate the `cumulative_lots`, and send the new UI map via the next WebSocket pulse.

---

## 🚦 Common Error Codes to Catch

When making REST calls, wrap them in try/catch or `.then().catch()` blocks. Expect these errors from the backend:

- **`400 Bad Request`**:
  - _Cause A:_ You tried to change the gap/lots of an `executed` row.
  - _Cause B:_ You tried to load a preset while the grid was `is_on = true`.
  - _Cause C:_ You tried to save a preset name that already exists.
- **`404 Not Found`**:
  - _Cause A:_ You sent an `ack-alert` for an index that doesn't exist.
  - _Cause B:_ You tried to load a preset ID that was deleted.
- **`422 Unprocessable Entity`**:
  - _Cause:_ Your JSON payload did not perfectly match the TypeScript interfaces defined above (e.g., you sent a string instead of a float for a gap).
