# Phase 2 — Implementation Document

**Project:** Elastic DCA Trading SaaS  
**Blueprint:** `docs/saas_blueprint_v4.md`  
**Phase:** 2 — Authentication + User Management  
**Total Source:** ~2,410 lines across 11 Python files (834 lines added/modified from Phase 1)

---

## 1. Architecture Overview

Phase 2 adds **authentication** (JWT), **user registration/login**, and **admin user management** on top of the Phase 1 core backend. The Master EA data path is unchanged.

```
┌─────────────────┐    HTTP POST         ┌──────────────────────────────────┐
│  Master EA      │ ──────────────────▶  │  FastAPI Server                  │
│  (MetaTrader 5) │  /api/master-tick    │  apps/server/                    │
│                 │  X-Admin-Key header  │                                  │
└─────────────────┘                      │  ┌──────────────────────────┐    │
                                         │  │  Auth Layer              │    │
       ┌─────────────┐                   │  │  (dependencies.py)       │    │
       │  Admin       │  JWT Bearer      │  │  - bcrypt password hash  │    │
       │  (Web UI)    │ ◀────────────▶  │  │  - JWT HS256 tokens      │    │
       │              │  /api/admin/*    │  │  - Role-based guards     │    │
       └─────────────┘  /api/auth/*     │  └──────────────────────────┘    │
                                         │                                  │
       ┌─────────────┐                   │  ┌──────────────────────────┐    │
       │  Client      │  JWT Bearer      │  │  User Management         │    │
       │  (Web UI)    │ ◀────────────▶  │  │  (database.py)           │    │
       │              │  /api/client/*   │  │  - users table           │    │
       └─────────────┘  /api/auth/*     │  │  - subscriptions table   │    │
                                         │  │  - user_snapshots table  │    │
                                         │  └──────────────────────────┘    │
                                         │                                  │
                                         │  ┌──────────────────────────┐    │
                                         │  │  Phase 1 Engine          │    │
                                         │  │  (engine.py + state.py)  │    │
                                         │  │  [UNCHANGED]             │    │
                                         │  └──────────────────────────┘    │
                                         └──────────────────────────────────┘
```

### Auth Strategy (Section 10.1)

| Path                           | Auth Method                | Details                                  |
| ------------------------------ | -------------------------- | ---------------------------------------- |
| Master EA → `/api/master-tick` | `X-Admin-Key` header       | Unchanged from Phase 1                   |
| Admin web → `/api/admin/*`     | JWT Bearer (`role=admin`)  | Admin credentials from `.env`, NOT in DB |
| Client web → `/api/client/*`   | JWT Bearer (`role=client`) | Client users stored in DB                |
| Public → `/api/auth/*`         | None required              | Registration, login, password reset      |

---

## 2. What Changed from Phase 1

### Files Modified

| File                  | Phase 1 Lines | Phase 2 Lines | Change                                                                     |
| --------------------- | ------------- | ------------- | -------------------------------------------------------------------------- |
| `main.py`             | 71            | 82            | +11: auth/client routers, `__main__` block                                 |
| `app/config.py`       | 28            | 35            | +7: `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`, `JWT_SECRET`, `JWT_EXPIRY_HOURS` |
| `app/models.py`       | 142           | 243           | +101: User, Subscription, UserSnapshot, auth/client/admin request models   |
| `app/database.py`     | ~330          | 634           | +304: users/subscriptions/user_snapshots tables, CRUD functions            |
| `app/dependencies.py` | ~38           | 110           | +72: bcrypt, JWT, role-based route guards                                  |
| `app/routes/admin.py` | ~340          | 454           | +114: JWT auth, user management endpoints                                  |
| `requirements.txt`    | 5             | 7             | +2: `bcrypt==5.0.0`, `PyJWT==2.11.0`                                       |
| `.env`                | 5             | 10            | +5: admin email, password hash, JWT secret/expiry                          |

### Files Created (New)

| File                   | Lines | Purpose                                           |
| ---------------------- | ----- | ------------------------------------------------- |
| `app/routes/auth.py`   | 242   | Registration, login, email verify, password reset |
| `app/routes/client.py` | 121   | Client account endpoints                          |

### Files Unchanged

| File                   | Lines | Reason                                  |
| ---------------------- | ----- | --------------------------------------- |
| `app/engine.py`        | 335   | Virtual execution engine — Phase 1 only |
| `app/state.py`         | 102   | In-memory tier state — Phase 1 only     |
| `app/routes/master.py` | 52    | Master-tick endpoint — unchanged        |

---

## 3. File-by-File Breakdown (Phase 2 Changes Only)

