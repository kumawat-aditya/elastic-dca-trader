"""
Client API endpoints — Account management, MT5 ID update.

Blueprint references:
  - Section 11.5 : Client Dashboard Endpoints
  - Section 10.3 : MetaID Management
  - All require JWT with role == 'client'
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_subscription_by_user, get_user_by_id, update_user
from app.dependencies import verify_jwt_client
from app.models import UpdateAccountRequest, UpdateMetaIdRequest

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
