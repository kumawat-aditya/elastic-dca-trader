# Phase 2 — Run & Test Guide

**Project:** Elastic DCA Trading SaaS  
**Phase:** 2 — Authentication + User Management

---

## 1. Prerequisites

| Requirement       | Minimum Version | Check Command                  |
| ----------------- | --------------- | ------------------------------ |
| Python            | 3.12+           | `python3 --version`            |
| PostgreSQL        | 15+             | `psql --version` or use Docker |
| Docker (optional) | 20+             | `docker --version`             |
| curl              | any             | `curl --version`               |
| Phase 1           | Complete        | Server runs, tiers/grids work  |

---

## 2. Setup

### 2.1 Navigate to Server

```bash
cd Elastic_DCA_Trading/apps/server
```

### 2.2 Activate Virtual Environment

```bash
source venv/bin/activate
```

### 2.3 Install Dependencies

Phase 2 adds `bcrypt` and `PyJWT`:

```bash
pip install -r requirements.txt
```

Verify new packages:

```bash
python -c "import bcrypt; print('bcrypt', bcrypt.__version__)"
python -c "import jwt; print('PyJWT', jwt.__version__)"
```

### 2.4 Ensure PostgreSQL is Running

```bash
docker start elastic_dca_pg
# or: docker ps | grep elastic_dca_pg
```

### 2.5 Configure Environment

Your `.env` file should contain these Phase 2 additions:

```env
# Phase 1 (existing)
DATABASE_URL=postgresql://elastic_dca:elastic_dca_pass@localhost:5432/elastic_dca
ADMIN_KEY=test_admin_key_12345
HOST=0.0.0.0
PORT=8000

# Phase 2 (new)
ADMIN_EMAIL=admin@elasticdca.com
ADMIN_PASSWORD_HASH=$2b$12$6QXECRcp7Tvi8vTSAEWBOO2FKIWTNB0ZNuTkRQO/agAOCtzqJ4fp6
JWT_SECRET=test_jwt_secret_key_change_in_production
JWT_EXPIRY_HOURS=24
```

> **Note:** The default `ADMIN_PASSWORD_HASH` corresponds to password `admin123`. To generate a new hash:
>
> ```bash
> python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt()).decode())"
> ```

### 2.6 Start Server

```bash
python main.py
```

Expected startup output:

```
════════════════════════════════════════════════════════════
  Elastic DCA Cloud — Phase 2 Server Starting
════════════════════════════════════════════════════════════
... DB pool created ...
... Schema ensured / loaded ...
Server ready. Auth + User management enabled.
════════════════════════════════════════════════════════════
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2.7 Verify Server

```bash
curl -s http://localhost:8000/health
```

Expected:

```json
{ "status": "ok", "version": "4.0.0-phase2" }
```

---

## 3. Test Phase 2 Endpoints

All commands assume the server is running on `http://localhost:8000`.

### 3.1 Register a New User

```bash
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "name": "John Doe",
    "phone": "+1234567890",
    "password": "testpass123"
  }'
```

Expected (201):

```json
{
  "status": "ok",
  "message": "Verification email sent",
  "verification_token": "<TOKEN_STRING>"
}
```

> **Save the `verification_token`** — you'll need it in step 3.3.

**Test duplicate registration:**

```bash
curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "name": "Dup", "password": "testpass123"}'
```

Expected (400):

```json
{ "detail": "Email already registered" }
```

### 3.2 Login Before Verification (Should Fail)

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'
```

Expected (403):

```json
{ "detail": "Email not verified. Please verify your email first." }
```

### 3.3 Verify Email

Replace `<TOKEN>` with the verification token from step 3.1:

```bash
curl -s -X POST http://localhost:8000/api/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token": "<TOKEN>"}'
```

Expected (200):

```json
{ "status": "ok", "message": "Email verified" }
```

### 3.4 Client Login

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'
```

Expected (200):

```json
{
  "token": "<JWT_TOKEN>",
  "user": {
    "id": 1,
    "email": "test@example.com",
    "name": "John Doe",
    "role": "client",
    "mt5_id": null
  }
}
```

> **Save the `token`** — this is your client JWT for subsequent requests.

**Store in shell variable:**

```bash
CLIENT_TOKEN="<paste JWT token here>"
```