### 3.1 `apps/server/app/config.py` (35 lines)

**Blueprint ref:** Section 10.1, 15

Added 4 new settings loaded from `.env`:

| Setting               | Type | Default | Purpose                              |
| --------------------- | ---- | ------- | ------------------------------------ |
| `ADMIN_EMAIL`         | str  | `""`    | Admin login email (not stored in DB) |
| `ADMIN_PASSWORD_HASH` | str  | `""`    | bcrypt hash of admin password        |
| `JWT_SECRET`          | str  | `""`    | HS256 signing key                    |
| `JWT_EXPIRY_HOURS`    | int  | `24`    | Token lifetime                       |

### 3.2 `apps/server/app/models.py` (243 lines)

**Blueprint ref:** Sections 9.1, 9.2, 9.5, 11.3, 11.4, 11.5

Added 12 Pydantic v2 models:

| Model                       | Fields                                                                                                 | Blueprint Section |
| --------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------- |
| `User`                      | id, email, name, phone, mt5_id, assigned_tier_id, role, status, email_verified, created_at, updated_at | 9.1               |
| `Subscription`              | id, user_id, plan_name, status, paypal_sub_id, start_date, end_date, created_at                        | 9.2               |
| `UserSnapshot`              | user_id, equity, balance, positions, last_seen                                                         | 9.5               |
| `RegisterRequest`           | email, name, phone?, password                                                                          | 11.3              |
| `LoginRequest`              | email, password                                                                                        | 11.3              |
| `VerifyEmailRequest`        | token                                                                                                  | 11.3              |
| `ForgotPasswordRequest`     | email                                                                                                  | 11.3              |
| `ResetPasswordRequest`      | token, new_password                                                                                    | 11.3              |
| `UpdateAccountRequest`      | name?, phone?, mt5_id?                                                                                 | 11.5              |
| `UpdateMetaIdRequest`       | mt5_id                                                                                                 | 11.5              |
| `UpdateUserStatusRequest`   | status                                                                                                 | 11.4              |
| `ManageSubscriptionRequest` | plan_name, end_date                                                                                    | 11.4              |

### 3.3 `apps/server/app/database.py` (634 lines)

**Blueprint ref:** Sections 9.1, 9.2, 9.5

#### New Tables (in `_create_schema()`)

**`users` table:**

```sql
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    email          VARCHAR(255) UNIQUE NOT NULL,
    password_hash  VARCHAR(255) NOT NULL,
    name           VARCHAR(100) NOT NULL,
    phone          VARCHAR(20),
    mt5_id         VARCHAR(50) UNIQUE,
    assigned_tier_id INTEGER REFERENCES tiers(id),
    role           VARCHAR(20) DEFAULT 'client',
    status         VARCHAR(20) DEFAULT 'pending',
    email_verified BOOLEAN DEFAULT FALSE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Indexes: idx_users_mt5_id, idx_users_email, idx_users_status
```

**`subscriptions` table:**

```sql
CREATE TABLE IF NOT EXISTS subscriptions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plan_name   VARCHAR(50) NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    paypal_sub_id VARCHAR(100),
    start_date  TIMESTAMP NOT NULL,
    end_date    TIMESTAMP NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Indexes: idx_subscriptions_user, idx_subscriptions_status, idx_subscriptions_end_date
```

**`user_snapshots` table:**

