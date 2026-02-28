"""
Auth API endpoints — Registration, Login, Email verification, Password reset.

Blueprint references:
  - Section 10.2 : User Registration & Login flows
  - Section 11.3 : Auth endpoint specifications
  - Phase 2      : No auth required for these endpoints
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.database import create_user, get_user_by_email, get_user_by_id, update_user, verify_user_email
from app.dependencies import create_jwt, hash_password, verify_password
from app.models import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)

logger = logging.getLogger("elastic_dca.api.auth")

router = APIRouter(prefix="/api/auth")

# ── In-memory token stores (Phase 2: simple approach, no external email service) ─
# In production, these would be stored in Redis or DB with proper expiry.
# Format: { token_string: { "user_id": int, "expires": float } }
_email_verify_tokens: dict[str, dict] = {}
_password_reset_tokens: dict[str, dict] = {}

TOKEN_EXPIRY_SECONDS = 3600  # 1 hour


def _generate_token(user_id: int, store: dict) -> str:
    """Generate a secure random token and store it."""
    token = secrets.token_urlsafe(32)
    store[token] = {
        "user_id": user_id,
        "expires": time.time() + TOKEN_EXPIRY_SECONDS,
    }
    return token


def _validate_token(token: str, store: dict) -> int | None:
    """Validate token from store, return user_id or None."""
    data = store.get(token)
    if not data:
        return None
    if time.time() > data["expires"]:
        store.pop(token, None)
        return None
    return data["user_id"]


def _consume_token(token: str, store: dict) -> int | None:
    """Validate and remove token, return user_id or None."""
    user_id = _validate_token(token, store)
    if user_id is not None:
        store.pop(token, None)
    return user_id


# ── POST /api/auth/register ─────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    """
    Section 11.3 — POST /api/auth/register
    1. Create user with status='pending', email_verified=false.
    2. Generate email verification token.
    3. In production, send verification email. In Phase 2, return token for testing.
    """
    # Validate email format (basic)
    if "@" not in body.email or "." not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate password length
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Hash password with bcrypt
    pw_hash = hash_password(body.password)

    try:
        user = await create_user(body.email, pw_hash, body.name, body.phone)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate verification token
    token = _generate_token(user.id, _email_verify_tokens)

    logger.info("User registered: %s (id=%d). Verification token generated.", user.email, user.id)

    return {
        "status": "ok",
        "message": "Verification email sent",
        # Phase 2: Include token in response for testing (no email service yet)
        "verification_token": token,
    }


# ── POST /api/auth/login ────────────────────────────────────────────────────

@router.post("/login")
async def login(body: LoginRequest):
    """
    Section 11.3 — POST /api/auth/login
    1. Check if it's an admin login (compare with .env ADMIN_EMAIL).
    2. Otherwise find user in DB, verify password, return JWT.
    """
    # ── Admin login (Section 10.1: admin credentials from .env, NOT in DB) ──
    if body.email == settings.ADMIN_EMAIL:
        if not settings.ADMIN_PASSWORD_HASH:
            raise HTTPException(status_code=500, detail="Admin password hash not configured")
        if not verify_password(body.password, settings.ADMIN_PASSWORD_HASH):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_jwt(user_id=0, role="admin")
        logger.info("Admin logged in: %s", settings.ADMIN_EMAIL)
        return {
            "token": token,
            "user": {
                "id": 0,
                "email": settings.ADMIN_EMAIL,
                "name": "Admin",
                "role": "admin",
                "mt5_id": None,
            },
        }

    # ── Client login ────────────────────────────────────────────────────────
    user = await get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Fetch password hash from DB (need raw row for password_hash)
    from app.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT password_hash FROM users WHERE id = $1", user.id
        )
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check user status
    if user.status == "banned":
        raise HTTPException(status_code=403, detail="Account is banned")
    if user.status == "pending" and not user.email_verified:
        raise HTTPException(status_code=403, detail="Email not verified. Please verify your email first.")

    token = create_jwt(user_id=user.id, role=user.role)
    logger.info("User logged in: %s (id=%d)", user.email, user.id)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "mt5_id": user.mt5_id,
        },
    }


# ── POST /api/auth/verify-email ─────────────────────────────────────────────

@router.post("/verify-email")
async def verify_email(body: VerifyEmailRequest):
    """
    Section 11.3 — POST /api/auth/verify-email
    Section 10.2: User clicks verification link → email_verified=true, status='active'.
    """
    user_id = _consume_token(body.token, _email_verify_tokens)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    user = await verify_user_email(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("Email verified for user id=%d (%s)", user.id, user.email)
    return {"status": "ok", "message": "Email verified"}


# ── POST /api/auth/forgot-password ──────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """
    Section 11.3 — POST /api/auth/forgot-password
    Generate password reset token. In production, send via email.
    Phase 2: Return token in response for testing.
    """
    user = await get_user_by_email(body.email)
    if not user:
        # Don't reveal whether the email exists (security best practice)
        return {"status": "ok", "message": "If the email exists, a reset link has been sent"}

    token = _generate_token(user.id, _password_reset_tokens)
    logger.info("Password reset token generated for user id=%d (%s)", user.id, user.email)

    return {
        "status": "ok",
        "message": "If the email exists, a reset link has been sent",
        # Phase 2: Include token in response for testing
        "reset_token": token,
    }


# ── POST /api/auth/reset-password ───────────────────────────────────────────

@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """
    Section 11.3 — POST /api/auth/reset-password
    Validate reset token, update password.
    """
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user_id = _consume_token(body.token, _password_reset_tokens)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    pw_hash = hash_password(body.new_password)
    user = await update_user(user_id, password_hash=pw_hash)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("Password reset for user id=%d (%s)", user.id, user.email)
    return {"status": "ok", "message": "Password reset successfully"}
