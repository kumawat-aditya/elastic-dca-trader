# Phase 3 — Run & Test Guide

**Version:** `4.0.0-phase3`

---

## Prerequisites

| Component | Required | Check |
|---|---|---|
| Python | 3.12+ | `python3 --version` |
| PostgreSQL 16 | Running via Docker | `docker ps \| grep elastic_dca_pg` |
| Virtual env | Activated | `source apps/server/venv/bin/activate` |
| Dependencies | Installed | `pip install -r apps/server/requirements.txt` |

---

## 1. Start the Server

```bash
cd apps/server
source venv/bin/activate
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO:     Started server process
INFO:elastic_dca: ═══════════════════════════════════════════
INFO:elastic_dca:   Elastic DCA Trading Engine v4.0.0-phase3
INFO:elastic_dca:   Phase 3 Server Starting
INFO:elastic_dca:   Auth + User management + Client sync enabled.
INFO:elastic_dca: ═══════════════════════════════════════════
INFO:elastic_dca.startup: Loaded tier id=... name='...'
INFO:     Application startup complete.
```

---

## 2. Quick Health Check

```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected:
```json
{"status": "ok", "version": "4.0.0-phase3"}
```

---

## 3. Clean Test Environment

```bash
# Remove any leftover test data
docker exec elastic_dca_pg psql -U elastic_dca -d elastic_dca -c \
  "DELETE FROM user_snapshots; DELETE FROM subscriptions; DELETE FROM users;"
```

---

## 4. Comprehensive Test Script

The full test suite is provided below. Save it and run with Python (requires `requests`):

```bash
pip install requests
python3 phase3_test.py
```

### Test Script

```python
#!/usr/bin/env python3
"""Phase 3 Comprehensive Test Suite — 24 tests covering all sync scenarios"""
import requests, json

BASE = "http://localhost:8000"
ADMIN_KEY = "test_admin_key_12345"  # Must match .env ADMIN_KEY

def pp(data):
    print(json.dumps(data, indent=2))

def heading(n, text):
    print(f"\n▸ {n}. {text}")

def setup_client(admin_token, email, name, mt5_id=None):
    """Register → verify → login → subscription → set MT5. Returns (user_id, token)."""
    r = requests.post(f"{BASE}/api/auth/register",
        json={"email":email,"password":"testpass123","name":name})
    reg = r.json()
    assert "verification_token" in reg, f"Register failed: {reg}"

    requests.post(f"{BASE}/api/auth/verify-email", json={"token": reg["verification_token"]})

    r = requests.post(f"{BASE}/api/auth/login",
        json={"email":email,"password":"testpass123"})
    login = r.json()
    user_id = login["user"]["id"]
    token = login["token"]

    requests.put(f"{BASE}/api/admin/users/{user_id}/subscription",
        json={"plan_name":"monthly","end_date":"2027-12-31T23:59:59"},
        headers={"Authorization":f"Bearer {admin_token}"})

    if mt5_id:
        requests.patch(f"{BASE}/api/client/meta-id",
            json={"mt5_id": mt5_id},
            headers={"Authorization":f"Bearer {token}"})

    return user_id, token

print("═" * 60)
print("  Phase 3 Comprehensive Test Suite")
print("═" * 60)

# ── 1. Admin Login ──
heading(1, "Admin Login")
r = requests.post(f"{BASE}/api/auth/login",
    json={"email":"admin@elasticdca.com","password":"admin123"})
ADMIN_TOKEN = r.json()["token"]
print("  Token obtained")

# ── 2. Get tier ──
heading(2, "Get tier")
r = requests.get(f"{BASE}/api/admin/tiers", headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
TIER_ID = r.json()["tiers"][0]["id"]
print(f"  Tier ID: {TIER_ID}")

# ── 3. Reset all grids OFF ──
heading(3, "Reset all grids OFF")
for gid in ["B1","B2","S1","S2"]:
    requests.post(f"{BASE}/api/admin/tiers/{TIER_ID}/grids/{gid}/control",
        json={"on":False}, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
print("  Done")

# ── 4. Setup client 1 ──
heading(4, "Setup client 1")
CLIENT1_ID, CLIENT1_TOKEN = setup_client(ADMIN_TOKEN, "phase3c1@test.com", "Client One", "883921")
print(f"  Client ID={CLIENT1_ID}")

# ── 5. Unknown mt5_id ──
heading(5, "Unknown mt5_id")
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"999999","balance":5000.0,"positions":[]})
pp(r.json())
assert r.json()["status"] == "error"

