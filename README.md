# Elastic DCA Engine v4

> A full-stack, server-centric algorithmic trading system for automated Dollar Cost Averaging (DCA) grid strategies on MetaTrader 5.

---

## What It Does

The Elastic DCA Engine separates trading intelligence from the MetaTrader 5 terminal. A Python server acts as the persistent state machine; the MQL5 Expert Advisor is a stateless HTTP client that polls the server every second, receives trade instructions, and executes them. A React dashboard provides live visualisation and runtime control of dual independent buy/sell grids.

**Core capabilities:**

- Runs independent buy and sell DCA grids simultaneously on any MT5 symbol.
- Automatically executes grid rows (BUY/SELL market orders) when price crosses user-defined levels.
- Monitors cumulative P&L and triggers Take Profit or Stop Loss closes (fixed dollar, equity %, or balance %).
- Deploys an automated hedge (counter-trade) when floating loss exceeds a configurable threshold.
- Supports cyclic mode: automatically restarts a new session after TP/SL is hit.
- Detects orphaned and zombie trades left by previous sessions and cleans them up.
- Persists named grid row presets to SQLite for reuse.

---

## Tech Stack

| Layer                  | Technology                       |
| ---------------------- | -------------------------------- |
| **Backend Language**   | Python 3.10+                     |
| **Web Framework**      | FastAPI 0.100+                   |
| **ASGI Server**        | Uvicorn (with `standard` extras) |
| **Data Validation**    | Pydantic v2, pydantic-settings   |
| **Database ORM**       | SQLAlchemy 2.0                   |
| **Database**           | SQLite (file: `elastic_dca.db`)  |
| **Frontend Language**  | TypeScript 5.8                   |
| **Frontend Framework** | React 19                         |
| **Build Tool**         | Vite 6                           |
| **Styling**            | Tailwind CSS 4                   |
| **UI Notifications**   | Sonner                           |
| **UI Icons**           | Lucide React                     |
| **Motion**             | Motion (Framer Motion)           |
| **EA Language**        | MQL5 (MetaTrader 5)              |

---

## Prerequisites

- **Python 3.10+** — [python.org](https://www.python.org/downloads/)
- **Node.js 20+ & npm** — [nodejs.org](https://nodejs.org/)
- **MetaTrader 5 Terminal** — with a live or demo broker account
- The MQL5 Expert Advisor (`scripts/automation.mq5`) compiled and attached to a chart in MT5

---

## Installation & Running Locally

### 1 — Backend Server

```bash
cd apps/server

# Install Python dependencies
pip install -r requirements.txt

# (Optional) Create a .env file with your overrides
# See the Environment Variables section below

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server starts at `http://0.0.0.0:8000`. The SQLite database file (`elastic_dca.db`) is created automatically in `apps/server/` on first run.

### 2 — Frontend Dashboard

```bash
cd apps/web

# Install Node dependencies
npm install

# (Optional) Create a .env file for custom API URLs
# See the Environment Variables section below

# Start the development server
npm run dev
```

The dashboard is available at `http://localhost:3000`.

### 3 — MetaTrader 5 Expert Advisor

1. Open MetaTrader 5.
2. Copy `scripts/automation.mq5` to the `MQL5/Experts` folder in your MT5 data directory.
3. Compile the script in the MetaEditor.
4. Attach the EA to a chart. Configure the server URL to point to `http://<your-server-ip>:8000`.

> **Order of startup:** Start the Python server **before** attaching the EA. The server must be reachable when the EA sends its first tick.

---

## Environment Variables

### Backend (`apps/server/.env`)

| Variable               | Default   | Description                                                                                            |
| ---------------------- | --------- | ------------------------------------------------------------------------------------------------------ |
| `HOST`                 | `0.0.0.0` | Server bind address                                                                                    |
| `PORT`                 | `8000`    | Server listen port                                                                                     |
| `EA_TIMEOUT_SECONDS`   | `10`      | Seconds without an EA tick before the engine marks the EA as disconnected and resets both grids        |
| `CROSSOVER_TICK_COUNT` | `5`       | Reserved — stored in settings, not currently used in crossover logic                                   |
| `HEDGE_TP_PCT`         | `100.0`   | Hedge Take Profit as a percentage of the distance from the reference point to the current market price |
| `HEDGE_SL_PCT`         | `50.0`    | Hedge Stop Loss as a percentage of the hedge TP distance                                               |
| `LOG_LEVEL`            | `DEBUG`   | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)                                             |

### Frontend (`apps/web/.env`)

| Variable         | Default                            | Description                                                                                          |
| ---------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `VITE_API_URL`   | `http://localhost:8000/api/v1/ui`  | Base URL for all REST API calls from the dashboard                                                   |
| `VITE_WS_URL`    | `ws://localhost:8000/api/v1/ui/ws` | WebSocket URL for the live state stream                                                              |
| `GEMINI_API_KEY` | —                                  | Google Gemini API key (exposed to the client via `vite.config.ts`; unused in current dashboard code) |

---

## Folder Structure

```
├── apps/
│   ├── server/                    # Python FastAPI backend
│   │   ├── main.py                # App bootstrap, CORS, router registration, lifespan
│   │   ├── requirements.txt       # Python dependencies
│   │   └── app/
│   │       ├── config.py          # Environment-driven settings (pydantic-settings)
│   │       ├── logger.py          # Root logging configuration
│   │       ├── database/
│   │       │   ├── models.py      # SQLAlchemy ORM model (PresetDB)
│   │       │   └── session.py     # DB engine, session factory, get_db dependency
│   │       ├── models/
│   │       │   └── schemas.py     # Pydantic models: TickData, SystemState, GridSettings, etc.
│   │       ├── routers/
│   │       │   ├── ea_api.py      # POST /api/v1/ea/tick  (EA communication)
│   │       │   └── ui_api.py      # WebSocket + REST /api/v1/ui/* (dashboard)
│   │       └── services/
│   │           └── engine.py      # DcaEngine singleton — the core state machine
│   │
│   └── web/                       # React + TypeScript frontend
│       ├── src/
│       │   ├── App.tsx            # Root component: WebSocket connection + global state
│       │   ├── types.ts           # TypeScript interfaces mirroring backend Pydantic models
│       │   ├── services/
│       │   │   └── api.ts         # All HTTP fetch calls to /api/v1/ui/*
│       │   └── components/
│       │       ├── TopBar.tsx     # Market data bar (symbol, ask/bid/mid, trends, account)
│       │       ├── SidePanel.tsx  # Full grid control panel for one side (buy or sell)
│       │       ├── GridTable.tsx  # Grid row visualiser table
│       │       ├── NumberInput.tsx # Controlled numeric input component
│       │       ├── CreatePresetModal.tsx  # Create / edit preset modal
│       │       └── ManagePresetsModal.tsx # Preset list management modal
│       ├── package.json
│       └── vite.config.ts
│
├── scripts/
│   └── automation.mq5             # MQL5 Expert Advisor (MT5 client bridge)
│
├── docs/
│   ├── ARCHITECTURE.md            # System architecture, diagrams, design patterns
│   └── API_REFERENCE.md           # Complete API contract documentation
│
└── infra/
    └── aws/                       # AWS deployment guides
```

---

## Quick Links

- [Architecture & System Design](docs/ARCHITECTURE.md)
- [API Reference](docs/API_REFERENCE.md)
