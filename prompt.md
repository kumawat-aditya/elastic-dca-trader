**1. System Architecture**

- **Modular Backend:** FastAPI framework divided into `app/main.py` (entry point), `app/api/v1/` (routers), `app/services/` (core logic), `app/models/` (Pydantic models), and `app/database/` (SQLite DB and ORM).
- **Live Tick Feed:** Server maintains a rolling queue of ~120 ticks (2 minutes of 1-second pings) from the EA. This queue is used by crossover functions to trigger grid row execution.
- **Grid Independence:** The BUY grid and SELL grid are completely decoupled. They have independent lifecycles, hash session IDs, limits, limits, targets, and execution flows.

**2. UI / Dashboard Components**

- **Status Indicators:** Separate connection statuses for the Server (backend) and the EA (MetaTrader).
- **Market Data:** Live display of Mid, Ask, Bid prices.
- **Trend Display:** Shows H1 and H4 trends (calculated and provided directly by the EA; server merely passes it to the UI).
- **Preset Management:** A dedicated "Add Preset" popup/card to save grid configurations into the SQLite database. A dropdown exists to select named presets or "Custom/Manual" mode.
- **Grid Controls (Per Side):** On/Off switch, Cyclic Run switch.
- **Grid Inputs (Per Side):**
  - _Start Limit:_ Float (price anchor) or empty (immediate start).
  - _Stop Limit:_ Integer (max rows) or empty (run all).
  - _Target (TP):_ Type (Fixed $, Equity %, Balance %) and Value.
  - _Stop Loss (SL):_ Type (Fixed $, Equity %, Balance %) and Value.
  - _Hedging:_ Integer (dollar loss trigger) or null (disabled).
- **Grid Data Table:** Columns for Index, Gap ($), Lots, Alert (boolean), Price (executed price), Total Lot (cumulative), PnL (cumulative dynamic), Executed (boolean UI color marker).

**3. Execution Logic & Constraints**

- **Cycle Initiation:** Toggling a grid "ON" generates a new hash session ID, marks the current market price as the reference point (if Start Limit is empty), and begins the execution flow.
- **Start Limit Logic:** If empty, execution evaluates immediately based on current price. If a float value is provided, the server waits and cross-checks the tick queue until the market crosses this limit before anchoring the grid.
- **Cyclic Run:** If enabled, reaching a TP or SL automatically cleans the execution/PnL data, marks a new reference point, generates a new hash ID, and restarts.
- **Preset Application:** Presets can only be loaded if the grid is "OFF" (not running). Running grids are locked from major structural edits.
- **Grid Row Mechanics:**
  - _Gap:_ Dollar distance from the reference point.
  - _Lots:_ Minimum `0.01`.
  - _Alert:_ Triggers a frontend UI notification when crossed, then unmarks itself.
  - _PnL:_ Calculated dynamically by matching EA positions. If the EA skipped opening a trade for a row, its individual PnL is assumed `$0.00` for cumulative calculations.

**4. Risk Management (Target, SL, Hedging)**

- **Take Profit / Stop Loss:** Evaluates cumulative grid PnL against the chosen type (Fixed $, Equity %, Balance %).
- **Hedging Flow:** If cumulative loss hits the Hedging $ input -> Grid execution pauses -> Server instructs EA to open an opposite trade (Volume = total grid cumulative lots) at market price with Hard TP = Hedging loss $, Hard SL = (Hedging loss / 2) $ -> UI shows "Hedge Triggered" with trade details -> Normal grid waits for TP/SL to hit. The hedge trade manages itself via MT5.

**5. Server-EA Synchronization & Failsafes**

- **Ping Cycle:** EA pings 1x/second with MT ID, Equity, Balance, Symbol, Ask, Bid, and Open Positions.
- **Autonomous Cleanup:** If the EA has open positions belonging to an old session ID (for a side that the server has assigned a _new_ session ID), the EA automatically closes them. If it takes multiple attempts, the server ignores the delay and continues flow.
- **Slippage Bypass:** If the EA skips a trade due to slippage rules, the server grid does not break. It marks the row executed, applies `$0` PnL for that row, and continues.
- **Emergency State:** If the server has NO running session (both sides OFF) but the EA reports active EA-managed positions, the server flags an Emergency State: UI displays "Unknown trades opened on account, please manage/close them first".
- **Disconnect Timeout:** If the EA stops pinging for >10 seconds -> Server stops running cycles, clears PnL, nullifies session IDs, and turns Cyclic OFF. If it reconnects _within_ 10 seconds -> Execution resumes normally.
