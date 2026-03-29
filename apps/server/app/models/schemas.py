from pydantic import BaseModel, Field
from typing import List, Optional, Dict

# --- EA Communication Payloads ---
class Position(BaseModel):
    ticket: int
    symbol: str
    type: str
    volume: float
    price: float
    profit: float
    comment: str

class TickData(BaseModel):
    account_id: str
    equity: float
    balance: float
    symbol: str
    ask: float
    bid: float
    trend_h1: str = "neutral"
    trend_h4: str = "neutral"
    positions: List[Position] =[]

# --- Grid Data Models ---
class GridRow(BaseModel):
    index: int
    gap: float
    lots: float
    alert: bool = False
    alert_executed: bool = False
    executed: bool = False
    price: Optional[float] = None
    cumulative_lots: float = 0.0
    pnl: float = 0.0
    cumulative_pnl: float = 0.0

class GridSettings(BaseModel):
    # Controls
    is_on: bool = False
    is_cyclic: bool = False
    
    # Risk Management
    start_limit: Optional[float] = None
    stop_limit: Optional[int] = None
    
    tp_type: str = "fixed" # "fixed", "equity", "balance"
    tp_value: float = 0.0
    
    sl_type: str = "fixed" # "fixed", "equity", "balance"
    sl_value: float = 0.0
    
    hedging: Optional[float] = None # Dollar amount to trigger hedge
    
    # Rows
    rows: List[GridRow] =[]

class HedgeData(BaseModel):
    entry_price: float
    sl: float
    tp: float
    lots: float

# --- System & Session State ---
class GridState(BaseModel):
    """Tracks the live runtime metrics of a single grid side (Decoupled)"""
    session_id: Optional[str] = None
    reference_point: Optional[float] = None
    is_hedged: bool = False
    hedge_data: Optional[HedgeData] = None
    emergency_state: bool = False
    total_cumulative_lots: float = 0.0
    total_cumulative_pnl: float = 0.0

class SystemState(BaseModel):
    """The master state returned to the UI via WebSockets"""
    buy_settings: GridSettings = Field(default_factory=GridSettings)
    buy_state: GridState = Field(default_factory=GridState)
    
    sell_settings: GridSettings = Field(default_factory=GridSettings)
    sell_state: GridState = Field(default_factory=GridState)
    
    ea_connected: bool = False
    last_ea_ping_ts: float = 0.0

    account_id: str = ""
    symbol: str = ""
    equity: float = 0.0
    balance: float = 0.0
    
    current_mid: float = 0.0
    current_ask: float = 0.0
    current_bid: float = 0.0
    trend_h1: str = "neutral"
    trend_h4: str = "neutral"