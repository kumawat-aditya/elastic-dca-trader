"""
Admin API endpoints for tier and grid management.

Blueprint references:
  - Section 11.4 : All admin endpoints
  - Section 6.3  : Session activation (turning ON)
  - Section 6.4  : Session close (turning OFF)
  - Section 14.7 : Admin edits while session is active
  - Section 14.11: Overlapping tier ranges → 400 error
  - Section 14.12: Zero rows configured
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import create_tier, delete_tier, get_all_tiers, get_tier, save_grid_state, update_tier
from app.dependencies import verify_admin_key
from app.engine import activate_grid, close_session
from app.models import (
    GRID_IDS,
    CreateTierRequest,
    GridConfig,
    GridControlRequest,
    GridRow,
    GridRuntime,
    TierState,
    UpdateGridConfigRequest,
    UpdateTierRequest,
)
from app.state import (
    add_tier_state,
    get_tier_state,
    market,
    persist_all_grids,
    persist_grid,
    remove_tier_state,
    tier_states,
)

logger = logging.getLogger("elastic_dca.api.admin")

router = APIRouter(prefix="/api/admin", dependencies=[Depends(verify_admin_key)])


# ── Tier CRUD ────────────────────────────────────────────────────────────────

@router.get("/tiers")
async def list_tiers():
    """GET /api/admin/tiers — List all tiers."""
    tiers = []
    for ts in tier_states.values():
        tiers.append({
            "id": ts.tier.id,
            "name": ts.tier.name,
            "min_balance": ts.tier.min_balance,
            "max_balance": ts.tier.max_balance,
            "is_active": ts.tier.is_active,
        })
    return {"tiers": tiers}


@router.post("/tiers", status_code=201)
async def create_new_tier(body: CreateTierRequest):
    """
    POST /api/admin/tiers — Create a new tier.
    Auto-creates 4 empty grid records (Section 11.4).
    """
    try:
        tier = await create_tier(body.name, body.min_balance, body.max_balance)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Add to in-memory state
    configs = {gid: GridConfig(grid_id=gid) for gid in GRID_IDS}
    runtimes = {gid: GridRuntime(grid_id=gid) for gid in GRID_IDS}
    ts = TierState(tier=tier, configs=configs, runtimes=runtimes)
    add_tier_state(ts)

    logger.info("Created tier '%s' (id=%d) [%.0f – %.0f]", tier.name, tier.id, tier.min_balance, tier.max_balance)
    return {
        "tier": {
            "id": tier.id,
            "name": tier.name,
            "min_balance": tier.min_balance,
            "max_balance": tier.max_balance,
            "is_active": tier.is_active,
        },
        "grids_created": list(GRID_IDS),
    }


@router.put("/tiers/{tier_id}")
async def update_existing_tier(tier_id: int, body: UpdateTierRequest):
    """PUT /api/admin/tiers/{tier_id} — Update tier metadata."""
    try:
        tier = await update_tier(
            tier_id,
            name=body.name,
            min_balance=body.min_balance,
            max_balance=body.max_balance,
            is_active=body.is_active,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    # Update in-memory
    ts = get_tier_state(tier_id)
    if ts:
        ts.tier = tier

    return {
        "tier": {
            "id": tier.id,
            "name": tier.name,
            "min_balance": tier.min_balance,
            "max_balance": tier.max_balance,
            "is_active": tier.is_active,
        }
    }


@router.delete("/tiers/{tier_id}")
async def delete_existing_tier(tier_id: int):
    """DELETE /api/admin/tiers/{tier_id} — Only allowed if no active sessions."""
    try:
        deleted = await delete_tier(tier_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not deleted:
        raise HTTPException(status_code=404, detail="Tier not found")

    remove_tier_state(tier_id)
    logger.info("Deleted tier id=%d", tier_id)
    return {"status": "deleted"}


# ── Grid Management ──────────────────────────────────────────────────────────

@router.get("/tiers/{tier_id}/grids")
async def get_grids(tier_id: int):
    """
    GET /api/admin/tiers/{tier_id}/grids
    Returns all 4 grid configs + runtime states + market state.
    This is the main testing endpoint for Phase 1.
    """
    ts = get_tier_state(tier_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Tier not found")

    grids = []
    for grid_id in GRID_IDS:
        cfg = ts.configs.get(grid_id)
        rt = ts.runtimes.get(grid_id)
        if cfg and rt:
            grids.append({
                "grid_id": grid_id,
                "config": cfg.model_dump(),
                "runtime": rt.model_dump(),
            })

    return {
        "tier": {"id": ts.tier.id, "name": ts.tier.name},
        "grids": grids,
        "market": {
            "ask": market.ask,
            "bid": market.bid,
            "mid": market.mid,
            "contract_size": market.contract_size,
            "direction": market.direction,
        },
    }


@router.put("/tiers/{tier_id}/grids/{grid_id}/config")
async def update_grid_config(tier_id: int, grid_id: str, body: UpdateGridConfigRequest):
    """
    PUT /api/admin/tiers/{tier_id}/grids/{grid_id}/config
    Update a grid's configuration (rows, TP, limits).

    Section 14.7 merge logic:
      - Executed rows: only `alert` can change. `dollar` and `lots` locked.
      - Non-executed rows: freely editable.
      - New rows can be appended.
    """
    ts = get_tier_state(tier_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Tier not found")
    if grid_id not in GRID_IDS:
        raise HTTPException(status_code=400, detail=f"Invalid grid_id. Must be one of {GRID_IDS}")

    config = ts.configs[grid_id]

    # Update scalar fields if provided
    if body.start_limit is not None:
        config.start_limit = body.start_limit
    if body.end_limit is not None:
        config.end_limit = body.end_limit
    if body.tp_type is not None:
        if body.tp_type not in ("equity_pct", "balance_pct", "fixed_money"):
            raise HTTPException(status_code=400, detail="tp_type must be equity_pct, balance_pct, or fixed_money")
        config.tp_type = body.tp_type
    if body.tp_value is not None:
        config.tp_value = body.tp_value

    # Update rows with merge logic (Section 14.7)
    if body.rows is not None:
        # Validate max 100 rows (Section 5.4)
        if len(body.rows) > 100:
            raise HTTPException(status_code=400, detail="Maximum 100 rows per grid")

        # Validate sequential indexing (indices must be 0..N-1)
        submitted_indices = sorted(r.index for r in body.rows)
        expected_indices = list(range(len(body.rows)))
        if submitted_indices != expected_indices:
            raise HTTPException(
                status_code=400,
                detail=f"Row indices must be sequential starting from 0. Got: {submitted_indices}",
            )

        # Build a map of currently executed rows
        executed_map: dict[int, GridRow] = {}
        for row in config.rows:
            if row.executed:
                executed_map[row.index] = row

        new_rows: list[GridRow] = []
        for row_input in body.rows:
            if row_input.index in executed_map:
                # Executed row: keep dollar/lots, only allow alert change
                existing = executed_map[row_input.index]
                existing.alert = row_input.alert
                new_rows.append(existing)
            else:
                # New or non-executed row: apply admin's values
                new_rows.append(GridRow(
                    index=row_input.index,
                    dollar=row_input.dollar,
                    lots=row_input.lots,
                    alert=row_input.alert,
                ))

        # Re-inject any executed rows omitted from admin's request (Section 14.7:
        # "Executed rows persist until session ends")
        submitted_idx_set = {r.index for r in new_rows}
        for idx, executed_row in executed_map.items():
            if idx not in submitted_idx_set:
                new_rows.append(executed_row)
        new_rows.sort(key=lambda r: r.index)

        # Ensure row 0 always has dollar=0 (Section 5.5)
        if new_rows and new_rows[0].index == 0:
            new_rows[0].dollar = 0.0

        config.rows = new_rows

    # Persist to DB
    await persist_grid(tier_id, grid_id)

    return {"status": "updated", "grid_id": grid_id, "config": config.model_dump()}


@router.post("/tiers/{tier_id}/grids/{grid_id}/control")
async def control_grid(tier_id: int, grid_id: str, body: GridControlRequest):
    """
    POST /api/admin/tiers/{tier_id}/grids/{grid_id}/control
    Toggle grid ON/OFF or cyclic.

    Turning ON → Section 6.3 (session activation)
    Turning OFF → Section 6.4 (session close, no CLOSING state)
    """
    ts = get_tier_state(tier_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Tier not found")
    if grid_id not in GRID_IDS:
        raise HTTPException(status_code=400, detail=f"Invalid grid_id. Must be one of {GRID_IDS}")

    config = ts.configs[grid_id]
    runtime = ts.runtimes[grid_id]

    # Handle cyclic toggle
    if body.cyclic is not None:
        config.cyclic = body.cyclic
        logger.info("Grid %s (tier %d) cyclic set to %s", grid_id, tier_id, config.cyclic)

    # Handle ON/OFF toggle
    if body.on is not None:
        if body.on and not config.on:
            # Turning ON (Section 6.3)
            config.on = True
            activate_grid(config, runtime, market.ask, market.bid)
            logger.info("Grid %s (tier %d) turned ON. session=%s", grid_id, tier_id, runtime.session_id)

        elif not body.on and config.on:
            # Turning OFF (Section 6.4)
            # No CLOSING state — immediate clear
            config.on = False
            old_session = runtime.session_id
            runtime.session_id = ""
            runtime.is_active = False
            runtime.waiting_limit = False
            runtime.start_ref = 0.0
            logger.info("Grid %s (tier %d) turned OFF. Old session=%s cleared.", grid_id, tier_id, old_session)

    # Persist to DB
    await persist_grid(tier_id, grid_id)

    return {
        "status": "ok",
        "grid_id": grid_id,
        "on": config.on,
        "cyclic": config.cyclic,
        "session_id": runtime.session_id,
    }


# ── Market State ─────────────────────────────────────────────────────────────

@router.get("/market")
async def get_market():
    """GET /api/admin/market — Current market state."""
    return {
        "ask": market.ask,
        "bid": market.bid,
        "mid": market.mid,
        "contract_size": market.contract_size,
        "direction": market.direction,
        "last_update": market.last_update,
    }