```sql
CREATE TABLE IF NOT EXISTS user_snapshots (
    user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    equity    DECIMAL(15,2),
    balance   DECIMAL(15,2),
    positions JSONB DEFAULT '[]',
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### New CRUD Functions

| Function                                         | Returns                | Purpose                                                                                              |
| ------------------------------------------------ | ---------------------- | ---------------------------------------------------------------------------------------------------- |
| `create_user(email, password_hash, name, phone)` | `User`                 | Insert new user, raises `ValueError` on duplicate email                                              |
| `get_user_by_email(email)`                       | `User \| None`         | Lookup by email                                                                                      |
| `get_user_by_id(user_id)`                        | `User \| None`         | Lookup by ID                                                                                         |
| `get_all_users()`                                | `list[User]`           | All users ordered by id                                                                              |
| `update_user(user_id, **kwargs)`                 | `User \| None`         | Dynamic field update (name, phone, mt5_id, status, password_hash). MT5 ID uniqueness check included. |
| `verify_user_email(user_id)`                     | `User \| None`         | Sets `email_verified=true`, `status='active'`                                                        |
| `create_subscription(user_id, plan, start, end)` | `Subscription`         | Insert new subscription                                                                              |
| `get_subscription_by_user(user_id)`              | `Subscription \| None` | Latest subscription for user                                                                         |
| `update_subscription(sub_id, **kwargs)`          | `Subscription \| None` | Update subscription fields                                                                           |
| `upsert_subscription(user_id, plan, start, end)` | `Subscription`         | Create or update existing subscription                                                               |
| `is_subscription_active(user_id)`                | `bool`                 | Check if user has active, non-expired subscription                                                   |

**Helper:** `_parse_dt(value)` — Converts ISO date strings to naive `datetime` objects for asyncpg compatibility.

### 3.4 `apps/server/app/dependencies.py` (110 lines)

**Blueprint ref:** Sections 10.1, 11.3

Phase 1's `verify_admin_key()` is unchanged. Phase 2 adds:

| Function                                | Purpose                                                              |
| --------------------------------------- | -------------------------------------------------------------------- |
| `hash_password(plain)` → str            | bcrypt hash (`$2b$12$...`)                                           |
| `verify_password(plain, hashed)` → bool | bcrypt verify                                                        |
| `create_jwt(user_id, role)` → str       | JWT with payload `{sub, role, iat, exp}`, HS256, configurable expiry |
| `decode_jwt(token)` → dict              | Decode + validate. Raises 401 on expired/invalid.                    |
| `get_current_user(credentials)` → dict  | FastAPI dependency: extract JWT from `Authorization: Bearer` header  |
| `verify_jwt_admin(payload)` → dict      | Guard: requires `role == 'admin'`, raises 403 otherwise              |
| `verify_jwt_client(payload)` → dict     | Guard: requires `role == 'client'`, raises 403 otherwise             |

**JWT Payload (Section 11.3):**

```json
{
  "sub": "0",
  "role": "admin",
  "iat": 1772321886,
  "exp": 1772408286
}
```

- `sub`: User ID as string (`"0"` for admin)
- `role`: `"admin"` or `"client"`
- Algorithm: HS256
- Expiry: 24 hours (configurable via `JWT_EXPIRY_HOURS`)

### 3.5 `apps/server/app/routes/auth.py` (242 lines) — NEW

**Blueprint ref:** Sections 10.2, 11.3

Router prefix: `/api/auth` (no auth required)

| Endpoint           | Method | Status | Logic                                                                                                                                      |
| ------------------ | ------ | ------ | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `/register`        | POST   | 201    | Validate email/password → bcrypt hash → `create_user()` → generate verification token → return token                                       |
| `/login`           | POST   | 200    | Admin: check `.env`, return JWT with `sub=0, role=admin`. Client: check DB, verify password, check status (banned/unverified), return JWT. |
| `/verify-email`    | POST   | 200    | Consume one-time token → `verify_user_email()` (sets `email_verified=true`, `status='active'`)                                             |
| `/forgot-password` | POST   | 200    | Generate reset token (or silent no-op for unknown emails — security best practice)                                                         |
| `/reset-password`  | POST   | 200    | Consume reset token → bcrypt-hash new password → `update_user()`                                                                           |

**Token Management:** In-memory `dict` stores (`_email_verify_tokens`, `_password_reset_tokens`) with 1-hour expiry and `secrets.token_urlsafe(32)`. Production will use Redis/DB.

**Admin Login Path (Section 10.1):**

1. Login request with admin email → match against `ADMIN_EMAIL` from `.env`
2. Verify password against `ADMIN_PASSWORD_HASH` from `.env`
3. Return JWT with `sub="0"`, `role="admin"` — admin is NEVER stored in the users table

### 3.6 `apps/server/app/routes/client.py` (121 lines) — NEW

**Blueprint ref:** Sections 10.3, 11.5

Router prefix: `/api/client` (requires JWT with `role='client'`)

| Endpoint   | Method | Response                                                                                           |
| ---------- | ------ | -------------------------------------------------------------------------------------------------- |
| `/account` | GET    | `{email, name, phone, mt5_id, subscription: {status, plan_name, start_date, end_date}}`            |
| `/account` | PATCH  | Update name, phone, mt5_id. MT5 ID must be numeric (Section 10.3). Returns updated fields.         |
| `/meta-id` | PATCH  | Dedicated MT5 ID update. Must be numeric, must not be claimed by another user. Returns `{mt5_id}`. |

**MT5 ID Validation (Section 10.3):**

- Must be a numeric string (`isdigit()` check)
- Must be globally unique (DB `UNIQUE` constraint + application-level check before update)
- One MT5 ID per user, updated anytime (old ID is released)

### 3.7 `apps/server/app/routes/admin.py` (454 lines)

**Blueprint ref:** Sections 11.4

**Auth Change:** All admin endpoints migrated from `verify_admin_key` (X-Admin-Key header) to `verify_jwt_admin` (JWT Bearer with `role='admin'`). Master EA endpoint remains on X-Admin-Key.

| Endpoint                        | Method | Purpose                                    | New in Phase 2? |
| ------------------------------- | ------ | ------------------------------------------ | --------------- |
| `/users`                        | GET    | List all users with subscription status    | ✅              |
| `/users/{user_id}`              | PUT    | Update user status (active/banned/pending) | ✅              |
| `/users/{user_id}/subscription` | PUT    | Manually create/update subscription        | ✅              |
| All Phase 1 tier/grid endpoints | —      | Unchanged logic, new auth dependency       | Auth changed    |

**`GET /api/admin/users` response:**

```json
{
  "users": [
    {
      "id": 1,
      "email": "user@example.com",
      "name": "John Doe",
      "phone": "+1234567890",
      "mt5_id": "883921",
      "assigned_tier_id": null,
      "role": "client",
      "status": "active",
      "email_verified": true,
      "subscription": {
        "plan_name": "monthly",
        "status": "active",
        "end_date": "2026-04-01 00:00:00",
        "is_active": true
      },
      "created_at": "2026-02-28 23:17:31.693381"
    }
  ]
}
```

### 3.8 `apps/server/main.py` (82 lines)

**Blueprint ref:** Phase 2 entry point

Changes from Phase 1:

- Version bumped to `4.0.0-phase2`
- Added `auth_router` and `client_router` imports and includes
- Added `if __name__ == "__main__"` block for direct execution via `python main.py`

Router mount order:

```python
app.include_router(master_router)   # POST /api/master-tick (X-Admin-Key)
app.include_router(auth_router)     # POST /api/auth/*      (no auth)
app.include_router(admin_router)    # /api/admin/*           (JWT admin)
app.include_router(client_router)   # /api/client/*          (JWT client)
```

---

## 4. Database Schema Summary (Phase 1 + Phase 2)

| Table                | Phase | Key Columns                                                                                       |
| -------------------- | ----- | ------------------------------------------------------------------------------------------------- |
| `tiers`              | 1     | id, name, symbol, min/max_balance, is_active                                                      |
| `grid_configs`       | 1     | tier_id, grid_id, on, cyclic, start_limit, end_limit, tp, rows                                    |
| `grid_runtimes`      | 1     | tier_id, grid_id, session_id, is_active, waiting_limit, start_ref                                 |
| `market_state`       | 1     | symbol, ask, bid, mid, contract_size, direction                                                   |
| **`users`**          | **2** | **id, email, password_hash, name, phone, mt5_id, assigned_tier_id, role, status, email_verified** |
| **`subscriptions`**  | **2** | **id, user_id, plan_name, status, paypal_sub_id, start_date, end_date**                           |
| **`user_snapshots`** | **2** | **user_id, equity, balance, positions, last_seen**                                                |

---

## 5. API Surface (Phase 1 + Phase 2)

### Auth Endpoints (Phase 2 — No auth)

| Method | Path                        | Purpose                   |
| ------ | --------------------------- | ------------------------- |
| POST   | `/api/auth/register`        | Register new user         |
| POST   | `/api/auth/login`           | Login (admin or client)   |
| POST   | `/api/auth/verify-email`    | Verify email address      |
| POST   | `/api/auth/forgot-password` | Request password reset    |
| POST   | `/api/auth/reset-password`  | Reset password with token |

### Client Endpoints (Phase 2 — JWT `role='client'`)

| Method | Path                  | Purpose                    |
| ------ | --------------------- | -------------------------- |
| GET    | `/api/client/account` | Get profile + subscription |
| PATCH  | `/api/client/account` | Update name, phone, mt5_id |
| PATCH  | `/api/client/meta-id` | Update MT5 account number  |

### Admin Endpoints (JWT `role='admin'`)

| Method  | Path                                        | Purpose                 | Phase |
| ------- | ------------------------------------------- | ----------------------- | ----- |
| GET     | `/api/admin/tiers`                          | List tiers              | 1     |
| POST    | `/api/admin/tiers`                          | Create tier             | 1     |
| PUT     | `/api/admin/tiers/{id}`                     | Update tier             | 1     |
| DELETE  | `/api/admin/tiers/{id}`                     | Delete tier             | 1     |
| GET     | `/api/admin/tiers/{id}/grids`               | Get grid states         | 1     |
| PUT     | `/api/admin/tiers/{id}/grids/{gid}/config`  | Configure grid          | 1     |
| POST    | `/api/admin/tiers/{id}/grids/{gid}/control` | ON/OFF control          | 1     |
| GET     | `/api/admin/market`                         | Current market state    | 1     |
| **GET** | **`/api/admin/users`**                      | **List all users**      | **2** |
| **PUT** | **`/api/admin/users/{id}`**                 | **Update user status**  | **2** |
| **PUT** | **`/api/admin/users/{id}/subscription`**    | **Manage subscription** | **2** |

### Master EA Endpoint (X-Admin-Key — unchanged)

| Method | Path               | Purpose          |
| ------ | ------------------ | ---------------- |
| POST   | `/api/master-tick` | Market data feed |

---

## 6. Environment Variables

| Variable                  | Purpose                           | Example                                                   |
| ------------------------- | --------------------------------- | --------------------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL connection             | `postgresql://elastic_dca:...@localhost:5432/elastic_dca` |
| `ADMIN_KEY`               | Master EA auth header             | `test_admin_key_12345`                                    |
| `HOST`                    | Server bind address               | `0.0.0.0`                                                 |
| `PORT`                    | Server bind port                  | `8000`                                                    |
| **`ADMIN_EMAIL`**         | **Admin login email**             | **`admin@elasticdca.com`**                                |
| **`ADMIN_PASSWORD_HASH`** | **bcrypt hash of admin password** | **`$2b$12$6QXE...`**                                      |
| **`JWT_SECRET`**          | **JWT signing key**               | **`test_jwt_secret_key_...`**                             |
| **`JWT_EXPIRY_HOURS`**    | **Token lifetime in hours**       | **`24`**                                                  |