### 3.5 Admin Login

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@elasticdca.com", "password": "admin123"}'
```

Expected (200):

```json
{
  "token": "<JWT_TOKEN>",
  "user": {
    "id": 0,
    "email": "admin@elasticdca.com",
    "name": "Admin",
    "role": "admin",
    "mt5_id": null
  }
}
```

> **Note:** Admin returns `id: 0` because admin is not stored in the DB.

**Store in shell variable:**

```bash
ADMIN_TOKEN="<paste JWT token here>"
```

**Verify JWT payload** (optional):

```bash
echo "$ADMIN_TOKEN" | cut -d. -f2 | python3 -c "
import sys, base64, json
s = sys.stdin.read().strip()
s += '=' * (4 - len(s) % 4)
print(json.dumps(json.loads(base64.urlsafe_b64decode(s)), indent=2))
"
```

Expected:

```json
{
  "sub": "0",
  "role": "admin",
  "iat": 1772321886,
  "exp": 1772408286
}
```

---

## 4. Test Client Endpoints

All require `Authorization: Bearer $CLIENT_TOKEN`.

### 4.1 Get Account

```bash
curl -s http://localhost:8000/api/client/account \
  -H "Authorization: Bearer $CLIENT_TOKEN"
```

Expected (200):

```json
{
  "email": "test@example.com",
  "name": "John Doe",
  "phone": "+1234567890",
  "mt5_id": null,
  "subscription": null
}
```

### 4.2 Update MT5 ID

```bash
curl -s -X PATCH http://localhost:8000/api/client/meta-id \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mt5_id": "883921"}'
```

Expected (200):

```json
{ "mt5_id": "883921" }
```

**Test non-numeric MT5 ID (should fail):**

```bash
curl -s -X PATCH http://localhost:8000/api/client/meta-id \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mt5_id": "abc123"}'
```

Expected (400):

```json
{ "detail": "MT5 ID must be numeric" }
```

### 4.3 Update Account

```bash
curl -s -X PATCH http://localhost:8000/api/client/account \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "John Updated", "phone": "+9876543210"}'
```

Expected (200):

```json
{
  "email": "test@example.com",
  "name": "John Updated",
  "phone": "+9876543210",
  "mt5_id": "883921"
}
```

---

## 5. Test Admin User Management

All require `Authorization: Bearer $ADMIN_TOKEN`.

### 5.1 List Users

```bash
curl -s http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Expected (200):

```json
{
  "users": [
    {
      "id": 1,
      "email": "test@example.com",
      "name": "John Updated",
      "phone": "+9876543210",
      "mt5_id": "883921",
      "assigned_tier_id": null,
      "role": "client",
      "status": "active",
      "email_verified": true,
      "subscription": {
        "plan_name": null,
        "status": null,
        "end_date": null,
        "is_active": false
      },
      "created_at": "2026-02-28T..."
    }
  ]
}
```

### 5.2 Manage Subscription

```bash
curl -s -X PUT http://localhost:8000/api/admin/users/1/subscription \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_name": "monthly", "end_date": "2026-04-01T00:00:00"}'
```

Expected (200):

```json
{
  "subscription": {
    "id": 1,
    "user_id": 1,
    "plan_name": "monthly",
    "status": "active",
    "start_date": "2026-03-01 ...",
    "end_date": "2026-04-01 00:00:00"
  }
}
```

### 5.3 Verify Client Sees Subscription

```bash
curl -s http://localhost:8000/api/client/account \
  -H "Authorization: Bearer $CLIENT_TOKEN"
```

Expected — subscription data now present:

```json
{
  "email": "test@example.com",
  "name": "John Updated",
  "phone": "+9876543210",
  "mt5_id": "883921",
  "subscription": {
    "status": "active",
    "plan_name": "monthly",
    "start_date": "2026-03-01 ...",
    "end_date": "2026-04-01 00:00:00"
  }
}
```

### 5.4 Ban User

```bash
curl -s -X PUT http://localhost:8000/api/admin/users/1 \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "banned"}'
```

Expected (200):

```json
{
  "user": {
    "id": 1,
    "email": "test@example.com",
    "name": "John Updated",
    "status": "banned",
    "email_verified": true
  }
}
```

