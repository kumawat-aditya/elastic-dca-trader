"""
In-memory state manager.

Holds the global tier states and market state in memory.
Loads from DB on startup, persists to DB on every change.

Blueprint reference:
  - Phase 1: "In-memory tier state loaded from PostgreSQL on startup"
  - Phase 1: "State persistence to DB on every change"
"""

from __future__ import annotations

import logging
from typing import Optional

from app.database import load_all_tier_states, load_market_state, save_grid_state, save_market_state
from app.models import GRID_IDS, GridConfig, GridRuntime, MarketState, TierState

logger = logging.getLogger("elastic_dca.state")

# ── Global In-Memory State ───────────────────────────────────────────────────
tier_states: dict[int, TierState] = {}   # keyed by tier.id
market: MarketState = MarketState()


async def load_state_from_db() -> None:
    """Load all tier states and market state from PostgreSQL into memory.

    IMPORTANT: We mutate the existing `market` object rather than reassigning
    the module-level variable so that other modules which imported `market`
    via ``from app.state import market`` keep a valid reference.
    """
    states = await load_all_tier_states()
    for ts in states:
        tier_states[ts.tier.id] = ts
    logger.info("Loaded %d tier(s) into memory.", len(tier_states))

    loaded = await load_market_state()
    # Copy fields into the existing object (preserves all foreign references)
    market.symbol = loaded.symbol
    market.ask = loaded.ask
    market.bid = loaded.bid
    market.mid = loaded.mid
    market.contract_size = loaded.contract_size
    market.direction = loaded.direction
    market.last_update = loaded.last_update
    logger.info(
        "Market state loaded: ask=%.5f bid=%.5f contract_size=%.2f",
        market.ask, market.bid, market.contract_size,
    )


def get_tier_state(tier_id: int) -> Optional[TierState]:
    return tier_states.get(tier_id)


def add_tier_state(ts: TierState) -> None:
    tier_states[ts.tier.id] = ts


def remove_tier_state(tier_id: int) -> None:
    tier_states.pop(tier_id, None)


async def persist_grid(tier_id: int, grid_id: str) -> None:
    """Save a single grid's config + runtime to DB."""
    ts = tier_states.get(tier_id)
    if not ts:
        return
    config = ts.configs.get(grid_id)
    runtime = ts.runtimes.get(grid_id)
    if config and runtime:
        await save_grid_state(tier_id, grid_id, config, runtime)


async def persist_all_grids(tier_id: int) -> None:
    """Save all 4 grids for a tier."""
    for grid_id in GRID_IDS:
        await persist_grid(tier_id, grid_id)


async def update_market(ask: float, bid: float, contract_size: float) -> None:
    """Update in-memory market state and persist to DB."""
    prev_mid = market.mid
    market.ask = ask
    market.bid = bid
    market.mid = round((ask + bid) / 2, 5)
    market.contract_size = contract_size

    new_mid = market.mid
    if new_mid > prev_mid:
        market.direction = "up"
    elif new_mid < prev_mid:
        market.direction = "down"
    else:
        market.direction = "neutral"

    from datetime import datetime, timezone
    market.last_update = datetime.now(timezone.utc).isoformat()

    await save_market_state(market)