---

## 7. Dependencies

| Package       | Version    | Purpose                           |
| ------------- | ---------- | --------------------------------- |
| fastapi       | 0.115.12   | Web framework                     |
| uvicorn       | 0.34.2     | ASGI server                       |
| asyncpg       | 0.30.0     | PostgreSQL driver                 |
| pydantic      | 2.11.3     | Data validation                   |
| python-dotenv | 1.1.0      | .env loading                      |
| **bcrypt**    | **5.0.0**  | **Password hashing**              |
| **PyJWT**     | **2.11.0** | **JWT token creation/validation** |

---

## 8. Bugs Found & Fixed During Implementation

### Bug 1: asyncpg DataError with timestamp strings

**Problem:** Subscription CRUD functions passed ISO date strings with `::timestamp` SQL casts, but asyncpg requires native Python `datetime` objects for parameterized queries.

**Fix:** Added `_parse_dt()` helper that parses ISO strings to naive `datetime` objects. Removed `::timestamp` casts from SQL.

### Bug 2: Mixing offset-aware and offset-naive datetimes

**Problem:** Admin route used `datetime.now(timezone.utc)` (offset-aware) while parsed dates from user input were offset-naive. asyncpg cannot compare mixed types.

**Fix:** Made `_parse_dt()` always strip timezone info and changed admin route to use `datetime.utcnow()`.

