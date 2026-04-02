# API Reference — Elastic DCA Engine v4

> **Generated:** April 2, 2026  
> **Source of truth:** Derived entirely from source code analysis of `apps/server/app/routers/` and `apps/web/src/services/api.ts`.

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Base URLs](#2-base-urls)
3. [Common Types](#3-common-types)
4. [EA Communication Endpoints](#4-ea-communication-endpoints)
   - [POST /api/v1/ea/tick](#post-apiv1eatick)
5. [Dashboard & UI Endpoints](#5-dashboard--ui-endpoints)
   - [WS /api/v1/ui/ws](#ws-apiv1uiws)
   - [POST /api/v1/ui/control/{side}](#post-apiv1uicontrolside)
   - [PUT /api/v1/ui/settings/{side}](#put-apiv1uisettingsside)
   - [POST /api/v1/ui/ack-alert/{side}/{index}](#post-apiv1uiack-alertsideindex)
   - [GET /api/v1/ui/presets](#get-apiv1uipresets)
   - [POST /api/v1/ui/presets](#post-apiv1uipresets)
   - [PUT /api/v1/ui/presets/{preset_id}](#put-apiv1uipresetspreset_id)
   - [DELETE /api/v1/ui/presets/{preset_id}](#delete-apiv1uipresetspreset_id)
   - [POST /api/v1/ui/presets/{preset_id}/load/{side}](#post-apiv1uipresetspreset_idloadside)
6. [EA Action Payload Types](#6-ea-action-payload-types)
7. [Frontend API Consumption](#7-frontend-api-consumption)
8. [Error Responses](#8-error-responses)

---

## 1. Authentication

**There is no authentication.** All endpoints are open. The server relies on network-level access control (firewall / VPN) to restrict access.

> **Security note:** For any internet-facing deployment, add authentication middleware (e.g., API key header validation as a FastAPI dependency) before exposing these endpoints publicly.

---

## 2. Base URLs

| Client                 | Base URL                           | Configurable via       |
| ---------------------- | ---------------------------------- | ---------------------- |
| MT5 Expert Advisor     | `http://<host>:8000/api/v1/ea`     | EA input parameter     |
| React Dashboard (REST) | `http://localhost:8000/api/v1/ui`  | `VITE_API_URL` env var |
| React Dashboard (WS)   | `ws://localhost:8000/api/v1/ui/ws` | `VITE_WS_URL` env var  |

Default server: `http://0.0.0.0:8000`.

---

## 3. Common Types

These types appear across multiple endpoints. They map 1:1 to both the backend Pydantic schemas and the frontend TypeScript interfaces in `types.ts`.

### `GridRow`

| Field             | Type            | Description                                                                       |
| ----------------- | --------------- | --------------------------------------------------------------------------------- |
| `index`           | `integer`       | Row position in the grid (0-based)                                                |
| `gap`             | `float`         | Price gap from the previous row (in price units, e.g. pips × point)               |
| `lots`            | `float`         | Trade volume for this row in lots                                                 |
| `alert`           | `boolean`       | If `true`, the frontend fires an audio/visual notification when this row executes |
| `alert_executed`  | `boolean`       | **Server-managed.** Set to `true` after the alert has been acknowledged           |
| `executed`        | `boolean`       | **Server-managed.** Set to `true` when the engine has queued a trade for this row |
| `price`           | `float \| null` | **Server-managed.** Computed absolute price target for this row                   |
| `cumulative_lots` | `float`         | **Server-managed.** Running sum of lots from row 0 to this row                    |
| `pnl`             | `float`         | **Server-managed.** Live P&L in dollars for the trade at this row                 |
| `cumulative_pnl`  | `float`         | **Server-managed.** Running sum of P&L from row 0 to this row                     |

### `GridSettings`

| Field         | Type                               | Description                                                                                          |
| ------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `is_on`       | `boolean`                          | Master switch: `true` = grid is active                                                               |
| `is_cyclic`   | `boolean`                          | If `true`, automatically starts a new session after TP/SL is hit                                     |
| `start_limit` | `float \| null`                    | Price level that must be crossed before the session anchors. `null` = start immediately on next tick |
| `stop_limit`  | `integer \| null`                  | Maximum number of rows to execute. `null` = no limit                                                 |
| `tp_type`     | `"fixed" \| "equity" \| "balance"` | How the TP target is interpreted                                                                     |
| `tp_value`    | `float`                            | TP target value. `<= 0` disables TP. For `equity`/`balance` types, this is a percentage              |
| `sl_type`     | `"fixed" \| "equity" \| "balance"` | How the SL target is interpreted                                                                     |
| `sl_value`    | `float`                            | SL target value (absolute; the engine compares against `-sl_value`). `<= 0` disables SL              |
| `hedging`     | `float \| null`                    | Dollar loss threshold that triggers the automatic hedge. `null` = disabled                           |
| `rows`        | `GridRow[]`                        | The ordered list of grid rows                                                                        |

### `GridState`

| Field                   | Type                | Description                                                                    |
| ----------------------- | ------------------- | ------------------------------------------------------------------------------ |
| `session_id`            | `string \| null`    | Active session UUID (format: `{side}_{8-hex}`). `null` = no active session     |
| `reference_point`       | `float \| null`     | Anchor price from which all grid row prices are calculated                     |
| `is_hedged`             | `boolean`           | `true` if the hedge trade has been deployed in this session                    |
| `hedge_data`            | `HedgeData \| null` | Details of the deployed hedge trade                                            |
| `emergency_state`       | `boolean`           | `true` if orphaned trades are detected on the account without a server session |
| `total_cumulative_lots` | `float`             | Sum of volumes of all active session positions                                 |
| `total_cumulative_pnl`  | `float`             | Sum of floating P&L of all active session positions                            |

### `HedgeData`

| Field         | Type    | Description                                                                      |
| ------------- | ------- | -------------------------------------------------------------------------------- |
| `entry_price` | `float` | Market price at the moment the hedge was triggered                               |
| `sl`          | `float` | Stop loss price for the hedge trade                                              |
| `tp`          | `float` | Take profit price for the hedge trade                                            |
| `lots`        | `float` | Volume of the hedge trade (equals `total_cumulative_lots` at hedge trigger time) |

### `SystemState`

The complete state pushed over WebSocket every second.

| Field             | Type           | Description                                                 |
| ----------------- | -------------- | ----------------------------------------------------------- |
| `ea_connected`    | `boolean`      | `true` if a tick was received within `EA_TIMEOUT_SECONDS`   |
| `last_ea_ping_ts` | `float`        | Unix timestamp of the last received tick                    |
| `account_id`      | `string`       | MT5 account identifier (from EA tick)                       |
| `symbol`          | `string`       | Trading symbol (e.g., `"EURUSD"`)                           |
| `equity`          | `float`        | Current account equity in account currency                  |
| `balance`         | `float`        | Current account balance in account currency                 |
| `current_mid`     | `float`        | `(ask + bid) / 2` of the latest tick                        |
| `current_ask`     | `float`        | Latest ask price                                            |
| `current_bid`     | `float`        | Latest bid price                                            |
| `trend_h1`        | `string`       | H1 trend signal from EA (`"buy"`, `"sell"`, or `"neutral"`) |
| `trend_h4`        | `string`       | H4 trend signal from EA (`"buy"`, `"sell"`, or `"neutral"`) |
| `buy_settings`    | `GridSettings` | Full buy grid configuration                                 |
| `buy_state`       | `GridState`    | Live buy grid runtime state                                 |
| `sell_settings`   | `GridSettings` | Full sell grid configuration                                |
| `sell_state`      | `GridState`    | Live sell grid runtime state                                |

---

## 4. EA Communication Endpoints

### `POST /api/v1/ea/tick`

**Description:** The EA's 1-second heartbeat. Receives current market data and open position list from MetaTrader 5. The engine processes it through its full evaluation pipeline and returns a batch of queued trading actions for the EA to execute.

**Request Body:** `application/json`

```json
{
  "account_id": "12345678",
  "equity": 10250.5,
  "balance": 10000.0,
  "symbol": "EURUSD",
  "ask": 1.085,
  "bid": 1.08498,
  "trend_h1": "buy",
  "trend_h4": "neutral",
  "positions": [
    {
      "ticket": 987654321,
      "symbol": "EURUSD",
      "type": "buy",
      "volume": 0.01,
      "price": 1.0845,
      "profit": 0.5,
      "comment": "buy_a1b2c3d4_idx0"
    }
  ]
}
```

**Request Schema:**

| Field        | Type         | Required                  | Description                               |
| ------------ | ------------ | ------------------------- | ----------------------------------------- |
| `account_id` | `string`     | Yes                       | MT5 account login number                  |
| `equity`     | `float`      | Yes                       | Current account equity                    |
| `balance`    | `float`      | Yes                       | Current account balance                   |
| `symbol`     | `string`     | Yes                       | Symbol the EA is attached to              |
| `ask`        | `float`      | Yes                       | Current ask price                         |
| `bid`        | `float`      | Yes                       | Current bid price                         |
| `trend_h1`   | `string`     | No (default: `"neutral"`) | H1 EMA trend signal                       |
| `trend_h4`   | `string`     | No (default: `"neutral"`) | H4 EMA trend signal                       |
| `positions`  | `Position[]` | No (default: `[]`)        | List of all open positions on the account |

**Position object:**

| Field     | Type      | Required | Description                               |
| --------- | --------- | -------- | ----------------------------------------- |
| `ticket`  | `integer` | Yes      | MT5 position ticket                       |
| `symbol`  | `string`  | Yes      | Position symbol                           |
| `type`    | `string`  | Yes      | `"buy"` or `"sell"`                       |
| `volume`  | `float`   | Yes      | Position size in lots                     |
| `price`   | `float`   | Yes      | Position open price                       |
| `profit`  | `float`   | Yes      | Floating P&L in account currency          |
| `comment` | `string`  | Yes      | Trade comment (used for session matching) |

**Response:** `200 OK` — `application/json`

```json
{
  "actions": [
    {
      "action": "BUY",
      "volume": 0.01,
      "comment": "buy_a1b2c3d4_idx1"
    }
  ]
}
```

On any exception (validation error or internal error), returns `{"actions": []}` with HTTP 200 to ensure the EA always gets a valid response.

See [Section 6 — EA Action Payload Types](#6-ea-action-payload-types) for the full list of possible action objects.

---

## 5. Dashboard & UI Endpoints

All REST endpoints below are prefixed with `/api/v1/ui`. The `{side}` path parameter is always either `"buy"` or `"sell"`. Passing any other value returns `400 Bad Request`.

---

### `WS /api/v1/ui/ws`

**Description:** Persistent WebSocket connection. The server pushes the full `SystemState` JSON every **1 second** to all connected clients. The client does not send messages on this connection.

**Connection URL:** `ws://<host>:8000/api/v1/ui/ws`

**Push Message:** Serialised `SystemState` (see [Section 3 — SystemState](#systemstate))

```json
{
  "ea_connected": true,
  "last_ea_ping_ts": 1743600000.123,
  "account_id": "12345678",
  "symbol": "EURUSD",
  "equity": 10250.50,
  "balance": 10000.00,
  "current_mid": 1.08499,
  "current_ask": 1.08500,
  "current_bid": 1.08498,
  "trend_h1": "buy",
  "trend_h4": "neutral",
  "buy_settings": { ... },
  "buy_state": { ... },
  "sell_settings": { ... },
  "sell_state": { ... }
}
```

The frontend reconnects automatically after a 3-second delay on disconnect.

---

### `POST /api/v1/ui/control/{side}`

**Description:** Turns a grid ON or OFF and sets cyclic mode.

- **Turning OFF while running:** Queues a `CLOSE_ALL` action for the EA and performs a hard reset of the grid state (session cleared, `is_on = false`).
- **Turning ON:** Sets `is_on = true`. The engine will initiate the session anchor on the next qualifying tick.

**Path Parameters:**

| Parameter | Type     | Values              |
| --------- | -------- | ------------------- |
| `side`    | `string` | `"buy"` or `"sell"` |

**Request Body:** `application/json`

```json
{
  "is_on": true,
  "is_cyclic": false
}
```

| Field       | Type      | Required | Description                                             |
| ----------- | --------- | -------- | ------------------------------------------------------- |
| `is_on`     | `boolean` | Yes      | Target power state for the grid                         |
| `is_cyclic` | `boolean` | Yes      | Whether to enable automatic session restart after TP/SL |

**Response:** `200 OK`

```json
{
  "status": "success",
  "is_on": true,
  "is_cyclic": false
}
```

**Error Responses:**

| Status | Body                         | Condition                         |
| ------ | ---------------------------- | --------------------------------- |
| `400`  | `{"detail": "Invalid side"}` | `side` is not `"buy"` or `"sell"` |

---

### `PUT /api/v1/ui/settings/{side}`

**Description:** Replaces the full grid settings for a given side. When the grid is **ON**, the endpoint enforces immutability of executed rows: the `gap` and `lots` of any already-executed row cannot be changed, and executed rows cannot be deleted. The server merges the original executed row data (price, pnl, executed flag) into the new payload before saving.

After saving, `engine.recalculate_grid_math(side)` is called to instantly recompute price targets and cumulative lots.

**Path Parameters:**

| Parameter | Type     | Values              |
| --------- | -------- | ------------------- |
| `side`    | `string` | `"buy"` or `"sell"` |

**Request Body:** `application/json` — A full `GridSettings` object.

```json
{
  "is_on": false,
  "is_cyclic": false,
  "start_limit": null,
  "stop_limit": null,
  "tp_type": "fixed",
  "tp_value": 100.0,
  "sl_type": "fixed",
  "sl_value": 200.0,
  "hedging": 150.0,
  "rows": [
    {
      "index": 0,
      "gap": 50.0,
      "lots": 0.01,
      "alert": true,
      "alert_executed": false,
      "executed": false,
      "price": null,
      "cumulative_lots": 0.0,
      "pnl": 0.0,
      "cumulative_pnl": 0.0
    },
    {
      "index": 1,
      "gap": 100.0,
      "lots": 0.02,
      "alert": false,
      "alert_executed": false,
      "executed": false,
      "price": null,
      "cumulative_lots": 0.0,
      "pnl": 0.0,
      "cumulative_pnl": 0.0
    }
  ]
}
```

**Response:** `200 OK`

```json
{
  "status": "success",
  "message": "BUY settings updated."
}
```

**Error Responses:**

| Status | Body                                                           | Condition                                                         |
| ------ | -------------------------------------------------------------- | ----------------------------------------------------------------- |
| `400`  | `{"detail": "Invalid side"}`                                   | `side` is not `"buy"` or `"sell"`                                 |
| `400`  | `{"detail": "Cannot delete executed row {index}."}`            | Grid is ON and an executed row was removed from the payload       |
| `400`  | `{"detail": "Cannot alter gap/lots of executed row {index}."}` | Grid is ON and the `gap` or `lots` of an executed row was changed |

---

### `POST /api/v1/ui/ack-alert/{side}/{index}`

**Description:** Marks a row's alert as acknowledged. Called by the frontend after playing the notification sound/popup for an executed row. Sets `row.alert_executed = true` for the matching row, which prevents the alert from firing again on subsequent state pushes.

**Path Parameters:**

| Parameter | Type      | Description                                         |
| --------- | --------- | --------------------------------------------------- |
| `side`    | `string`  | `"buy"` or `"sell"`                                 |
| `index`   | `integer` | The `GridRow.index` value of the row to acknowledge |

**Request Body:** None

**Response:** `200 OK`

```json
{
  "status": "success"
}
```

**Error Responses:**

| Status | Body                          | Condition                                                |
| ------ | ----------------------------- | -------------------------------------------------------- |
| `400`  | `{"detail": "Invalid side"}`  | `side` is not `"buy"` or `"sell"`                        |
| `404`  | `{"detail": "Row not found"}` | No row with the given `index` exists in current settings |

---

### `GET /api/v1/ui/presets`

**Description:** Returns all saved presets from the SQLite database.

**Request Body:** None

**Response:** `200 OK` — `application/json`

```json
[
  {
    "id": 1,
    "name": "Gold Scalp 0.01",
    "rows": [
      {
        "index": 0,
        "gap": 50.0,
        "lots": 0.01,
        "alert": true,
        "alert_executed": false,
        "executed": false,
        "price": null,
        "cumulative_lots": 0.0,
        "pnl": 0.0,
        "cumulative_pnl": 0.0
      }
    ]
  }
]
```

Returns an empty array `[]` if no presets exist.

---

### `POST /api/v1/ui/presets`

**Description:** Creates a new named preset. The preset stores only the grid rows (`gap`, `lots`, `alert` values) — not TP/SL, limits, or hedging settings.

**Request Body:** `application/json`

```json
{
  "name": "Gold Scalp 0.01",
  "rows": [
    {
      "index": 0,
      "gap": 50.0,
      "lots": 0.01,
      "alert": true,
      "alert_executed": false,
      "executed": false,
      "price": null,
      "cumulative_lots": 0.0,
      "pnl": 0.0,
      "cumulative_pnl": 0.0
    }
  ]
}
```

| Field  | Type        | Required | Description                               |
| ------ | ----------- | -------- | ----------------------------------------- |
| `name` | `string`    | Yes      | Unique human-readable name for the preset |
| `rows` | `GridRow[]` | Yes      | Grid rows to save                         |

**Response:** `200 OK`

```json
{
  "status": "success",
  "message": "Preset 'Gold Scalp 0.01' saved."
}
```

**Error Responses:**

| Status | Body                                        | Condition                                    |
| ------ | ------------------------------------------- | -------------------------------------------- |
| `400`  | `{"detail": "Preset name already exists."}` | A preset with the same `name` already exists |

---

### `PUT /api/v1/ui/presets/{preset_id}`

**Description:** Updates the name and/or rows of an existing preset.

**Path Parameters:**

| Parameter   | Type      | Description                         |
| ----------- | --------- | ----------------------------------- |
| `preset_id` | `integer` | Database ID of the preset to update |

**Request Body:** `application/json` — Same schema as `POST /presets`.

```json
{
  "name": "Gold Scalp Revised",
  "rows": [...]
}
```

**Response:** `200 OK`

```json
{
  "status": "success",
  "message": "Preset 'Gold Scalp Revised' updated."
}
```

**Error Responses:**

| Status | Body                                        | Condition                                                 |
| ------ | ------------------------------------------- | --------------------------------------------------------- |
| `404`  | `{"detail": "Preset not found."}`           | No preset with given `preset_id`                          |
| `400`  | `{"detail": "Preset name already exists."}` | The new `name` conflicts with a different existing preset |

---

### `DELETE /api/v1/ui/presets/{preset_id}`

**Description:** Permanently deletes a preset from the database.

**Path Parameters:**

| Parameter   | Type      | Description                         |
| ----------- | --------- | ----------------------------------- |
| `preset_id` | `integer` | Database ID of the preset to delete |

**Request Body:** None

**Response:** `200 OK`

```json
{
  "status": "success",
  "message": "Preset 'Gold Scalp 0.01' deleted."
}
```

**Error Responses:**

| Status | Body                              | Condition                        |
| ------ | --------------------------------- | -------------------------------- |
| `404`  | `{"detail": "Preset not found."}` | No preset with given `preset_id` |

---

### `POST /api/v1/ui/presets/{preset_id}/load/{side}`

**Description:** Loads a preset's rows into the live grid settings for the given side. **Constraint:** The target grid must be OFF (`is_on = false`). Only the rows are loaded; all other settings (TP, SL, limits, hedging, `is_on`, `is_cyclic`) remain unchanged. After loading, `recalculate_grid_math()` is called on the engine.

**Path Parameters:**

| Parameter   | Type      | Description                                   |
| ----------- | --------- | --------------------------------------------- |
| `preset_id` | `integer` | Database ID of the preset to load             |
| `side`      | `string`  | `"buy"` or `"sell"` — which grid to load into |

**Request Body:** None

**Response:** `200 OK`

```json
{
  "status": "success",
  "message": "Preset 'Gold Scalp 0.01' loaded to BUY grid."
}
```

**Error Responses:**

| Status | Body                                                 | Condition                         |
| ------ | ---------------------------------------------------- | --------------------------------- |
| `400`  | `{"detail": "Invalid side"}`                         | `side` is not `"buy"` or `"sell"` |
| `400`  | `{"detail": "Cannot load preset while grid is ON."}` | Target grid has `is_on = true`    |
| `404`  | `{"detail": "Preset not found."}`                    | No preset with given `preset_id`  |

---

## 6. EA Action Payload Types

The `POST /api/v1/ea/tick` response body contains `{"actions": [...]}`. Each action is a dict with a mandatory `"action"` key. Below are all possible action types.

### `BUY` — Open a Buy market order

```json
{
  "action": "BUY",
  "volume": 0.01,
  "comment": "buy_a1b2c3d4_idx2"
}
```

| Field     | Type     | Description                                           |
| --------- | -------- | ----------------------------------------------------- |
| `action`  | `"BUY"`  | Action type                                           |
| `volume`  | `float`  | Lots to open                                          |
| `comment` | `string` | Trade comment in format `{session_id}_idx{row_index}` |

---

### `SELL` — Open a Sell market order

```json
{
  "action": "SELL",
  "volume": 0.02,
  "comment": "sell_b9c3d1e2_idx1"
}
```

| Field     | Type     | Description                                           |
| --------- | -------- | ----------------------------------------------------- |
| `action`  | `"SELL"` | Action type                                           |
| `volume`  | `float`  | Lots to open                                          |
| `comment` | `string` | Trade comment in format `{session_id}_idx{row_index}` |

---

### `CLOSE_ALL` — Close all positions matching a comment

```json
{
  "action": "CLOSE_ALL",
  "comment": "buy_a1b2c3d4"
}
```

| Field     | Type          | Description                                                                              |
| --------- | ------------- | ---------------------------------------------------------------------------------------- |
| `action`  | `"CLOSE_ALL"` | Action type                                                                              |
| `comment` | `string`      | Session ID prefix. The EA closes all open positions whose `comment` contains this string |

This action is issued when:

- A TP or SL threshold is hit.
- The user manually turns the grid OFF.
- Zombie trades from a previous session are detected.

---

### `HEDGE` — Open a counter-direction trade with explicit TP/SL

```json
{
  "action": "HEDGE",
  "side": "buy",
  "type": "SELL",
  "volume": 0.06,
  "tp": 1.082,
  "sl": 1.0865,
  "comment": "hedge_buy_a1b2c3d4"
}
```

| Field     | Type                | Description                                                 |
| --------- | ------------------- | ----------------------------------------------------------- |
| `action`  | `"HEDGE"`           | Action type                                                 |
| `side`    | `string`            | The originating grid side (`"buy"` or `"sell"`)             |
| `type`    | `"BUY"` \| `"SELL"` | Direction of the hedge trade (always opposite to `side`)    |
| `volume`  | `float`             | Volume equals `total_cumulative_lots` at hedge trigger time |
| `tp`      | `float`             | Absolute take profit price for the hedge trade              |
| `sl`      | `float`             | Absolute stop loss price for the hedge trade                |
| `comment` | `string`            | Format: `hedge_{session_id}`                                |

---

### `WAIT` — No-op, do nothing

```json
{
  "action": "WAIT"
}
```

Returned by `get_next_ea_action()` (legacy single-action path) when the queue is empty. Not returned by the current bulk `get_and_clear_pending_actions()` path — the bulk path returns an empty array instead.

---

## 7. Frontend API Consumption

The frontend uses **native browser `fetch()`** with no wrapper library. All API calls are centralised in `apps/web/src/services/api.ts`.

### WebSocket (live state)

`App.tsx` establishes a native `WebSocket` connection on mount:

```typescript
const ws = new WebSocket(WS_URL); // WS_URL = VITE_WS_URL or ws://localhost:8000/api/v1/ui/ws
ws.onmessage = (e) => {
  const data: SystemState = JSON.parse(e.data);
  setSystemState(data);
};
```

Reconnect logic: on `onclose`, retry after 3 seconds via `setTimeout`.

### HTTP Calls (from `api.ts`)

All functions use `fetch()` directly. No retry logic, no interceptors, no caching layer.

```typescript
// Toggle grid power and cyclic mode
export const controlSide = (side, is_on, is_cyclic) =>
  fetch(`${API_BASE}/control/${side}`, { method: "POST", ... });

// Replace full grid settings
export const updateSettings = (side, settings: GridSettings) =>
  fetch(`${API_BASE}/settings/${side}`, { method: "PUT", ... });

// Acknowledge a row alert
export const ackAlert = (side, index) =>
  fetch(`${API_BASE}/ack-alert/${side}/${index}`, { method: "POST" });

// Load a preset into the live grid
export const loadPreset = (presetId, side) =>
  fetch(`${API_BASE}/presets/${presetId}/load/${side}`, { method: "POST" });

// Preset CRUD
export const getPresets  = () => fetch(`${API_BASE}/presets`);
export const createPreset = (name, rows) => fetch(`${API_BASE}/presets`, { method: "POST", ... });
export const updatePreset = (presetId, name, rows) => fetch(`${API_BASE}/presets/${presetId}`, { method: "PUT", ... });
export const deletePreset = (presetId) => fetch(`${API_BASE}/presets/${presetId}`, { method: "DELETE" });
```

### State Management

The entire `SystemState` received from the WebSocket is stored in a single `useState<SystemState | null>` in `App.tsx` and passed as props to child components. There is no global state manager (no Redux, no Zustand, no React Query).

`SidePanel.tsx` maintains a local copy of `GridSettings` (`localSettings`) to support unsaved edits. It merges server-managed fields (executed state, prices, pnl) from the WebSocket state into the local copy without overwriting user-edited fields.

---

## 8. Error Responses

All error responses use FastAPI's default `HTTPException` format:

```json
{
  "detail": "Human-readable error message."
}
```

Standard HTTP status codes used:

| Code  | Meaning              | When used                                                                                                       |
| ----- | -------------------- | --------------------------------------------------------------------------------------------------------------- |
| `200` | OK                   | All successful responses, including the EA tick endpoint (even on internal errors)                              |
| `400` | Bad Request          | Invalid `side` param; constraint violations (executed row mutation, grid ON during preset load, name conflicts) |
| `404` | Not Found            | Referenced preset ID does not exist; row index not found for ack-alert                                          |
| `422` | Unprocessable Entity | FastAPI automatic validation failure on malformed request bodies (Pydantic schema mismatch)                     |