# ── 6. First ping → tier assignment ──
heading(6, "First ping (tier assignment)")
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"883921","balance":5000.0,"positions":[]})
pp(r.json())
assert r.json()["status"] == "ok"
print(f"  ✓ Tier: {r.json()['tier']}")

# ── 7. Configure B1 grid ──
heading(7, "Configure B1 grid (5 rows)")
requests.put(f"{BASE}/api/admin/tiers/{TIER_ID}/grids/B1/config",
    json={
        "tp_type":"fixed_money","tp_value":500.0,"start_limit":0,"end_limit":0,
        "rows":[
            {"index":0,"dollar":0,"lots":0.01},
            {"index":1,"dollar":2.0,"lots":0.02},
            {"index":2,"dollar":3.0,"lots":0.03},
            {"index":3,"dollar":4.0,"lots":0.04},
            {"index":4,"dollar":5.0,"lots":0.05}
        ]
    }, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
print("  Configured")

# ── 8. Activate B1 ──
heading(8, "Send tick → Turn B1 ON")
# Send tick FIRST to set market price (activate_grid reads current market)
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2050.50,"bid":2050.10}, headers={"X-Admin-Key": ADMIN_KEY})
# Turn ON → start_ref = 2050.50, row 0 executes immediately
requests.post(f"{BASE}/api/admin/tiers/{TIER_ID}/grids/B1/control",
    json={"on":True,"cyclic":True}, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2050.50,"bid":2050.10}, headers={"X-Admin-Key": ADMIN_KEY})

r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/grids",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
grids = r.json()["grids"]
b1 = [g for g in grids if g["grid_id"] == "B1"][0]
SESSION_ID = b1["runtime"]["session_id"]
exec_count = sum(1 for row in b1["config"]["rows"] if row["executed"])
print(f"  Session: {SESSION_ID}")
print(f"  Executed rows: {exec_count}")
assert exec_count == 1

# ── 9. SCENARIO 2: Fresh Join ──
heading(9, "SCENARIO 2: Fresh Join (1 master row, 0 client)")
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"883921","balance":5000.0,"positions":[]})
result = r.json()
pp(result)
assert len(result["actions"]) == 1
assert result["actions"][0]["action"] == "BUY"
assert result["actions"][0]["comment"] == f"{SESSION_ID}_0"
assert result["actions"][0]["volume"] == 0.01
print("  ✓ Fresh Join: BUY row 0")

# ── 10. Trigger row 1 ──
heading(10, "Trigger row 1 (price drop $2)")
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2048.50,"bid":2048.10}, headers={"X-Admin-Key": ADMIN_KEY})
r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/grids",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
b1 = [g for g in r.json()["grids"] if g["grid_id"] == "B1"][0]
exec_count = sum(1 for row in b1["config"]["rows"] if row["executed"])
print(f"  Executed rows: {exec_count}")
assert exec_count == 2

# ── 11. SCENARIO 3: Catchup ──
heading(11, "SCENARIO 3: Catchup (client=1 row, grid=2)")
r = requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5000.0,
    "positions":[
        {"ticket":1001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.50,"profit":-2.0,"comment":f"{SESSION_ID}_0"}
    ]})
result = r.json()
pp(result)
assert result["actions"][0]["action"] == "BUY"
assert result["actions"][0]["comment"] == f"{SESSION_ID}_1"
assert result["actions"][0]["volume"] == 0.02
print("  ✓ Catchup: BUY row 1")