### 5.5 Banned User Cannot Login

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'
```

Expected (403):

```json
{ "detail": "Account is banned" }
```

### 5.6 Unban User

```bash
curl -s -X PUT http://localhost:8000/api/admin/users/1 \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "active"}'
```

---

## 6. Test Password Reset Flow

### 6.1 Request Reset Token

```bash
curl -s -X POST http://localhost:8000/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
```

Expected (200):

```json
{
  "status": "ok",
  "message": "If the email exists, a reset link has been sent",
  "reset_token": "<RESET_TOKEN>"
}
```

> **Save the `reset_token`.**

### 6.2 Reset Password

```bash
curl -s -X POST http://localhost:8000/api/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{"token": "<RESET_TOKEN>", "new_password": "newpassword456"}'
```

Expected (200):

```json
{ "status": "ok", "message": "Password reset successfully" }
```

### 6.3 Login with New Password

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "newpassword456"}'
```

Expected (200): JWT token returned.

### 6.4 Old Password No Longer Works

```bash
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'
```

Expected (401):

```json
{ "detail": "Invalid credentials" }
```

---

## 7. Test Role-Based Access Control

### 7.1 Client Token Cannot Access Admin Routes

```bash
curl -s http://localhost:8000/api/admin/users \
  -H "Authorization: Bearer $CLIENT_TOKEN"
```

Expected (403):

```json
{ "detail": "Admin access required" }
```

### 7.2 No Token Cannot Access Protected Routes

```bash
curl -s http://localhost:8000/api/admin/tiers
```

Expected (403):

```json
{ "detail": "Not authenticated" }
```

```bash
curl -s http://localhost:8000/api/client/account
```

Expected (403):

```json
{ "detail": "Not authenticated" }
```

### 7.3 Admin Token Cannot Access Client Routes

```bash
curl -s http://localhost:8000/api/client/account \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Expected (403):

```json
{ "detail": "Client access required" }
```

---

## 8. Test Phase 1 Backward Compatibility

Phase 1 endpoints must still work unchanged.

### 8.1 Master Tick (X-Admin-Key Auth)

```bash
curl -s -X POST http://localhost:8000/api/master-tick \
  -H "X-Admin-Key: test_admin_key_12345" \
  -H "Content-Type: application/json" \
  -d '{"ask": 1.10500, "bid": 1.10480, "contract_size": 100000}'
```

Expected (200):

```json
{ "status": "ok" }
```

### 8.2 Admin Tiers (Now JWT Auth)

```bash
curl -s http://localhost:8000/api/admin/tiers \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Expected (200): Tiers array (may be empty if no tiers created).

---

## 9. Quick Automated Test Script

Save as `test_phase2.sh` and run with `bash test_phase2.sh`:

```bash
#!/bin/bash
BASE="http://localhost:8000"
PASS=0 FAIL=0

check() {
  local desc="$1" expect="$2" actual="$3"
  if echo "$actual" | grep -q "$expect"; then
    echo "  ✅ $desc"
    ((PASS++))
  else
    echo "  ❌ $desc (expected '$expect', got: $actual)"
    ((FAIL++))
  fi
}

echo "=== Phase 2 Test Suite ==="

# Health
R=$(curl -s $BASE/health)
check "Health check" "phase2" "$R"

# Register
R=$(curl -s -X POST $BASE/api/auth/register -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com","name":"Auto Test","password":"testpass123"}')
check "Register" "verification_token" "$R"
VTOKEN=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('verification_token',''))" 2>/dev/null)

# Duplicate register
R=$(curl -s -X POST $BASE/api/auth/register -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com","name":"Dup","password":"testpass123"}')
check "Duplicate register blocked" "already registered" "$R"

# Login before verify
R=$(curl -s -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com","password":"testpass123"}')
check "Login before verify fails" "not verified" "$R"

# Verify email
R=$(curl -s -X POST $BASE/api/auth/verify-email -H "Content-Type: application/json" \
  -d "{\"token\":\"$VTOKEN\"}")
check "Email verification" "Email verified" "$R"

# Client login
R=$(curl -s -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com","password":"testpass123"}')
check "Client login" "token" "$R"
CT=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)

# Admin login
R=$(curl -s -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"admin@elasticdca.com","password":"admin123"}')
check "Admin login" "token" "$R"
AT=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)

# Client account
R=$(curl -s $BASE/api/client/account -H "Authorization: Bearer $CT")
check "Client account" "autotest@test.com" "$R"

# Update MT5 ID
R=$(curl -s -X PATCH $BASE/api/client/meta-id -H "Authorization: Bearer $CT" \
  -H "Content-Type: application/json" -d '{"mt5_id":"999888"}')
check "Update MT5 ID" "999888" "$R"

# Non-numeric MT5
R=$(curl -s -X PATCH $BASE/api/client/meta-id -H "Authorization: Bearer $CT" \
  -H "Content-Type: application/json" -d '{"mt5_id":"abc"}')
check "Non-numeric MT5 rejected" "numeric" "$R"

# Admin list users
R=$(curl -s $BASE/api/admin/users -H "Authorization: Bearer $AT")
check "Admin list users" "autotest@test.com" "$R"

# Client→Admin blocked
R=$(curl -s $BASE/api/admin/users -H "Authorization: Bearer $CT")
check "Client→Admin blocked" "Admin access required" "$R"

# No auth blocked
R=$(curl -s $BASE/api/admin/tiers)
check "No auth blocked" "Not authenticated" "$R"

# Master tick (Phase 1 compat)
R=$(curl -s -X POST $BASE/api/master-tick -H "X-Admin-Key: test_admin_key_12345" \
  -H "Content-Type: application/json" -d '{"ask":1.105,"bid":1.104,"contract_size":100000}')
check "Master tick (Phase 1)" "ok" "$R"

# Forgot password
R=$(curl -s -X POST $BASE/api/auth/forgot-password -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com"}')
check "Forgot password" "reset_token" "$R"
RTOKEN=$(echo "$R" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reset_token',''))" 2>/dev/null)

# Reset password
R=$(curl -s -X POST $BASE/api/auth/reset-password -H "Content-Type: application/json" \
  -d "{\"token\":\"$RTOKEN\",\"new_password\":\"newpass789\"}")
check "Reset password" "reset successfully" "$R"

# Login with new password
R=$(curl -s -X POST $BASE/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"autotest@test.com","password":"newpass789"}')
check "Login new password" "token" "$R"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
```

