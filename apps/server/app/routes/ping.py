"""
POST /api/client-ping — Client EA sync endpoint.

Blueprint references:
  - Section 3.3  : Client EA payload / response format
  - Section 8.1  : Ping payload
  - Section 8.2  : Authentication flow
  - Section 8.3  : Tier assignment (balance-range routing with locking)
  - Section 8.4  : Sync scenarios (6 total)
  - Section 11.2 : Endpoint specification
  - Section 14.4 : Ignore unknown comments
  - Section 14.9 : Subscription expiry mid-trade
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.database import (
    get_user_by_mt5_id,
    is_subscription_active,
    update_user_tier,
    upsert_user_snapshot,
)
from app.models import ClientPingRequest
from app.state import get_tier_state, tier_states
from app.sync import (
    client_has_active_session_trades,
    compute_sync_actions,
    find_tier_for_balance,
)

logger = logging.getLogger("elastic_dca.api.ping")

router = APIRouter()


@router.post("/api/client-ping")
async def client_ping(body: ClientPingRequest):
    """
    Section 11.2: POST /api/client-ping

    Auth: None via header. mt5_id is the identifier.
    Subscription check is done server-side.

    Flow (Section 8.2):
      1. Look up user by mt5_id
      2. Check subscription status
      3. Save user snapshot
      4. Tier assignment (with locking)
      5. Compute sync actions for all 4 grids
      6. Return actions array (CLOSE_ALL first, then BUY/SELL)
    """
    # ── Step 1: Look up user by mt5_id (Section 8.2) ────────────────────
    user = await get_user_by_mt5_id(body.mt5_id)
    if not user:
        return {"status": "error", "message": "Unknown account"}

    # ── Step 2: Check user status + subscription (Section 8.2) ───────────
    if user.status == "banned":
        return {"status": "banned", "message": "Account banned"}

    if user.status != "active":
        return {"status": "error", "message": "Account not active"}

    sub_active = await is_subscription_active(user.id)
    if not sub_active:
        return {"status": "expired", "message": "Subscription expired"}

    # ── Step 3: Save user snapshot (Section 8.2, 9.5) ───────────────────
    positions_dicts = [p.model_dump() for p in body.positions]
    await upsert_user_snapshot(user.id, body.balance, positions_dicts)

    # ── Step 4: Tier assignment (Section 8.3) ────────────────────────────
    assigned_ts = None

    if user.assigned_tier_id:
        assigned_ts = get_tier_state(user.assigned_tier_id)

    # Check tier locking: if client has active session trades, stay locked
    if assigned_ts and client_has_active_session_trades(body.positions, assigned_ts):
        # Tier is locked — use currently assigned tier
        pass
    else:
        # No active session trades — re-evaluate balance
        new_ts = find_tier_for_balance(tier_states, body.balance)
        if new_ts is None:
            # Clear assignment if balance is outside all ranges
            if user.assigned_tier_id:
                await update_user_tier(user.id, None)
            return {"status": "no_tier", "message": "Balance outside configured ranges"}

        # Assign (or re-assign) tier
        if not assigned_ts or assigned_ts.tier.id != new_ts.tier.id:
            await update_user_tier(user.id, new_ts.tier.id)
        assigned_ts = new_ts

    if not assigned_ts:
        return {"status": "no_tier", "message": "Balance outside configured ranges"}

    # ── Step 5: Compute sync actions (Section 8.4) ──────────────────────
    actions = compute_sync_actions(assigned_ts, body.positions)

    # ── Step 6: Return response (Section 8.5) ───────────────────────────
    actions_list = []
    for a in actions:
        entry: dict = {"action": a.action, "comment": a.comment}
        if a.volume is not None:
            entry["volume"] = a.volume
        actions_list.append(entry)

    return {
        "status": "ok",
        "tier": assigned_ts.tier.name,
        "actions": actions_list,
    }
