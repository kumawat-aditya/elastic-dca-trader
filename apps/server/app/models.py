"""
Pydantic models matching the SaaS Blueprint v4 data structures.

Blueprint references:
  - Section 5.4  : GridRow structure
  - Section 5.6  : GridConfig / GridRuntime models
  - Section 4    : Tier model
  - Section 9.6  : MarketState model
  - Section 11.1 : MasterTick request model
  - Section 11.4 : Admin API request/response models
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Grid Row (Section 5.4) ──────────────────────────────────────────────────

class GridRow(BaseModel):
    """A single strata level in a grid."""
    index: int                                  # 0-based position
    dollar: float = 0.0                         # Gap from previous level (price units)
    lots: float = 0.01                          # Volume
    alert: bool = False                         # Triggers UI/audio alert on execution
    executed: bool = False                      # Server-managed
    entry_price: float = 0.0                    # Set when executed
    executed_at: str = ""                       # ISO timestamp, empty if not executed


# ── Grid Config (Section 5.6 — admin-editable) ──────────────────────────────

class GridConfig(BaseModel):
    """Per-grid settings."""
    grid_id: str                                # "B1", "B2", "S1", "S2"
    on: bool = False
    cyclic: bool = False
    start_limit: float = 0.0
    end_limit: float = 0.0
    tp_type: str = "fixed_money"                # equity_pct | balance_pct | fixed_money
    tp_value: float = 0.0
    rows: List[GridRow] = Field(default_factory=list)


# ── Grid Runtime (Section 5.6 — server-managed) ─────────────────────────────

class GridRuntime(BaseModel):
    """Per-grid runtime state."""
    grid_id: str
    session_id: str = ""                        # e.g. "B1_a1b2c3d4"
    is_active: bool = False
    waiting_limit: bool = False
    start_ref: float = 0.0                      # Anchor price for current session
    last_order_ts: float = 0.0                  # Sync-Shield grace period timestamp


# ── Tier (Section 4 + 9.3) ──────────────────────────────────────────────────

class Tier(BaseModel):
    id: int = 0
    name: str                                   # "1k-4k", "4k-8k", etc.
    symbol: str = "XAUUSD"
    min_balance: float
    max_balance: float
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ── Market State (Section 9.6) ──────────────────────────────────────────────

class MarketState(BaseModel):
    """Latest price feed from Master EA."""
    symbol: str = "XAUUSD"
    ask: float = 0.0
    bid: float = 0.0
    mid: float = 0.0
    contract_size: float = 100.0                # From Master EA (SymbolInfoDouble)
    direction: str = "neutral"                  # "up", "down", "neutral"
    last_update: Optional[str] = None


# ── In-Memory Tier State (combines config + runtime for all 4 grids) ────────

GRID_IDS = ["B1", "B2", "S1", "S2"]


class TierState(BaseModel):
    """Complete in-memory state for one tier (4 grids)."""
    tier: Tier
    configs: dict[str, GridConfig] = Field(default_factory=dict)     # keyed by grid_id
    runtimes: dict[str, GridRuntime] = Field(default_factory=dict)   # keyed by grid_id


# ── API Request / Response Models ────────────────────────────────────────────

# Section 11.1 — Master tick
class MasterTickRequest(BaseModel):
    ask: float
    bid: float
    contract_size: float = 100.0


# Section 11.4 — Admin: create tier
class CreateTierRequest(BaseModel):
    name: str
    min_balance: float
    max_balance: float


# Section 11.4 — Admin: update tier
class UpdateTierRequest(BaseModel):
    name: Optional[str] = None
    min_balance: Optional[float] = None
    max_balance: Optional[float] = None
    is_active: Optional[bool] = None


# Section 11.4 — Admin: update grid config
class GridRowInput(BaseModel):
    """Row data submitted by admin (no server-managed fields)."""
    index: int
    dollar: float = 0.0
    lots: float = 0.01
    alert: bool = False


class UpdateGridConfigRequest(BaseModel):
    start_limit: Optional[float] = None
    end_limit: Optional[float] = None
    tp_type: Optional[str] = None
    tp_value: Optional[float] = None
    rows: Optional[List[GridRowInput]] = None


# Section 11.4 — Admin: grid control (ON/OFF, cyclic)
class GridControlRequest(BaseModel):
    on: Optional[bool] = None
    cyclic: Optional[bool] = None