# ── 12. SCENARIO 6: In Sync ──
heading(12, "SCENARIO 6: In Sync (client=2, grid=2)")
r = requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5000.0,
    "positions":[
        {"ticket":1001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.50,"profit":-2.0,"comment":f"{SESSION_ID}_0"},
        {"ticket":1002,"symbol":"XAUUSD","type":"BUY","volume":0.02,
         "price":2048.50,"profit":-1.0,"comment":f"{SESSION_ID}_1"}
    ]})
result = r.json()
pp(result)
assert len(result["actions"]) == 0
print("  ✓ In Sync: No actions")

# ── 13. Trigger rows 2+3 ──
heading(13, "Trigger rows 2+3")
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2045.50,"bid":2045.10}, headers={"X-Admin-Key": ADMIN_KEY})
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2041.50,"bid":2041.10}, headers={"X-Admin-Key": ADMIN_KEY})
r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/grids",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
b1 = [g for g in r.json()["grids"] if g["grid_id"] == "B1"][0]
exec_count = sum(1 for row in b1["config"]["rows"] if row["executed"])
print(f"  Executed rows: {exec_count}")
assert exec_count == 4

# ── 14. SCENARIO 1: Late Join ──
heading(14, "Setup client 2 → Late Join")
CLIENT2_ID, _ = setup_client(ADMIN_TOKEN, "latejoin@test.com", "Late Joiner", "112233")
print(f"  Client2 ID={CLIENT2_ID}")
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"112233","balance":5000.0,"positions":[]})
result = r.json()
pp(result)
assert len(result["actions"]) == 0
print("  ✓ Late Join: Skip (wait for new session)")

# ── 15. SCENARIO 4: Session Mismatch ──
heading(15, "SCENARIO 4: Session Mismatch")
r = requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5000.0,
    "positions":[
        {"ticket":9001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.50,"profit":-2.0,"comment":"B1_deadbeef_0"},
        {"ticket":1001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.50,"profit":-2.0,"comment":f"{SESSION_ID}_0"},
        {"ticket":1002,"symbol":"XAUUSD","type":"BUY","volume":0.02,
         "price":2048.50,"profit":-1.0,"comment":f"{SESSION_ID}_1"}
    ]})
result = r.json()
pp(result)
close_actions = [a for a in result["actions"] if a["action"] == "CLOSE_ALL"]
trade_actions = [a for a in result["actions"] if a["action"] in ("BUY","SELL")]
assert len(close_actions) == 1 and close_actions[0]["comment"] == "B1_deadbeef"
assert len(trade_actions) == 1 and trade_actions[0]["comment"] == f"{SESSION_ID}_2"
print("  ✓ CLOSE_ALL stale + BUY catchup")

# ── 16. SCENARIO 5: Grid OFF Orphans ──
heading(16, "SCENARIO 5: Grid OFF Orphans")
requests.post(f"{BASE}/api/admin/tiers/{TIER_ID}/grids/B1/control",
    json={"on":False}, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
r = requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5000.0,
    "positions":[
        {"ticket":1001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.50,"profit":-2.0,"comment":f"{SESSION_ID}_0"},
        {"ticket":1002,"symbol":"XAUUSD","type":"BUY","volume":0.02,
         "price":2048.50,"profit":-1.0,"comment":f"{SESSION_ID}_1"}
    ]})
result = r.json()
pp(result)
close_actions = [a for a in result["actions"] if a["action"] == "CLOSE_ALL"]
assert len(close_actions) == 1 and close_actions[0]["comment"] == SESSION_ID
print(f"  ✓ CLOSE_ALL for {SESSION_ID}")

# ── 17. Client Dashboard ──
heading(17, "Client Dashboard")
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2060.50,"bid":2060.10}, headers={"X-Admin-Key": ADMIN_KEY})
requests.post(f"{BASE}/api/admin/tiers/{TIER_ID}/grids/B1/control",
    json={"on":True}, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
requests.post(f"{BASE}/api/master-tick",
    json={"ask":2060.50,"bid":2060.10}, headers={"X-Admin-Key": ADMIN_KEY})

r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/grids",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
b1 = [g for g in r.json()["grids"] if g["grid_id"] == "B1"][0]
NEW_SID = b1["runtime"]["session_id"]
print(f"  New session: {NEW_SID}")

requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5200.0,
    "positions":[
        {"ticket":2001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2060.50,"profit":-5.0,"comment":f"{NEW_SID}_0"}
    ]})

