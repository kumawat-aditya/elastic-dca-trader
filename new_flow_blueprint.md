
**1. System Architecture & Protocols**
*   **Modular Backend:** FastAPI framework logically divided into `app/main.py` (entry point), `app/api/v1/` (routers), `app/services/` (core logic), `app/models/` (Pydantic models), and `app/database/` (SQLite DB and ORM).
*   **Communication Protocols:** 
    *   **EA <-> Server:** Standard REST API. The EA sends POST requests (ticks) and receives JSON responses.
    *   **Server <-> UI:** WebSockets. The server pushes live tick data, grid updates, and UI alerts directly to the frontend for a smooth, low-latency dashboard experience.
*   **Environment Configuration:** All major system constraints (like the EA disconnect timeout, server port, etc.) are customizable via a `.env` file, meaning logic can be adjusted without touching source code.
*   **Live Tick Feed:** Server maintains a rolling queue of ~120 ticks (2 minutes of 1-second pings) from the EA. This queue is used by crossover functions to trigger grid row execution.
*   **Grid Independence:** The BUY grid and SELL grid are completely decoupled. They have independent lifecycles, hash session IDs, limits, targets, emergency states, and execution flows.

**2. UI / Dashboard Components**
*   **Status Indicators:** Separate connection statuses for the Server (backend) and the EA (MetaTrader).
*   **Market Data:** Live display of Mid, Ask, Bid prices.
*   **Trend Display:** Shows H1 and H4 trends (calculated and provided directly by the EA; server merely passes it to the UI via WebSocket).
*   **Preset Management:** A dedicated "Add Preset" popup/card to save grid configurations into the SQLite database. A dropdown exists to select named presets or a "Custom/Manual" mode.
*   **Grid Controls (Per Side):** On/Off switch, Cyclic Run switch.
*   **Grid Inputs (Per Side):** 
    *   *Start Limit:* Float (price anchor) or empty (immediate start).
    *   *Stop Limit:* Integer (max rows) or empty (run all).
    *   *Target (TP):* Type (Fixed $, Equity %, Balance %) and Value.
    *   *Stop Loss (SL):* Type (Fixed $, Equity %, Balance %) and Value.
    *   *Hedging:* Integer (dollar loss trigger) or null (disabled).
*   **Grid Data Table:** Columns for Index, Gap ($), Lots, Alert (boolean), Price (executed price), Total Lot (cumulative), PnL (cumulative dynamic), Executed (boolean UI color marker).

**3. Execution Logic & Constraints**
*   **Cycle Initiation:** Toggling a grid "ON" generates a new hash session ID, marks the current market price as the reference point (if Start Limit is empty), and begins the execution flow.
*   **Start Limit Logic:** If empty, execution evaluates immediately based on current price. If a float value is provided, the server waits and cross-checks the tick queue until the market crosses this limit before anchoring the grid.
*   **Cyclic Run & Cleanup:** If enabled, reaching a TP or SL automatically triggers a new cycle. The server **clears execution markers, PnL data, and the executed Price values** of the old cycle. It generates a new hash ID, sets a new reference point, and recalculates the target prices for the new cycle based on the gaps.
*   **Preset Application:** Presets can only be loaded if the grid is "OFF" (not running). Running grids are locked from major structural edits.
*   **Grid Row Mechanics:** 
    *   *Gap:* Dollar distance from the reference point.
    *   *Lots:* Minimum `0.01`.
    *   *Alert:* Triggers a frontend UI WebSocket notification when crossed, then unmarks itself.
    *   *Price:* The specific price calculated for this row to execute at. Cleared and dynamically recalculated at the start of every new cycle.
    *   *PnL:* The Server **does not calculate PnL**. The EA is the absolute source of truth. The server reads the exact PnL from the EA's `positions` array, maps it to the respective row, and sums it for the cumulative UI display. If the EA skipped opening a trade for a row, its individual PnL is tracked as `$0.00`.

**4. Risk Management (Target, SL, Hedging)**
*   **Take Profit / Stop Loss:** Evaluates the exact cumulative grid PnL provided by the EA against the chosen type (Fixed $, Equity %, Balance %).
*   **Hedging Flow:** If cumulative loss hits the Hedging $ input -> Grid execution pauses -> Server instructs EA to open an opposite trade (Volume = total grid cumulative lots) at market price with Hard TP = Hedging loss $, Hard SL = (Hedging loss / 2) $ -> UI shows "Hedge Triggered" with trade details -> Normal grid waits for TP/SL to hit. The hedge trade manages itself autonomously via MT5.

**5. Server-EA Synchronization & Failsafes**
*   **Ping Cycle:** EA pings 1x/second via REST with MT ID, Equity, Balance, Symbol, Ask, Bid, and Open Positions.
*   **Autonomous Cleanup:** If the EA has open positions belonging to an old session ID (for a side that the server has assigned a *new* session ID), the EA automatically closes them. If it takes multiple attempts, the server ignores the delay and continues flow.
*   **Slippage Bypass:** If the EA skips a trade due to slippage rules, the server grid does not break. It marks the row executed, maps `$0` PnL for that row from the EA, and continues to the next.
*   **Decoupled Emergency State:** Emergencies are strictly separated by side. If the server has a null session ID for BUY, but the EA reports active BUY trades mapped to our system, the server flags a **BUY Emergency**: UI displays "Unknown Buy trades opened on account, please manage/close them first". The SELL grid continues operating normally if its session is intact.
*   **Configurable Disconnect Timeout:** If the EA stops pinging for greater than the `.env` timeout threshold (e.g., `EA_TIMEOUT_SECONDS=10`) -> Server stops running cycles, clears PnL, clears executed Prices, nullifies session IDs, and turns Cyclic OFF. If it reconnects *within* the threshold -> Execution resumes normally as if nothing happened.