import time
import uuid
from collections import deque
from typing import List
from app.models.schemas import SystemState, TickData, Position, HedgeData
from app.config import settings
from app.logger import get_logger

# Initialize the logger for this file
logger = get_logger(__name__)

class DcaEngine:
    def __init__(self):
        self.state = SystemState()
        # Rolling queue for the last ~120 ticks (2 minutes at 1 ping/sec)
        self.tick_queue = deque(maxlen=120)

        self.ticks_processed = 0

        # Action queue for the EA to pick up on its next 1-second ping
        self.pending_ea_actions =[]
    
    def update_from_tick(self, tick: TickData):
        """Called every second by the EA ping."""
        now = time.time()

        self.ticks_processed += 1 

        self.state.last_ea_ping_ts = now
        self.state.ea_connected = True
        
        self.state.account_id = tick.account_id
        self.state.symbol = tick.symbol
        self.state.equity = tick.equity
        self.state.balance = tick.balance

        # Update Market Data
        self.state.current_ask = tick.ask
        self.state.current_bid = tick.bid
        self.state.current_mid = (tick.ask + tick.bid) / 2
        self.state.trend_h1 = tick.trend_h1
        self.state.trend_h4 = tick.trend_h4
        
        # Append to queue for crossover logic
        self.tick_queue.append({
            "ts": now,
            "ask": tick.ask,
            "bid": tick.bid,
            "mid": self.state.current_mid
        })
        
        # 2. Check Emergencies (Orphan trades without server session)
        self._check_emergency_state("buy", tick.positions)
        self._check_emergency_state("sell", tick.positions)
        
        # 3. Map PnL & Volumes from EA (Absolute source of truth)
        self._map_positions_and_pnl("buy", tick.positions)
        self._map_positions_and_pnl("sell", tick.positions)
        
        # 4. Evaluate TP/SL (Snap-Back / Stop Out)
        self._evaluate_tp_sl("buy", tick)
        self._evaluate_tp_sl("sell", tick)
        
        # 5. Evaluate Hedging
        self._evaluate_hedging("buy")
        self._evaluate_hedging("sell")
        
        # 6. Evaluate Cycle Initiation
        self._evaluate_cycle_start("buy")
        self._evaluate_cycle_start("sell")
        
        # 7. Evaluate Grid Executions
        self._evaluate_grid_rows("buy")
        self._evaluate_grid_rows("sell")
        
    def generate_session_id(self, side: str) -> str:
        """Generates a unique decoupled hash ID"""
        return f"{side}_{uuid.uuid4().hex[:8]}"
        
    def check_ea_timeout(self):
        """Background task/check to trigger Emergency Disconnect"""
        now = time.time()
        if self.state.ea_connected and (now - self.state.last_ea_ping_ts > settings.EA_TIMEOUT_SECONDS):
            self.state.ea_connected = False
            logger.warning("EA Disconnected! Threshold exceeded. Resetting states and halting engine.")
            
            # Disable Cyclic & Clear states for Buy
            self.state.buy_settings.is_cyclic = False
            self._clear_grid_cycle(side="buy", hard_reset=True)
            
            # Disable Cyclic & Clear states for Sell
            self.state.sell_settings.is_cyclic = False
            self._clear_grid_cycle(side="sell", hard_reset=True)

    # --- MATH RECALCULATION HELPER ---
    def recalculate_grid_math(self, side: str):
        """Called on Cycle Start and via UI updates to compute prices and lots."""
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        
        cum_lots = 0.0
        ref = grid_state.reference_point
        
        for row in grid_settings.rows:
            cum_lots += row.lots
            row.cumulative_lots = cum_lots
            
            if ref is not None:
                if side == "buy":
                    ref -= row.gap
                else:
                    ref += row.gap
                row.price = ref
            else:
                row.price = None

    # --- PNL MAPPING, EMERGENCY & ZOMBIE CLEANUP ---
    def _check_emergency_state(self, side: str, positions: List[Position]):
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        prefix = f"{side}_"
        
        # 1. SCENARIO A: Server is OFF / Reset (No active session)
        if grid_state.session_id is None:
            orphan_exists = any(p.comment.startswith(prefix) for p in positions)
            if orphan_exists and not grid_state.emergency_state:
                logger.warning(f"[{side.upper()}] EMERGENCY STATE: Orphaned MT5 trades detected while server grid is OFF.")
            grid_state.emergency_state = orphan_exists
            return

        # 2. SCENARIO B: Server is actively running a session
        grid_state.emergency_state = False
        active_session = grid_state.session_id
        
        # Hunt for Zombie Trades (Trades belonging to this side, but NOT the active session)
        zombie_sessions = set()
        for p in positions:
            if p.comment.startswith(prefix) and active_session not in p.comment:
                parts = p.comment.split("_idx")
                if len(parts) > 0:
                    zombie_sessions.add(parts[0])
                    
        # Issue CLOSE_ALL commands for any zombie sessions found
        for old_session in zombie_sessions:
            already_queued = any(
                a["action"] == "CLOSE_ALL" and a["comment"] == old_session 
                for a in self.pending_ea_actions
            )
            if not already_queued:
                logger.warning(f"[{side.upper()}] ZOMBIE DETECTED: Leftover trades from {old_session}. Queuing CLOSE_ALL.")
                self.pending_ea_actions.append({
                    "action": "CLOSE_ALL", 
                    "comment": old_session
                })

    def _map_positions_and_pnl(self, side: str, positions: List[Position]):
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        
        if not grid_state.session_id:
            return
            
        # Filter EA positions belonging to THIS specific active session
        session_positions = [p for p in positions if grid_state.session_id in p.comment]
        
        # Sum Cumulative
        grid_state.total_cumulative_lots = sum(p.volume for p in session_positions)
        grid_state.total_cumulative_pnl = sum(p.profit for p in session_positions)
        
        # Map Row PnL & calculate rolling cumulative
        running_pnl = 0.0
        for row in grid_settings.rows:
            if row.executed:
                expected_comment = f"{grid_state.session_id}_idx{row.index}"
                matching_pos = next((p for p in session_positions if p.comment == expected_comment), None)
                row.pnl = matching_pos.profit if matching_pos else 0.0
                # 
                running_pnl += row.pnl
                row.cumulative_pnl = running_pnl
            else:
                row.pnl = 0.0

    # --- TP / SL & CYCLIC LOGIC ---
    def _evaluate_tp_sl(self, side: str, tick: TickData):
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        
        if not grid_state.session_id or grid_state.total_cumulative_lots == 0:
            return
            
        pnl = grid_state.total_cumulative_pnl
        
        def get_target(target_type, value):
            if value <= 0: return None
            if target_type == "fixed": return value
            if target_type == "equity": return tick.equity * (value / 100.0)
            if target_type == "balance": return tick.balance * (value / 100.0)
            return None
            
        tp_target = get_target(grid_settings.tp_type, grid_settings.tp_value)
        sl_target = get_target(grid_settings.sl_type, grid_settings.sl_value)
        
        close_reason = None
        if tp_target is not None and pnl >= tp_target:
            close_reason = "TP"
        elif sl_target is not None and pnl <= -sl_target:
            close_reason = "SL"
            
        if close_reason:
            logger.info(f"[{side.upper()}] {close_reason} Hit! PnL: ${pnl:.2f}. Closing Session: {grid_state.session_id}")
            
            self.pending_ea_actions.append({
                "action": "CLOSE_ALL",
                "comment": grid_state.session_id
            })
            
            if close_reason == "SL":
                # SL hit: turn off the grid completely and disable cyclic — requires manual restart
                logger.info(f"[{side.upper()}] SL Hit. Disabling grid switch and cyclic. Manual restart required.")
                grid_settings.is_cyclic = False
                self._clear_grid_cycle(side, hard_reset=True)
            else:
                # TP hit: respect cyclic setting
                is_cyclic = grid_settings.is_cyclic
                if is_cyclic:
                    logger.info(f"[{side.upper()}] Cyclic Restart Enabled. Preparing for new cycle.")
                self._clear_grid_cycle(side, hard_reset=not is_cyclic)

    # --- HEDGING MATH LOGIC ---
    def _evaluate_hedging(self, side: str):
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        
        if grid_settings.hedging is None or not grid_state.session_id or grid_state.is_hedged: 
            return
            
        if grid_state.total_cumulative_pnl <= -abs(grid_settings.hedging):
            grid_state.is_hedged = True
            
            current_market_price = self.state.current_bid if side == "buy" else self.state.current_ask
            ask = self.state.current_ask
            bid = self.state.current_bid
            spread_buffer = abs(ask - bid)
            distance_base = abs(grid_state.reference_point - current_market_price)
            tp_distance = distance_base * (settings.HEDGE_TP_PCT / 100.0)
            sl_distance = tp_distance * (settings.HEDGE_SL_PCT / 100.0)
            
            if side == "buy":
                # Hedge = SELL
                entry_price = bid  # SELL executes at BID
                hard_tp = entry_price - tp_distance
                hard_sl = entry_price + sl_distance
                trade_type = "SELL"

            else:
                # Hedge = BUY
                entry_price = ask  # BUY executes at ASK
                hard_tp = entry_price + tp_distance
                hard_sl = entry_price - sl_distance
                trade_type = "BUY"

            # Final MT5-safe validation
            if trade_type == "BUY":
                if hard_sl >= bid:
                    hard_sl = bid - (spread_buffer + 10)  # extra buffer
                if hard_tp <= ask:
                    hard_tp = ask + (spread_buffer + 10)

            elif trade_type == "SELL":
                if hard_sl <= ask:
                    hard_sl = ask + (spread_buffer + 10)
                if hard_tp >= bid:
                    hard_tp = bid - (spread_buffer + 10)
                
            logger.info(f"[{side.upper()}] HEDGE TRIGGERED! Loss: ${grid_state.total_cumulative_pnl:.2f} <= Limit: -${grid_settings.hedging}. Deploying {trade_type} Volume: {grid_state.total_cumulative_lots}")
            
            # --- SAVE HEDGE DETAILS TO STATE FOR THE UI ---
            grid_state.hedge_data = HedgeData(
                entry_price=current_market_price,
                sl=hard_sl,
                tp=hard_tp,
                lots=grid_state.total_cumulative_lots
            )
            
            self.pending_ea_actions.append({
                "action": "HEDGE",
                "side": side,
                "type": trade_type,
                "volume": grid_state.total_cumulative_lots,
                "tp": hard_tp,
                "sl": hard_sl,
                "comment": f"hedge_{grid_state.session_id}"
            })

    # --- CYCLE INITIATION ---
    def _evaluate_cycle_start(self, side: str):
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        
        if not grid_settings.is_on or grid_state.session_id is not None or grid_state.emergency_state:
            return
            
        should_start = False
        if grid_settings.start_limit is None:
            should_start = True
        else:
            limit = grid_settings.start_limit
            if side == "buy" and self._is_crossed(limit, "drop_below"):
                should_start = True
            elif side == "sell" and self._is_crossed(limit, "rise_above"):
                should_start = True

        if should_start:
            grid_state.session_id = self.generate_session_id(side)
            grid_state.reference_point = self.state.current_ask if side == "buy" else self.state.current_bid
            logger.info(f"[{side.upper()}] Cycle Initiated! Session: {grid_state.session_id} | Anchor: {grid_state.reference_point}")
            self.recalculate_grid_math(side)

    # --- ROW EXECUTION LOGIC ---
    def _evaluate_grid_rows(self, side: str):
        grid_settings = self.state.buy_settings if side == "buy" else self.state.sell_settings
        grid_state = self.state.buy_state if side == "buy" else self.state.sell_state
        
        if not grid_settings.is_on or not grid_state.session_id or grid_state.is_hedged: return
            
        for i, row in enumerate(grid_settings.rows):
            if grid_settings.row_stop_limit is not None and i >= grid_settings.row_stop_limit: 
                break
            if row.executed or row.price is None: 
                continue
                
            is_triggered = self._is_crossed(row.price, "drop_below" if side == "buy" else "rise_above")
                
            if is_triggered:
                row.executed = True
                # Clear start_limit so future cycles (cyclic or manual restart) begin immediately
                if grid_settings.start_limit is not None:
                    grid_settings.start_limit = None
                    logger.info(f"[{side.upper()}] start_limit cleared after first row execution — future sessions will anchor immediately.")
                logger.info(f"[{side.upper()}] Row {row.index} Crossover! Target: {row.price}. Queuing EA Action.")
                self.pending_ea_actions.append({
                    "action": "BUY" if side == "buy" else "SELL",
                    "volume": row.lots,
                    "comment": f"{grid_state.session_id}_idx{row.index}"
                })

    # --- HELPERS ---
    def _clear_grid_cycle(self, side: str, hard_reset: bool = False):
        logger.debug(f"[{side.upper()}] Clearing grid cycle data (hard_reset={hard_reset})")
        settings_ref = self.state.buy_settings if side == "buy" else self.state.sell_settings
        state_ref = self.state.buy_state if side == "buy" else self.state.sell_state
        
        if hard_reset:
            settings_ref.is_on = False
        
        # clear the running states
        state_ref.session_id = None
        state_ref.reference_point = None
        state_ref.is_hedged = False
        state_ref.hedge_data = None
        state_ref.emergency_state = False
        state_ref.total_cumulative_lots = 0.0
        state_ref.total_cumulative_pnl = 0.0
        
        for row in settings_ref.rows:
            row.alert_executed = False
            row.executed = False
            row.price = None
            row.pnl = 0.0
            row.cumulative_pnl = 0.0

    # --- CROSSOVER & CYCLE START ---
    def _is_crossed(self, target_price: float, direction: str) -> bool:
        """Instant crossover check based purely on the latest live tick."""
        if direction == "drop_below":
            return self.state.current_ask <= target_price
        elif direction == "rise_above":
            return self.state.current_bid >= target_price
        return False

    def get_next_ea_action(self):
        """Pops a single action to send to MT5, preventing Context Busy errors."""
        if self.pending_ea_actions:
            return self.pending_ea_actions.pop(0)
        return {"action": "WAIT"}

    def get_and_clear_pending_actions(self):
        """Called by the REST Router when responding to EA pings."""
        actions = list(self.pending_ea_actions)
        self.pending_ea_actions.clear()
        return actions

# Global Engine Instance
engine = DcaEngine()