r = requests.get(f"{BASE}/api/client/dashboard",
    headers={"Authorization":f"Bearer {CLIENT1_TOKEN}"})
result = r.json()
pp(result)
assert result["tier"] is not None
assert result["account"]["balance"] is not None
assert "B1" in result["grids"]
assert result["grids"]["B1"]["rows"][0]["my_ticket"] == 2001
print(f"  ✓ Dashboard: tier={result['tier']['name']}, balance={result['account']['balance']}")

# ── 18. Admin: Tier clients ──
heading(18, "Admin: Tier clients list")
r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/clients",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
result = r.json()
pp(result)
assert len(result["clients"]) >= 2
print(f"  ✓ {len(result['clients'])} client(s)")

# ── 19. Admin: Client positions ──
heading(19, "Admin: Client positions")
r = requests.get(f"{BASE}/api/admin/tiers/{TIER_ID}/clients/{CLIENT1_ID}/positions",
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
result = r.json()
pp(result)
assert "grids" in result
print("  ✓ Positions retrieved")

# ── 20. Balance outside ranges ──
heading(20, "Balance outside ranges")
CLIENT3_ID, _ = setup_client(ADMIN_TOKEN, "oor@test.com", "OOR User", "999000")
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"999000","balance":100.0,"positions":[]})
result = r.json()
pp(result)
assert result["status"] == "no_tier"
print("  ✓ no_tier")

# ── 21. Banned user ──
heading(21, "Banned user")
requests.put(f"{BASE}/api/admin/users/{CLIENT3_ID}",
    json={"status":"banned"}, headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"999000","balance":100.0,"positions":[]})
result = r.json()
pp(result)
assert result["status"] == "banned"
print("  ✓ Banned")

# ── 22. Expired subscription ──
heading(22, "Expired subscription")
CLIENT4_ID, _ = setup_client(ADMIN_TOKEN, "expired@test.com", "Expired User", "555666")
requests.put(f"{BASE}/api/admin/users/{CLIENT4_ID}/subscription",
    json={"plan_name":"monthly","end_date":"2024-01-01T00:00:00"},
    headers={"Authorization":f"Bearer {ADMIN_TOKEN}"})
r = requests.post(f"{BASE}/api/client-ping",
    json={"mt5_id":"555666","balance":5000.0,"positions":[]})
result = r.json()
pp(result)
assert result["status"] == "expired"
print("  ✓ Expired")

# ── 23. Unknown comments ignored ──
heading(23, "Unknown comments ignored (Section 14.4)")
r = requests.post(f"{BASE}/api/client-ping", json={
    "mt5_id":"883921","balance":5200.0,
    "positions":[
        {"ticket":3001,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2050.0,"profit":0,"comment":"random_garbage"},
        {"ticket":3002,"symbol":"XAUUSD","type":"BUY","volume":0.01,
         "price":2060.50,"profit":-5.0,"comment":f"{NEW_SID}_0"}
    ]})
result = r.json()
pp(result)
assert result["status"] == "ok"
print("  ✓ Unknown comments ignored")

# ── 24. Health check ──
heading(24, "Health check")
r = requests.get(f"{BASE}/health")
pp(r.json())
assert r.json()["status"] == "ok"

