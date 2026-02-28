"""Shared route dependencies and utilities."""

from __future__ import annotations

from fastapi import Header, HTTPException

from app.config import settings


async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> str:
    """
    Validate the X-Admin-Key header against .env value.
    Blueprint Section 3.1: "Every request includes the X-Admin-Key header."
    Used by master-tick AND admin endpoints in Phase 1 (no JWT yet).
    """
    if x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return x_admin_key