---

## 10. Cleanup / Reset

### Drop Phase 2 Tables (keep Phase 1)

```sql
-- Connect to DB
docker exec -it elastic_dca_pg psql -U elastic_dca -d elastic_dca

-- Drop Phase 2 tables
DROP TABLE IF EXISTS user_snapshots CASCADE;
DROP TABLE IF EXISTS subscriptions CASCADE;
DROP TABLE IF EXISTS users CASCADE;
```

### Full Database Reset

```bash
docker stop elastic_dca_pg && docker rm elastic_dca_pg
# Re-create with the docker run command from step 2.4
```

---

## 11. Expected Test Results Summary

| #   | Test                       | Expected Status | Expected Response                    |
| --- | -------------------------- | --------------- | ------------------------------------ |
| 1   | Health check               | 200             | `version: 4.0.0-phase2`              |
| 2   | Register new user          | 201             | `verification_token` present         |
| 3   | Duplicate register         | 400             | `Email already registered`           |
| 4   | Login before verify        | 403             | `Email not verified`                 |
| 5   | Verify email               | 200             | `Email verified`                     |
| 6   | Client login               | 200             | JWT `token` + user object            |
| 7   | Admin login                | 200             | JWT `token` + admin user (`id=0`)    |
| 8   | GET client account         | 200             | Profile + subscription data          |
| 9   | PATCH MT5 ID (valid)       | 200             | `mt5_id` updated                     |
| 10  | PATCH MT5 ID (non-numeric) | 400             | `MT5 ID must be numeric`             |
| 11  | PATCH client account       | 200             | Updated fields returned              |
| 12  | GET admin users            | 200             | Users array with subscription status |
| 13  | PUT admin subscription     | 200             | Subscription created/updated         |
| 14  | Client sees subscription   | 200             | Subscription in account response     |
| 15  | Ban user                   | 200             | Status changed to `banned`           |
| 16  | Banned user login          | 403             | `Account is banned`                  |
| 17  | Forgot password            | 200             | `reset_token` present                |
| 18  | Reset password             | 200             | `Password reset successfully`        |
| 19  | Login with new password    | 200             | JWT token returned                   |
| 20  | Client→Admin (role guard)  | 403             | `Admin access required`              |
| 21  | No auth→Protected          | 403             | `Not authenticated`                  |
| 22  | Admin→Client (role guard)  | 403             | `Client access required`             |
| 23  | Master tick (Phase 1)      | 200             | `{"status":"ok"}`                    |
| 24  | Admin tiers (JWT auth)     | 200             | Tiers array                          |
