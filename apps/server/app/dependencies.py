"""
Shared route dependencies and utilities.

Phase 1: verify_admin_key (X-Admin-Key header for Master EA)
Phase 2: JWT verification for admin and client routes (Section 10)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
from fastapi import Header, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import settings

# ── Reusable HTTP Bearer scheme ─────────────────────────────────────────────
_bearer_scheme = HTTPBearer()


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Master EA auth (unchanged)
# ═══════════════════════════════════════════════════════════════════════════════

async def verify_admin_key(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> str:
    """
    Validate the X-Admin-Key header against .env value.
    Blueprint Section 3.1: "Every request includes the X-Admin-Key header."
    Used by POST /api/master-tick only (Phase 2 admin routes use JWT).
    """
    if x_admin_key != settings.ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")
    return x_admin_key


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 — JWT Auth (Section 10)
# ═══════════════════════════════════════════════════════════════════════════════

def hash_password(plain: str) -> str:
    """Hash a password with bcrypt. Returns $2b$12$... string."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_jwt(user_id: int, role: str) -> str:
    """
    Create a JWT token.
    Payload: {sub, role, iat, exp}  — standard JWT claims per blueprint §11.3
    Signed with JWT_SECRET from .env.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    """Decode and validate a JWT token. Raises on invalid/expired."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """
    Extract and validate JWT from Authorization header.
    Returns the decoded payload dict: {sub, role, ...}.
    """
    return decode_jwt(credentials.credentials)


async def verify_jwt_admin(
    payload: dict = Depends(get_current_user),
) -> dict:
    """
    JWT auth dependency for admin routes.
    Blueprint Section 10.1: "Admin logs in with email + password → receives JWT."
    Requires role == 'admin'.
    """
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


async def verify_jwt_client(
    payload: dict = Depends(get_current_user),
) -> dict:
    """
    JWT auth dependency for client routes.
    Requires role == 'client'.
    """
    if payload.get("role") != "client":
        raise HTTPException(status_code=403, detail="Client access required")
    return payload
