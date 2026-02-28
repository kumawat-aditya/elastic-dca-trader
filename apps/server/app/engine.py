"""
Virtual Execution Engine — the core grid processing logic.

Implements the complete tick processing flow from Blueprint Section 7.

Blueprint references:
  - Section 7.1  : Row execution logic (BUY: ask <= target, SELL: bid >= target)
  - Section 7.2  : Sequential execution rule (one row per tick)
  - Section 7.3  : Start limit (anchor) wait behavior
  - Section 7.4  : End limit (safety boundary) behavior
  - Section 7.5  : Virtual P&L calculation using contract_size from Master EA
  - Section 7.6  : Take Profit (snap-back) logic
  - Section 7.7  : Complete tick processing flow (5 phases)
  - Section 5.5  : First row (row 0) immediate execution
  - Section 6.3  : Session activation
  - Section 6.4  : Session close (TP hit → cyclic restart or OFF)
  - Section 6.5  : Cyclic restart flow
  - Section 14.13: Concurrent master ticks → asyncio.Lock per tier
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.models import GridConfig, GridRow, GridRuntime, MarketState, TierState

logger = logging.getLogger("elastic_dca.engine")

# Per-tier locks to prevent concurrent tick processing (Section 14.13)
_tier_locks: dict[int, asyncio.Lock] = {}


def _get_tier_lock(tier_id: int) -> asyncio.Lock:
    if tier_id not in _tier_locks:
        _tier_locks[tier_id] = asyncio.Lock()
    return _tier_locks[tier_id]


# ── Session ID Generation (Section 6.1) ─────────────────────────────────────

def generate_session_id(grid_id: str) -> str:
    """Format: {GRID_ID}_{8_HEX_CHARS} e.g. B1_a1b2c3d4"""
    return f"{grid_id}_{uuid.uuid4().hex[:8]}"


# ── Virtual P&L Calculation (Section 7.5) ────────────────────────────────────

def calculate_virtual_pnl(
    config: GridConfig,
    current_bid: float,
    current_ask: float,
    contract_size: float,
) -> float:
    """
    Calculate the theoretical P&L of a grid's executed rows.
    contract_size comes from master tick payload (e.g. 100.0 for XAUUSD).
    """
    total_pnl = 0.0
    for row in config.rows:
        if not row.executed:
            continue
        if config.grid_id.startswith("B"):
            # BUY position: profit when bid > entry_price
            pnl = (current_bid - row.entry_price) * row.lots * contract_size
        else:
            # SELL position: profit when entry_price > ask
            pnl = (row.entry_price - current_ask) * row.lots * contract_size
        total_pnl += pnl
    return round(total_pnl, 2)


# ── Take Profit Check (Section 7.6) ─────────────────────────────────────────

def check_tp(
    config: GridConfig,
    tier_ref_balance: float,
    virtual_pnl: float,
) -> bool:
    """Returns True if TP target is reached."""
    if config.tp_value <= 0:
        return False  # TP disabled

    if config.tp_type == "fixed_money":
        target = config.tp_value
    elif config.tp_type in ("equity_pct", "balance_pct"):
        target = tier_ref_balance * (config.tp_value / 100.0)
    else:
        return False

    return virtual_pnl >= target


# ── Session Activation (Section 6.3) ────────────────────────────────────────

def activate_grid(
    config: GridConfig,
    runtime: GridRuntime,
    current_ask: float,
    current_bid: float,
) -> bool:
    """
    Activate a grid session. Returns True if state changed.
    Called when admin turns grid ON or on cyclic restart.
    """
    # 1. Generate new session ID
    runtime.session_id = generate_session_id(config.grid_id)

    # 2. Reset execution state on all rows
    for row in config.rows:
        row.executed = False
        row.entry_price = 0.0
        row.executed_at = ""

    # 3. Check start_limit
    if config.start_limit > 0:
        runtime.waiting_limit = True
        runtime.start_ref = config.start_limit
        runtime.is_active = True
        logger.info(
            "[ACTIVATE] Grid %s → WAITING_LIMIT (start_limit=%.2f) session=%s",
            config.grid_id, config.start_limit, runtime.session_id,
        )
    else:
        # start_limit == 0 → use current market price, execute Row 0 immediately
        runtime.waiting_limit = False
        runtime.is_active = True
        if config.grid_id.startswith("B"):
            runtime.start_ref = current_ask
        else:
            runtime.start_ref = current_bid

        # Execute Row 0 immediately (Section 5.5)
        if config.rows:
            _execute_row(config, config.rows[0], runtime)
            logger.info(
                "[ACTIVATE] Grid %s → ACTIVE (start_ref=%.5f) Row 0 executed. session=%s",
                config.grid_id, runtime.start_ref, runtime.session_id,
            )
        else:
            logger.info(
                "[ACTIVATE] Grid %s → ACTIVE (start_ref=%.5f) No rows configured. session=%s",
                config.grid_id, runtime.start_ref, runtime.session_id,
            )

    return True


# ── Session Close / TP Hit (Section 6.4) ────────────────────────────────────

def close_session(
    config: GridConfig,
    runtime: GridRuntime,
    current_ask: float,
    current_bid: float,
    reason: str = "tp_hit",
) -> None:
    """
    Handle session close. No intermediate CLOSING state.
    If cyclic → immediate new session. If not → set off.
    """
    old_session = runtime.session_id

    if config.cyclic:
        # Section 6.5: Cyclic restart — immediately generate new session
        logger.info(
            "[SNAP-BACK] Grid %s session %s TP hit → cyclic restart",
            config.grid_id, old_session,
        )
        activate_grid(config, runtime, current_ask, current_bid)
    else:
        # Section 6.4: Non-cyclic → turn off
        logger.info(
            "[SNAP-BACK] Grid %s session %s closed (reason=%s, cyclic=OFF)",
            config.grid_id, old_session, reason,
        )
        config.on = False
        runtime.session_id = ""
        runtime.is_active = False
        runtime.waiting_limit = False
        runtime.start_ref = 0.0


# ── Row Execution Helper ────────────────────────────────────────────────────

def _execute_row(config: GridConfig, row: GridRow, runtime: GridRuntime) -> None:
    """Mark a single row as executed."""
    row.executed = True
    # BUY → entry at ask; SELL → entry at bid
    # But at activation row 0 uses start_ref which is already set
    # For subsequent rows, entry_price is set in the expansion phase
    if not row.entry_price:
        row.entry_price = runtime.start_ref
    row.executed_at = datetime.now(timezone.utc).isoformat()
    runtime.last_order_ts = datetime.now(timezone.utc).timestamp()


# ── Complete Tick Processing (Section 7.7) ───────────────────────────────────

async def process_tick(
    tier_state: TierState,
    market: MarketState,
) -> bool:
    """
    Process a single master tick for one tier.
    Returns True if any state changed (needs DB persistence).

    Implements the 5-phase flow from Section 7.7:
      Phase 1: Limit Wait
      Phase 2: Virtual P&L Update
      Phase 3: TP Check
      Phase 4: End Limit Check
      Phase 5: Grid Expansion
    """
    lock = _get_tier_lock(tier_state.tier.id)
    async with lock:
        return _process_tick_sync(tier_state, market)


def _process_tick_sync(tier_state: TierState, market: MarketState) -> bool:
    """Synchronous inner logic for tick processing (runs under lock)."""
    changed = False
    ask = market.ask
    bid = market.bid
    contract_size = market.contract_size

    # Calculate tier reference balance = midpoint of tier range (Section 5.3.3)
    tier_ref_balance = (tier_state.tier.min_balance + tier_state.tier.max_balance) / 2.0

    for grid_id in ["B1", "B2", "S1", "S2"]:
        config = tier_state.configs.get(grid_id)
        runtime = tier_state.runtimes.get(grid_id)
        if not config or not runtime:
            continue

        # SKIP if grid is OFF
        if not config.on:
            continue

        is_buy = grid_id.startswith("B")

        # ── PHASE 1: LIMIT WAIT (Section 7.3) ──
        if runtime.waiting_limit:
            activated = False
            if is_buy and ask <= config.start_limit:
                activated = True
            elif not is_buy and bid >= config.start_limit:
                activated = True

            if activated:
                runtime.waiting_limit = False
                runtime.start_ref = ask if is_buy else bid
                # Execute Row 0 immediately
                if config.rows:
                    config.rows[0].entry_price = runtime.start_ref
                    _execute_row(config, config.rows[0], runtime)
                    logger.info(
                        "[LIMIT-HIT] Grid %s start_limit reached (%.5f). Row 0 executed at %.5f. session=%s",
                        grid_id, config.start_limit, runtime.start_ref, runtime.session_id,
                    )
                changed = True
                # Section 7.7: After activation, skip Phases 2-5 on this tick.
                # Only Row 0 fires on the activation tick (one-row-per-tick rule, Section 7.2).
                continue
            # Still waiting — skip all further phases
            continue

        # ── PHASE 2: VIRTUAL P&L UPDATE (Section 7.5) ──
        virtual_pnl = calculate_virtual_pnl(config, bid, ask, contract_size)

        # ── PHASE 3: TP CHECK (Section 7.6) ──
        if check_tp(config, tier_ref_balance, virtual_pnl):
            tp_target = _get_tp_target(config, tier_ref_balance)
            logger.info(
                "[SNAP-BACK] Grid %s TP hit. Virtual P&L: $%.2f >= Target: $%.2f",
                grid_id, virtual_pnl, tp_target,
            )
            close_session(config, runtime, ask, bid, reason="tp_hit")
            changed = True
            continue  # Move to next grid

        # ── PHASE 4: END LIMIT CHECK (Section 7.4) ──
        expansion_blocked = False
        if config.end_limit > 0:
            if is_buy and ask < config.end_limit:
                expansion_blocked = True
            elif not is_buy and bid > config.end_limit:
                expansion_blocked = True

        # ── PHASE 5: GRID EXPANSION (Section 7.1, 7.2) ──
        if not expansion_blocked:
            # Find next un-executed row (Section 7.2 — sequential rule)
            next_row = None
            for row in config.rows:
                if not row.executed:
                    next_row = row
                    break

            if next_row is not None:
                # Calculate target price (Section 7.1)
                cumulative_gap = sum(r.dollar for r in config.rows[:next_row.index + 1])

                if is_buy:
                    target_price = runtime.start_ref - cumulative_gap
                    if ask <= target_price:
                        next_row.entry_price = ask
                        _execute_row(config, next_row, runtime)
                        logger.info(
                            "[EXEC] Grid %s Row %d executed at %.5f (target=%.5f) session=%s",
                            grid_id, next_row.index, ask, target_price, runtime.session_id,
                        )
                        changed = True
                else:
                    target_price = runtime.start_ref + cumulative_gap
                    if bid >= target_price:
                        next_row.entry_price = bid
                        _execute_row(config, next_row, runtime)
                        logger.info(
                            "[EXEC] Grid %s Row %d executed at %.5f (target=%.5f) session=%s",
                            grid_id, next_row.index, bid, target_price, runtime.session_id,
                        )
                        changed = True

    return changed


def _get_tp_target(config: GridConfig, tier_ref_balance: float) -> float:
    """Calculate the TP target dollar amount."""
    if config.tp_type == "fixed_money":
        return config.tp_value
    elif config.tp_type in ("equity_pct", "balance_pct"):
        return tier_ref_balance * (config.tp_value / 100.0)
    return 0.0