### Bug 3: PyJWT `InvalidSubjectError` — sub must be string

**Problem:** JWT `sub` claim was set to an integer (`user_id`), but PyJWT enforces that standard `sub` claims must be strings per RFC 7519.

**Fix:** Changed `create_jwt()` to use `str(user_id)` and `int(payload["sub"])` at consumption points.

---

## 9. Blueprint Compliance

Cross-checked against blueprint sections 9.1, 9.2, 9.5, 10, 11.3, 11.4, 11.5, 15.

| Category                                        | Score        |
| ----------------------------------------------- | ------------ |
| Section 9.1 — users table                       | 15/15 (100%) |
| Section 9.2 — subscriptions table               | 11/11 (100%) |
| Section 9.5 — user_snapshots table              | 5/5 (100%)   |
| Section 10 — Auth & Subscription                | 12/12 (100%) |
| Section 11.3 — Auth Endpoints + JWT             | 9/9 (100%)   |
| Section 11.4 — Admin Endpoints (Phase 2 scope)  | 11/11 (100%) |
| Section 11.5 — Client Endpoints (Phase 2 scope) | 3/3 (100%)   |
| Section 15 — Phase 2 Deliverables               | 12/12 (100%) |
| Config / .env                                   | 8/8 (100%)   |

**Correctly deferred to later phases:**

- `GET /api/admin/tiers/{id}/clients` → Phase 3 (requires Client EA sync)
- `GET /api/admin/tiers/{id}/clients/{uid}/positions` → Phase 3
- `GET /api/client/dashboard` → Phase 4 (requires Client EA data)
- PayPal webhook integration → Phase 5
- Email sending (verification, password reset) → Phase 5
