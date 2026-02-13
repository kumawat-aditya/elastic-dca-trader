### Phase 2 Blueprint: "The Master-Slave Protocol"

### 1. Authentication & Security
*   **Admin:**
    *   Credentials (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `ADMIN_MT5_ID`) stored in `.env`.
    *   **Reasoning:** Fast, secure, zero database maintenance for the super-user.
*   **Users (Clients):**
    *   Stored in PostgreSQL.
    *   **Role:** Strictly read-only on the UI. MQL script provides the heartbeat.

### 2. Database Schema (PostgreSQL)

We need three distinct tables.

#### A. Table `users`
*Basic identity management.*
```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    mt5_id VARCHAR(50) UNIQUE NOT NULL, -- The link to the MQL script
    tier_id INTEGER REFERENCES tiers(id), -- Explicitly link user to a Tier
    status VARCHAR(20) DEFAULT 'pending', -- 'pending', 'active', 'banned'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```
*(Note: I added `tier_id` here. While you mentioned checking balance to find the tier, it is safer to assign a user to a specific Tier ID. This prevents them from jumping tiers automatically if their balance fluctuates slightly.)*

#### B. Table `tiers` (The "Master Brain")
*This table holds the Strategy Configuration AND the Live Execution Status (Triggers).*
```sql
CREATE TABLE tiers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50), -- e.g., "5k-10k Aggressive"
    symbol VARCHAR(20), -- e.g., "XAUUSD"
    
    -- CONFIGURATION (The Settings)
    settings JSONB, 
    /* Contains:
       buy_limit, sell_limit, tp_settings, hedge_settings, 
       rows_buy: [{idx, dollar, lots, alert}], 
       rows_sell: [...]
    */

    -- RUNTIME STATE (The Live Triggers)
    state JSONB,
    /* Contains:
       buy_on: bool, sell_on: bool,
       buy_cyclic: bool, sell_cyclic: bool,
       buy_id: "hash123", sell_id: "hash456",
       buy_start_ref: 2000.50, ...
    */
    
    -- THE TRIGGER MAP (The Progress Bar)
    triggers JSONB DEFAULT '{"buy": [], "sell": []}',
    /* Contains list of triggered row indices.
       e.g., "buy": [0, 1, 2] -> Rows 0, 1, and 2 are active on the Master.
    */

    updated_at TIMESTAMP
);
```

#### C. Table `user_snapshots` (The Monitoring Feed)
*Stores the data sent by the User's MQL ping. Used strictly for UI display.*
```sql
CREATE TABLE user_snapshots (
    user_id INTEGER PRIMARY KEY REFERENCES users(id),
    equity DECIMAL(15, 2),
    balance DECIMAL(15, 2),
    open_positions JSONB, -- The full list of tickets sent by MQL
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 3. The "Master Engine" (Admin Service)
*This service runs on the server, listens to the Admin's MT5 Data, and updates the `tiers` table.*

1.  **Input:** Receives price tick from Admin's VPS (The "Truth").
2.  **Process:**
    *   Checks `tiers.state` (Is Buy On? Is Cyclic On?).
    *   Checks `tiers.settings` (Where are the grid lines?).
    *   **Logic:**
        *   If Market Price crosses a Grid Line -> Update `tiers.triggers`.
        *   Example: Price drops to $2000. Grid Row 1 is at $2000.
        *   **Action:** Add `1` to `tiers.triggers['buy']`.
    *   **Cycle Reset:** If Admin hits TP/Close, generate new `buy_id`/`sell_id` and clear `triggers`.
3.  **Output:** Updates the Database. **It does NOT talk to clients directly.**

---

### 4. The "Slave Logic" (Client Sync Service)
*This handles the MQL pings from clients. It compares Client State vs. Tier State.*

**The Flow:**
1.  **Receive Ping:** Client sends `{mt5_id, equity, positions: [...]}`.
2.  **Identify:** Look up `user` by `mt5_id`. Get their assigned `tier_id`.
3.  **Load Truth:** Load the `tiers` row for that ID (Get `triggers`, `buy_id`, `settings`).
4.  **Save Snapshot:** Update `user_snapshots` table (for UI).
5.  **The Comparison Logic (Your 3 Cases):**

#### Case 1: ID Mismatch (Cycle Cleanup)
*   **Condition:** Client has open positions with comment `buy_OLDHASH`. Master Tier has `buy_NEWHASH`.
*   **Action:** Server returns `CLOSE_ALL` for the old hash.
*   **Result:** Client cleans up old trades.

#### Case 2: New Entry / Late Entry
*   **Condition:** Client has **Zero** positions. Master has active `buy_id`.
*   **Check:** Count how many rows are in `tiers.triggers['buy']`.
    *   **If Count == 1 (Just started):**
        *   **Action:** Return `OPEN_BUY` for Row 0.
    *   **If Count > 1 (e.g., 5 rows triggered):**
        *   **Action:** Return `WAIT`.
        *   **Reason:** Client is late. Entering now would ruin the mathematical safety of the grid. They must wait for the next cycle.

#### Case 3: The Catch-Up (Synchronization)
*   **Condition:** Client has positions matching the current `buy_id`.
*   **Comparison:**
    *   Client has Row 0, 1 (2 trades).
    *   Master has Row 0, 1, 2 (3 triggers).
*   **Action:** Server detects `Row 2` is in Master Triggers but missing from Client Positions.
*   **Response:** Return `OPEN_BUY` for Row 2.
*   **Edge Case (Lag):** If Client has Row 0, and Master has Row 0, 1, 2. The server returns a list: `[OPEN Row 1, OPEN Row 2]`. This forces the client to catch up immediately.

---

### 5. Questions & Refinements for You

This architecture is solid, but I have 3 specific questions to finalize the code structure:

1.  **Tier Assignment:** Do you agree to add `tier_id` to the `users` table? relying on "Balance Checks" is risky. If a user withdraws money, they might drop from "$10k Tier" to "$5k Tier" instantly, causing their EA to suddenly trade with different logic mid-cycle. **Hard-coding the Tier ID is safer.**
2.  **MQL Response Format:** Since a user might need to open *multiple* trades to catch up (Case 3), is it okay if the API response is a **JSON Array** of commands?
    *   Example: `{"actions": [{"type": "BUY", "lots": 0.1, "comment": "...idx1"}, {"type": "BUY", "lots": 0.2, "comment": "...idx2"}]}`
3.  **Manual Admin Intervention:** If you (Admin) manually close a trade on your MT5, the Master Engine detects this. Should it effectively force a `CLOSE_ALL` command to all users in that Tier immediately? (I assume Yes).

If you agree with these points, I can start generating the **Database Models (SQLAlchemy)** and the **Server Logic** code.