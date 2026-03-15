"""
Admin API endpoints for tier, grid, and user management.

Blueprint references:
  - Section 11.4 : All admin endpoints (JWT with role='admin')
  - Section 6.3  : Session activation (turning ON)
  - Section 6.4  : Session close (turning OFF)
  - Section 14.7 : Admin edits while session is active
  - Section 14.11: Overlapping tier ranges → 400 error
  - Section 14.12: Zero rows configured

Phase 2: Transitioned from X-Admin-Key to JWT auth.
         Added: GET /api/admin/users, PUT /api/admin/users/{user_id},
                PUT /api/admin/users/{user_id}/subscription
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import (
    create_tier,
    delete_tier,
    get_all_tiers,
    get_all_users,
    get_clients_by_tier,
    get_subscription_by_user,
    get_tier,
    get_user_by_id,
    get_user_snapshot,
    is_subscription_active,
    save_grid_state,
    update_tier,
    update_user,
    upsert_subscription,
)
from app.dependencies import verify_jwt_admin
from app.engine import activate_grid, calculate_virtual_pnl, close_session
from app.models import (
    GRID_IDS,
    CreateTierRequest,
    GridConfig,
    GridControlRequest,
    GridRow,
    GridRuntime,
    ManageSubscriptionRequest,
    TierState,
    UpdateGridConfigRequest,
    UpdateTierRequest,
    UpdateUserStatusRequest,
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
from app.sync import parse_comment

logger = logging.getLogger("elastic_dca.api.admin")

# Phase 2: Admin endpoints now require JWT with role='admin' (Section 10.1)
router = APIRouter(prefix="/api/admin", dependencies=[Depends(verify_jwt_admin)])


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


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — User Management (Section 11.4)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/users")
async def list_users():
    """
    GET /api/admin/users — List all users with subscription status.
    Section 11.4: Admin can manage users via API.
    """
    users = await get_all_users()
    result = []
    for u in users:
        sub = await get_subscription_by_user(u.id)
        sub_active = await is_subscription_active(u.id)
        result.append({
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "phone": u.phone,
            "mt5_id": u.mt5_id,
            "assigned_tier_id": u.assigned_tier_id,
            "role": u.role,
            "status": u.status,
            "email_verified": u.email_verified,
            "subscription": {
                "plan_name": sub.plan_name if sub else None,
                "status": sub.status if sub else None,
                "end_date": sub.end_date if sub else None,
                "is_active": sub_active,
            },
            "created_at": u.created_at,
        })
    return {"users": result}


@router.put("/users/{user_id}")
async def update_user_status(user_id: int, body: UpdateUserStatusRequest):
    """
    PUT /api/admin/users/{user_id} — Update user status (activate, ban, etc.).
    Section 11.4: Admin manages user lifecycle.
    """
    if body.status not in ("active", "banned", "pending"):
        raise HTTPException(status_code=400, detail="Status must be 'active', 'banned', or 'pending'")

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updated = await update_user(user_id, status=body.status)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("Admin updated user id=%d status to '%s'", user_id, body.status)
    return {
        "user": {
            "id": updated.id,
            "email": updated.email,
            "name": updated.name,
            "status": updated.status,
            "email_verified": updated.email_verified,
        }
    }


@router.put("/users/{user_id}/subscription")
async def manage_subscription(user_id: int, body: ManageSubscriptionRequest):
    """
    PUT /api/admin/users/{user_id}/subscription — Manually manage subscription.
    Phase 2: No PayPal yet. Admin manually creates/extends subscriptions.
    Section 11.4 + Phase 2 deliverables.
    """
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from datetime import datetime, timezone
    now_str = datetime.utcnow().isoformat()

    sub = await upsert_subscription(
        user_id=user_id,
        plan_name=body.plan_name,
        start_date=now_str,
        end_date=body.end_date,
    )

    logger.info("Admin set subscription for user id=%d: plan=%s, end=%s", user_id, body.plan_name, body.end_date)
    return {
        "subscription": {
            "id": sub.id,
            "user_id": sub.user_id,
            "plan_name": sub.plan_name,
            "status": sub.status,
            "start_date": sub.start_date,
            "end_date": sub.end_date,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Admin Tier Client Endpoints (Section 11.4)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/tiers/{tier_id}/clients")
async def list_tier_clients(tier_id: int):
    """
    GET /api/admin/tiers/{tier_id}/clients
    List all clients currently assigned to this tier.
    Section 11.4: connected = last_seen within 10 seconds.
    """
    ts = get_tier_state(tier_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Tier not found")

    clients = await get_clients_by_tier(tier_id)
    return {"clients": clients}


@router.get("/tiers/{tier_id}/clients/{user_id}/positions")
async def get_client_positions(tier_id: int, user_id: int):
    """
    GET /api/admin/tiers/{tier_id}/clients/{user_id}/positions
    Get a specific client's current positions mapped to grid rows.

    Section 11.4: Row matching — for each executed master row, find client
    position where comment == f"{session_id}_{row.index}".
    If not found: display null values (no error).
    """
    ts = get_tier_state(tier_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Tier not found")

    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    snapshot = await get_user_snapshot(user_id)
    client_positions = snapshot.positions if snapshot else []
    client_balance = float(snapshot.balance) if snapshot and snapshot.balance else None

    # Build comment → position lookup
    pos_by_comment: dict[str, dict] = {}
    for p in client_positions:
        comment = p.get("comment", "") if isinstance(p, dict) else ""
        if comment:
            pos_by_comment[comment] = p

    grids_data = {}
    combined_profit = 0.0

    for grid_id in GRID_IDS:
        config = ts.configs.get(grid_id)
        runtime = ts.runtimes.get(grid_id)
        if not config or not runtime:
            continue

        current_session = runtime.session_id
        rows_data = []
        total_client_profit = 0.0
        total_virtual_profit = 0.0

        for row in config.rows:
            if not row.executed:
                continue

            row_entry: dict = {
                "index": row.index,
                "master_entry_price": row.entry_price,
                "master_executed": True,
                "client_ticket": None,
                "client_entry_price": None,
                "client_lots": None,
                "client_profit": None,
            }

            if current_session:
                expected_comment = f"{current_session}_{row.index}"
                client_pos = pos_by_comment.get(expected_comment)
                if client_pos:
                    profit = client_pos.get("profit", 0.0) or 0.0
                    row_entry["client_ticket"] = client_pos.get("ticket")
                    row_entry["client_entry_price"] = client_pos.get("price")
                    row_entry["client_lots"] = client_pos.get("volume")
                    row_entry["client_profit"] = profit
                    total_client_profit += profit

            rows_data.append(row_entry)

        # Calculate virtual P&L from engine (using market data)
        virtual_pnl = calculate_virtual_pnl(config, market.bid, market.ask, market.contract_size)
        total_virtual_profit = round(virtual_pnl, 2)
        total_client_profit = round(total_client_profit, 2)

        grids_data[grid_id] = {
            "session_id": current_session,
            "rows": rows_data,
            "total_client_profit": total_client_profit,
            "total_virtual_profit": total_virtual_profit,
        }

        combined_profit += total_client_profit

    combined_profit = round(combined_profit, 2)

    return {
        "user": {
            "name": user.name,
            "mt5_id": user.mt5_id,
            "balance": client_balance,
        },
        "grids": grids_data,
        "combined_profit": combined_profit,
    }