print()
print("═" * 60)
print("  ALL PHASE 3 TESTS PASSED ✓")
print("═" * 60)
```

---

## 5. Test Results

### Test Matrix

| # | Test | Endpoint | Blueprint | Result |
|---|---|---|---|---|
| 1 | Admin login | POST /api/auth/login | 10.1 | ✅ |
| 2 | Get tier | GET /api/admin/tiers | 11.4 | ✅ |
| 3 | Reset grids OFF | POST /grids/{id}/control | 6.4 | ✅ |
| 4 | Setup client | register→verify→login→sub→mt5 | 10, 11.5 | ✅ |
| 5 | Unknown mt5_id | POST /api/client-ping | 8.2 | ✅ |
| 6 | First ping (tier assign) | POST /api/client-ping | 8.3 | ✅ |
| 7 | Configure B1 grid | PUT /grids/B1/config | 11.4 | ✅ |
| 8 | Activate B1 | tick + control ON | 6.3 | ✅ |
| 9 | **Scenario 2: Fresh Join** | POST /api/client-ping | 8.4 | ✅ |
| 10 | Trigger row 1 | POST /api/master-tick | 7.1 | ✅ |
| 11 | **Scenario 3: Catchup** | POST /api/client-ping | 8.4 | ✅ |
| 12 | **Scenario 6: In Sync** | POST /api/client-ping | 8.4 | ✅ |
| 13 | Trigger rows 2+3 | POST /api/master-tick | 7.1 | ✅ |
| 14 | **Scenario 1: Late Join** | POST /api/client-ping | 8.4 | ✅ |
| 15 | **Scenario 4: Session Mismatch** | POST /api/client-ping | 8.4 | ✅ |
| 16 | **Scenario 5: Grid OFF Orphans** | POST /api/client-ping | 8.4 | ✅ |
| 17 | Client dashboard | GET /api/client/dashboard | 11.5, 13 | ✅ |
| 18 | Admin: tier clients | GET /admin/tiers/{id}/clients | 11.4 | ✅ |
| 19 | Admin: client positions | GET /admin/.../positions | 11.4 | ✅ |
| 20 | Balance outside ranges | POST /api/client-ping | 14.2 | ✅ |
| 21 | Banned user | POST /api/client-ping | 8.2 | ✅ |
| 22 | Expired subscription | POST /api/client-ping | 14.9 | ✅ |
| 23 | Unknown comments ignored | POST /api/client-ping | 14.4 | ✅ |
| 24 | Health check | GET /health | — | ✅ |

**All 24 tests pass.** All 6 sync scenarios verified. Edge cases covered.

---

## 6. Manual Testing

### Quick Sync Test

```bash
# 1. Register + verify + login
REG=$(curl -s -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"pass123","name":"Tester"}')
VTOKEN=$(echo $REG | python3 -c "import sys,json; print(json.load(sys.stdin)['verification_token'])")
curl -s -X POST http://localhost:8000/api/auth/verify-email \
  -H "Content-Type: application/json" -d "{\"token\":\"$VTOKEN\"}"

LOGIN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"pass123"}')
TOKEN=$(echo $LOGIN | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
USER_ID=$(echo $LOGIN | python3 -c "import sys,json; print(json.load(sys.stdin)['user']['id'])")

# 2. Set MT5 ID
curl -s -X PATCH http://localhost:8000/api/client/meta-id \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"mt5_id":"123456"}'

# 3. Create subscription (admin)
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@elasticdca.com","password":"admin123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s -X PUT "http://localhost:8000/api/admin/users/$USER_ID/subscription" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan_name":"monthly","end_date":"2027-12-31T23:59:59"}'

# 4. Client ping
curl -s -X POST http://localhost:8000/api/client-ping \
  -H "Content-Type: application/json" \
  -d '{"mt5_id":"123456","balance":5000.0,"positions":[]}' \
  | python3 -m json.tool
```

### Check Dashboard

```bash
curl -s http://localhost:8000/api/client/dashboard \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| "Unknown account" | No user has that mt5_id | Register + verify + login + set mt5_id first |
| "Subscription expired" | No subscription or expired | Create via admin PUT endpoint |
| "no_tier" | Balance outside tier ranges | Check tier min/max vs client balance |
| Row 0 entry_price wrong | Market price from previous tick | Send a tick BEFORE turning grid ON |
| "Email already registered" | User exists from previous run | Clean DB: `DELETE FROM users` |
| 500 on positions endpoint | Missing market data | Send at least one tick first |
