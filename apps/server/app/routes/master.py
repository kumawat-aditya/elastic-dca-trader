"""
POST /api/master-tick — Master EA price feed endpoint.

Blueprint references:
  - Section 3.1  : Master EA sends {ask, bid, contract_size} with X-Admin-Key
  - Section 7.7  : Complete tick processing flow
  - Section 11.1 : Endpoint specification
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.dependencies import verify_admin_key
from app.engine import process_tick
from app.models import MasterTickRequest
from app.state import market, persist_grid, tier_states, update_market

logger = logging.getLogger("elastic_dca.api.master")

router = APIRouter()


@router.post("/api/master-tick")
async def master_tick(
    body: MasterTickRequest,
    _key: str = Depends(verify_admin_key),
):
    """
    Receive a price tick from the Master EA, update market state,
    then run the virtual execution engine for ALL tiers.

    Section 11.1:
      - Auth: X-Admin-Key header required
      - Request: { ask, bid, contract_size }
      - Response: { status: "ok" }
      - Error: 401 / 422
    """
    # Update global market state (Section 9.6)
    await update_market(body.ask, body.bid, body.contract_size)

    # Process every tier (Section 7.7: FOR EACH tier)
    for tier_id, ts in tier_states.items():
        state_changed = await process_tick(ts, market)
        if state_changed:
            # Persist changed grids to DB (Phase 1: "State persistence to DB on every change")
            for grid_id in ["B1", "B2", "S1", "S2"]:
                await persist_grid(tier_id, grid_id)

    return {"status": "ok"}
