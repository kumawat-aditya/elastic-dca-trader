"""
Client API endpoints — Account management, MT5 ID update, Dashboard.

Blueprint references:
  - Section 11.5 : Client Dashboard Endpoints
  - Section 10.3 : MetaID Management
  - Section 13   : Client Dashboard specification
  - All require JWT with role == 'client'
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_subscription_by_user, get_user_by_id, get_user_snapshot, update_user
from app.dependencies import verify_jwt_client
from app.models import GRID_IDS, UpdateAccountRequest, UpdateMetaIdRequest
from app.state import get_tier_state, market
from app.sync import parse_comment

logger = logging.getLogger("elastic_dca.api.client")

router = APIRouter(prefix="/api/client", dependencies=[Depends(verify_jwt_client)])


# ── GET /api/client/account ──────────────────────────────────────────────────

@router.get("/account")
async def get_account(payload: dict = Depends(verify_jwt_client)):
    """
    Section 11.5 — GET /api/client/account
    Returns user profile + subscription info.
    """
    user_id = int(payload["sub"])
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get subscription
    sub = await get_subscription_by_user(user_id)
    subscription_data = None
    if sub:
        subscription_data = {
            "status": sub.status,
            "plan_name": sub.plan_name,
            "start_date": sub.start_date,
            "end_date": sub.end_date,
        }

    return {
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "mt5_id": user.mt5_id,
        "subscription": subscription_data,
    }


# ── PATCH /api/client/account ────────────────────────────────────────────────

@router.patch("/account")
async def update_account(body: UpdateAccountRequest, payload: dict = Depends(verify_jwt_client)):
    """
    Section 11.5 — PATCH /api/client/account
    Update account fields: name, phone, mt5_id.
    """
    user_id = int(payload["sub"])

    # MT5 ID validation (Section 10.3: must be numeric)
    if body.mt5_id is not None:
        if body.mt5_id and not body.mt5_id.isdigit():
            raise HTTPException(status_code=400, detail="MT5 ID must be numeric")

    try:
        user = await update_user(
            user_id,
            name=body.name,
            phone=body.phone,
            mt5_id=body.mt5_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("User id=%d updated account", user_id)
    return {
        "email": user.email,
        "name": user.name,
        "phone": user.phone,
        "mt5_id": user.mt5_id,
    }


# ── PATCH /api/client/meta-id ───────────────────────────────────────────────

@router.patch("/meta-id")
async def update_meta_id(body: UpdateMetaIdRequest, payload: dict = Depends(verify_jwt_client)):
    """
    Section 10.3 / 11.5 — PATCH /api/client/meta-id
    Update MT5 account number.
    - Must be numeric
    - Must not be already claimed by another user
    - One MT5 ID per user. Updated anytime (old ID is released).
    """
    user_id = int(payload["sub"])

    # Validation: must be numeric (Section 10.3)
    if not body.mt5_id.isdigit():
        raise HTTPException(status_code=400, detail="MT5 ID must be numeric")

    try:
        user = await update_user(user_id, mt5_id=body.mt5_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("User id=%d updated MT5 ID to %s", user_id, body.mt5_id)
    return {"mt5_id": user.mt5_id}


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — Client Dashboard (Section 11.5, 13)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_dashboard(payload: dict = Depends(verify_jwt_client)):
    """
    GET /api/client/dashboard — Section 11.5, 13

    Returns the client's grid data and P&L:
      - Tier info
      - Account info (balance, mt5_id)
      - All 4 grids: config summary + per-row data with master entry_price
        matched against client's actual positions by comment string
      - Per-grid P&L, combined total P&L
      - Market data
    """
    user_id = int(payload["sub"])
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Must have an assigned tier
    if not user.assigned_tier_id:
        return {
            "tier": None,
            "account": {"balance": None, "mt5_id": user.mt5_id},
            "grids": {},
            "combined_total_profit": 0.0,
            "market": {"mid": market.mid, "direction": market.direction},
        }

    ts = get_tier_state(user.assigned_tier_id)
    if not ts:
        return {
            "tier": None,
            "account": {"balance": None, "mt5_id": user.mt5_id},
            "grids": {},
            "combined_total_profit": 0.0,
            "market": {"mid": market.mid, "direction": market.direction},
        }

    # Load client's latest snapshot (positions from last ping)
    snapshot = await get_user_snapshot(user_id)
    client_positions = snapshot.positions if snapshot else []
    client_balance = snapshot.balance if snapshot else None

    # Build a lookup: comment → position dict
    pos_by_comment: dict[str, dict] = {}
    for p in client_positions:
        comment = p.get("comment", "") if isinstance(p, dict) else ""
        if comment:
            pos_by_comment[comment] = p

    grids_data = {}
    combined_total = 0.0

    for grid_id in GRID_IDS:
        config = ts.configs.get(grid_id)
        runtime = ts.runtimes.get(grid_id)
        if not config or not runtime:
            continue

        current_session = runtime.session_id
        rows_data = []
        grid_profit = 0.0
        cumulative = 0.0

        for row in config.rows:
            row_entry: dict = {
                "index": row.index,
                "dollar": row.dollar,
                "lots": row.lots,
                "executed": row.executed,
                "master_entry_price": row.entry_price if row.executed else None,
                "my_ticket": None,
                "my_entry_price": None,
                "my_profit": None,
                "cumulative_profit": None,
            }

            if row.executed and current_session:
                # Match client position by comment: "{session_id}_{row_index}"
                expected_comment = f"{current_session}_{row.index}"
                client_pos = pos_by_comment.get(expected_comment)
                if client_pos:
                    profit = client_pos.get("profit", 0.0) or 0.0
                    row_entry["my_ticket"] = client_pos.get("ticket")
                    row_entry["my_entry_price"] = client_pos.get("price")
                    row_entry["my_profit"] = profit
                    cumulative += profit
                    row_entry["cumulative_profit"] = round(cumulative, 2)
                    grid_profit += profit
                # If not found: leave as null (Section 13.2 / 14.10: no error)

            rows_data.append(row_entry)

        grid_profit = round(grid_profit, 2)
        combined_total += grid_profit

        grids_data[grid_id] = {
            "config": {
                "on": config.on,
                "session_id": current_session,
                "tp_type": config.tp_type,
                "tp_value": config.tp_value,
            },
            "rows": rows_data,
            "grid_total_profit": grid_profit,
        }

    combined_total = round(combined_total, 2)

    return {
        "tier": {"name": ts.tier.name},
        "account": {"balance": client_balance, "mt5_id": user.mt5_id},
        "grids": grids_data,
        "combined_total_profit": combined_total,
        "market": {"mid": market.mid, "direction": market.direction},
    }
