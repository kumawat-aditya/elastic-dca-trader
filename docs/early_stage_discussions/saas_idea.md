Here is the **God-Level SaaS Specification** for converting Elastic DCA Trader into a full SaaS platform:

---

## Plan: Elastic DCA Trader — SaaS Platform Specification

**TL;DR:** Convert the current single-user, open-API algorithmic trading tool into a multi-tenant SaaS with user accounts, subscription tiers, payment processing, a marketing/pricing website, single-script enforcement per user via MT5 Meta ID binding, and an admin control panel — all while keeping the core DCA engine logic intact.

---

# ELASTIC DCA TRADER — SAAS PLATFORM SPEC

---

## 1. What This Platform Is

A subscription-based SaaS that lets retail traders connect their MetaTrader 5 terminal to a cloud-hosted Elastic DCA trading engine. The trader installs the provided `.mq5` EA on one chart, configures it with their personal API key, and the cloud engine handles all logic. The dashboard gives real-time visibility and control. Subscriptions gate access with hard enforcement on the server side.

---

## 2. Feature Inventory

### 2.1 Authentication & Identity
| Feature | Description |
|---|---|
| Email/Password Registration | Standard signup with unique email requirement |
| Email Verification | Verification link sent on signup; unverified users can browse but not use trading features |
| Login / Logout | JWT access token (15 min) + refresh token (7-30 days, httpOnly cookie) |
| Forgot Password | Sends time-limited reset link to registered email |
| Password Reset | Token-validated form to set new password |
| Session Management | View active sessions, revoke individual sessions |
| Role System | `user`, `admin` roles stored on user record |
| Optional: Google OAuth | One-click sign-in; links accounts by email |
| 2FA (Post-MVP) | TOTP-based (Google Authenticator compatible) |

### 2.2 Subscription & Billing
| Feature | Description |
|---|---|
| Plan Tiers | At least: Free Trial, Monthly, Quarterly, Annual |
| Stripe Integration | Checkout sessions, subscription lifecycle, customer portal |
| Free Trial | N-day trial with full access; auto-expires, no card required OR card required with auto-charge |
| Plan Upgrade/Downgrade | Prorated via Stripe, effective immediately |
| Subscription Cancellation | Cancel at period end (access until end_date) or immediately |
| Grace Period | If payment fails, configurable N-day grace period before access revoked |
| Invoice History | View all invoices with PDF download links (from Stripe) |
| Payment Method Management | Update card, view last 4 digits — delegated to Stripe Customer Portal |
| Webhook Handler | Handles Stripe events: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `customer.subscription.updated` |
| Trial-to-Paid Conversion Emails | Automated reminders at 3 days before trial end |

### 2.3 Meta ID (MT5 Account) Binding System
This is the **core enforcement mechanism** replacing the current zero-auth model.
| Feature | Description |
|---|---|
| Meta ID Registration | User submits their MT5 numeric account ID from MT4/5 terminal. Stored server-side. |
| Unique Binding | One MT5 account ID can be bound to exactly one platform user account. No sharing. |
| Single-Script Lock | Per-user Redis key: `ea_lock:{user_id}`. When EA sends first tick, lock is acquired with 15-second TTL, refreshed every tick. Second EA connection for same user gets `403 CONFLICT` response. |
| Meta ID Change | User can update Meta ID only if no active EA session (lock is free). Old binding is archived. |
| Meta ID Verification | When EA sends first tick, `tick.account_id` must match `user.meta_account_id`. Mismatch → `403 FORBIDDEN`. |
| Credential Delivery | After binding, server shows user their personal EA Server URL (`https://api.domain.com/ea/USER_API_KEY`) which they enter in MT5 `InpServerURL`. No email. Shown once, copyable. |

### 2.4 Multi-Tenant Trading Engine
| Feature | Description |
|---|---|
| Per-User Engine Instance | `EngineManager` class: `dict[user_id → DcaEngine]`. Engines are created on first authenticated EA tick and destroyed on subscription expiry. |
| Engine State Persistence | Engine's `GridSettings`, `GridState` serialized to PostgreSQL `engine_states` table every tick. Server restart restores all active users' states. |
| Per-User Presets | Presets table gains `user_id` FK. Users cannot see or load other users' presets. |
| Per-User WebSocket Room | WebSocket connections are authenticated (JWT or API key). Each connection is keyed to `user_id`. `SystemState` broadcasts only to that user's sockets. |
| Subscription Enforcement | Before processing any tick, check `user.subscription_status` in Redis cache (5-second TTL). Expired → `403 FORBIDDEN`, engine is suspended. |
| Symbol Multi-Instance (Post-MVP) | Future: allow multiple MetaId/symbol pairs per account on higher-tier plans. |

### 2.5 API Key System
| Feature | Description |
|---|---|
| Auto-Generated on Signup | `user_api_key`: `edca_live_{uuid4_hex}` — 40+ char random key |
| EA-Facing Endpoint | `POST /ea/{api_key}/tick` — key is in URL path, not header (because MQL5 `InpServerURL` param is the only injection point) |
| Key Rotation | User can regenerate key from account settings; old key immediately invalidated. Warning shown that EA config must be updated. |
| Key Visibility | Masked display (`edca_live_****...****xyz`); full key revealed behind password confirmation or "Click to reveal" with audit log entry. |

### 2.6 Real-Time Trading Dashboard
Enhanced version of the existing React app:
| Feature | Description |
|---|---|
| All existing dashboard features | Grid tables, controls, presets, TP/SL, etc. — unchanged |
| EA Connection Status | Shows `connected` / `disconnected` + last ping time |
| Subscription Status Badge | Prominently shows plan name, days remaining, renewal date |
| Meta ID Status | Shows registered Meta ID + lock status (active / free) |
| Quick Stats | Today's P&L, open positions count, total equity delta |
| Persistent State on Reconnect | Engine state restored from DB if browser was closed; no state loss |
| Alert History | Last N triggered row alerts stored and viewable |

### 2.7 Account Management Pages
| Feature | Description |
|---|---|
| Profile | Name, email, timezone, profile picture |
| Security | Change password, active sessions list, revoke sessions |
| Meta Account | Register / update MT5 account ID, view EA download + configuration instructions |
| API Key | View/reveal/rotate personal API key |
| Subscription | Current plan, billing cycle, usage, upgrade/downgrade CTA, cancel |
| Billing & Invoices | Invoice table with amount, date, status, PDF link (Stripe data) |

### 2.8 Marketing & Landing Site
| Feature | Description |
|---|---|
| Landing Page | Hero, features overview, social proof, CTA |
| Pricing Page | Plan comparison table, FAQ, toggle monthly/annual |
| Features Page | Deep-dive on DCA engine, grid trading explanation |
| Documentation | Setup guide, EA configuration, troubleshooting, API ref |
| Blog (Post-MVP) | Content marketing for SEO |
| About / Contact | Team, support form or Discord link |
| Legal Pages | Terms of Service, Privacy Policy, Cookie Policy |

### 2.9 Admin Panel
| Feature | Description |
|---|---|
| Overview Dashboard | DAU, MRR, active subscriptions, churn, new signups chart |
| User Management | Search, view profile, change role, suspend/unsuspend, impersonate |
| Subscription Management | View by user, manually extend, grant free access, refund trigger |
| Plan Configuration | Create/edit/deactivate plans, set prices and feature flags |
| Platform Health | EA connections count, engine instances running, Redis status, DB health |
| Audit Log | Log of all admin actions |

### 2.10 Notification System
| Feature | Description |
|---|---|
| Transactional Emails | Verify email, welcome, password reset, trial expiry warning, payment failed, subscription cancelled, payment receipt |
| In-App Toasts | Enhanced version of existing toast system — subscription warnings, connection events |
| Webhook Alerts (Post-MVP) | User-configurable Discord/Slack webhook for TP/SL hit events |

---

## 3. Pages Inventory

### Marketing Site (Next.js — server-rendered for SEO)
| Route | Page | Purpose |
|---|---|---|
| `/` | Landing | Hero section, features overview, testimonials, pricing teaser, CTAs |
| `/pricing` | Pricing | Plan cards, monthly/annual toggle, feature comparison table, FAQ |
| `/features` | Features | Detailed DCA explanation, grid visualization, use cases |
| docs | Documentation Index | Links to setup guide, configuration, troubleshooting |
| `/docs/getting-started` | Getting Started | Step-by-step: subscribe → configure EA → connect |
| `/docs/ea-setup` | EA Setup Guide | Download link, MT5 configuration, `InpServerURL` setup |
| `/docs/dashboard` | Dashboard Guide | Controls, settings, presets explained |
| `/about` | About | Mission statement, contact info |
| `/contact` | Contact | Support form (or redirect to Discord) |
| `/legal/terms` | Terms of Service | Full ToS |
| `/legal/privacy` | Privacy Policy | GDPR-compliant privacy policy |
| `/legal/cookies` | Cookie Policy | Cookie usage disclosure |
| `/blog` | Blog Index | *(Post-MVP)* Article listing |

### Auth Pages (React App or shared Next.js)
| Route | Page | Purpose |
|---|---|---|
| `/register` | Sign Up | Email, password, name; CTA to pricing before this |
| `/login` | Sign In | Email + password; "Forgot password" link |
| `/verify-email` | Email Verification | Sends link; shows "check your inbox" state; resend button |
| `/verify-email/:token` | Verification Handler | Validates token, redirects to `/dashboard` or shows error |
| `/forgot-password` | Forgot Password | Email input → sends reset link |
| `/reset-password/:token` | Reset Password | New password form; validates token expiry |

### App — Trading Dashboard (React SPA)
| Route | Page | Purpose |
|---|---|---|
| `/dashboard` | Main Dashboard | Full trading dashboard (enhanced existing) |
| `/dashboard/alerts` | Alert History | Historical log of triggered row alerts |

### App — Account Management
| Route | Page | Purpose |
|---|---|---|
| `/account` | Account Overview | Quick summary: plan, meta ID status, API key status |
| `/account/profile` | Profile Settings | Name, email, timezone |
| `/account/security` | Security | Password change, active sessions, revoke session buttons |
| `/account/meta-account` | MT5 Account | Register/view/update Meta ID; EA setup instructions; force-unlock button |
| `/account/api-key` | API Key | View masked key, reveal button, rotate button, usage snippet |
| `/account/subscription` | Subscription | Current plan card, upgrade/downgrade, cancel flow |
| `/account/billing` | Billing & Invoices | Invoice history table, update payment method link |

### Checkout Flow
| Route | Page | Purpose |
|---|---|---|
| `/checkout` | Plan Selection | Plan cards with "Subscribe" CTA; redirects to Stripe Checkout |
| `/checkout/success` | Success | Post-payment confirmation; next-step CTA (set up Meta ID) |
| `/checkout/cancel` | Cancelled | Returns user to pricing; optionally shows a discount offer |

### Admin Panel (protected by `admin` role)
| Route | Page | Purpose |
|---|---|---|
| `/admin` | Overview | MRR chart, active users, new signups, churn gauge |
| `/admin/users` | User List | Searchable table: email, plan, status, joined date; row actions |
| `/admin/users/:id` | User Detail | Full user profile, subscription history, EA activity, impersonate |
| `/admin/subscriptions` | Subscription List | All subs: active, trialing, past_due, cancelled |
| `/admin/plans` | Plan Manager | CRUD for subscription plans and feature flags |
| `/admin/health` | Platform Health | Live: engine count, EA connections, Redis, DB, Celery (if used) |
| `/admin/audit` | Audit Log | Admin action log |

---

## 4. Technical Architecture

### 4.1 Repository Structure (Monorepo)
```
elastic-dca-saas/
├── apps/
│   ├── server/          # FastAPI — trading API + auth + billing
│   ├── web/             # React SPA — dashboard + account pages
│   └── marketing/       # Next.js — landing site (NEW)
├── packages/
│   └── shared-types/    # TypeScript interfaces shared between web/ and marketing/
├── scripts/
│   └── automation.mq5   # Updated MQL5 EA
├── infra/
│   ├── docker/          # Dockerfiles per service
│   ├── nginx/           # Reverse proxy config
│   └── aws/             # IaC (CDK or Terraform)
├── docs/
└── .env.example
```

### 4.2 Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Trading API | FastAPI (Python 3.12) | Keep existing; minimal disruption |
| Auth | `python-jose` (JWT) + `passlib[bcrypt]` | Industry standard |
| ORM | SQLAlchemy 2.x + Alembic | Keep existing; add migrations |
| Database | PostgreSQL 16 | Replace SQLite; production-grade, multi-tenant safe |
| Cache / Locks | Redis 7 | EA single-script lock, subscription status cache, refresh token store |
| Task Queue | Celery + Redis broker | Async email sending, scheduled subscription checks |
| Payment | Stripe (Python SDK) | Industry standard; handles PCI compliance |
| Email | Resend or SendGrid | Transactional emails |
| Marketing Site | Next.js 14 (App Router) | SSR for SEO |
| Dashboard | React 18 + Vite | Keep existing; add routing |
| Router (web) | React Router v6 | Add route-based navigation |
| HTTP Client | TanStack Query + Axios | Replace raw `fetch`; caching + loading states |
| CSS | Tailwind CSS (if not already) | Keep or add; consistent styling across apps |
| Containerization | Docker + Docker Compose | Local dev + production parity |
| Reverse Proxy | Nginx | Route `/ea/*`, `/api/*`, `/` to correct services |
| CI/CD | GitHub Actions | Test + build + deploy pipeline |
| Monitoring | Sentry (errors) + Prometheus/Grafana (metrics) | Production observability |

### 4.3 Domain Architecture

```
yourdomain.com          → Next.js marketing site
app.yourdomain.com      → React SPA (dashboard + account)
api.yourdomain.com      → FastAPI backend
```

All under Nginx or a cloud load balancer. EA `InpServerURL` is set to `https://api.yourdomain.com/ea/{user_api_key}`.

---

## 5. Database Schema

### 5.1 `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR unique | |
| `password_hash` | VARCHAR | bcrypt |
| `name` | VARCHAR | |
| `role` | ENUM `user/admin` | default `user` |
| `email_verified` | BOOLEAN | default false |
| `api_key` | VARCHAR unique | `edca_live_{hex}` |
| `is_active` | BOOLEAN | false = suspended |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.2 `meta_accounts`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK users | |
| `mt5_account_id` | BIGINT unique | The numeric MT5 account ID |
| `broker_name` | VARCHAR | Captured from EA on first tick |
| `is_active` | BOOLEAN | Only one active per user |
| `created_at` | TIMESTAMP | |

### 5.3 `email_verifications`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 24h |
| `used` | BOOLEAN | |

### 5.4 `password_reset_tokens`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 1h |
| `used` | BOOLEAN | |

### 5.5 `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `token_hash` | VARCHAR | SHA-256 of actual token |
| `expires_at` | TIMESTAMP | |
| `revoked` | BOOLEAN | |
| `user_agent` | VARCHAR | For session list display |
| `ip_address` | VARCHAR | |

### 5.6 `plans`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR | e.g., "Monthly", "Annual" |
| `slug` | VARCHAR unique | e.g., `monthly`, `annual` |
| `price_monthly_cents` | INTEGER | in cents |
| `stripe_price_id_monthly` | VARCHAR | |
| `stripe_price_id_annual` | VARCHAR | |
| `trial_days` | INTEGER | 0 = no trial |
| `features` | JSONB | Feature flags for plan gating |
| `is_active` | BOOLEAN | |

### 5.7 `subscriptions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `plan_id` | UUID FK | |
| `stripe_subscription_id` | VARCHAR unique | |
| `stripe_customer_id` | VARCHAR | |
| `status` | ENUM | `trialing / active / past_due / cancelled / expired` |
| `current_period_start` | TIMESTAMP | |
| `current_period_end` | TIMESTAMP | Access granted until this time even if cancelled |
| `cancel_at_period_end` | BOOLEAN | |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.8 `engine_states`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK unique | One row per user |
| `buy_settings` | JSONB | Serialized `GridSettings` |
| `sell_settings` | JSONB | Serialized `GridSettings` |
| `buy_state` | JSONB | Serialized `GridState` |
| `sell_state` | JSONB | Serialized `GridState` |
| `updated_at` | TIMESTAMP | |

### 5.9 `presets` (modified from existing)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Changed from INTEGER |
| `user_id` | UUID FK | **NEW** — scoped to user |
| `name` | VARCHAR | Unique per user (not globally) |
| `rows_json` | TEXT | Existing JSON serialization |

### 5.10 `audit_logs` (admin)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `admin_user_id` | UUID FK | |
| `action` | VARCHAR | e.g., `impersonate_user`, `grant_subscription` |
| `target_user_id` | UUID FK nullable | |
| `metadata` | JSONB | Extra context |
| `created_at` | TIMESTAMP | |

### Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `ea_lock:{user_id}` | 15s (refreshed each tick) | Single-script enforcement lock |
| `sub_status:{user_id}` | 5s | Subscription status cache |
| `refresh:{token_hash}` | 30d | Refresh token store (alternative to DB) |
| `rate_limit:ea:{user_id}` | 1s | EA tick rate limiting (max 5/sec) |
| `rate_limit:api:{ip}` | 60s | Public API rate limiting |

---

## 6. API Design Changes

### 6.1 EA Endpoint (Critical Change)

**Before:** `POST /api/v1/ea/tick`  
**After:** `POST /ea/{api_key}/tick`

The API key is embedded in the URL path because `InpServerURL` in the MT5 EA is the only injection point. The user sets their InpServerURL to `https://api.yourdomain.com/ea/edca_live_xxxx`. The server:
1. Extracts `api_key` from path
2. Resolves `user` from `api_key`
3. Verifies `tick.account_id == user.meta_account_id`
4. Acquires/refreshes `ea_lock:{user_id}` in Redis (15s TTL)
5. If lock already held by different connection token → `403 CONFLICT`
6. Routes tick to `engine_manager.get_or_create(user_id)`
7. Returns actions JSON

### 6.2 Dashboard WebSocket

**Before:** `WS /api/v1/ui/ws` (open to all)  
**After:** `WS /ws?token={jwt_access_token}` — authenticated at connection time

Server validates JWT, extracts `user_id`, adds socket to `user_rooms[user_id]`. State broadcasts go only to that user's sockets. Multiple browser tabs per user are allowed.

### 6.3 Auth Endpoints (New)
```
POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/refresh
POST /auth/verify-email/{token}
POST /auth/forgot-password
POST /auth/reset-password/{token}
GET  /auth/me
```

### 6.4 Subscription Endpoints (New)
```
GET  /billing/plans
POST /billing/checkout-session        # Creates Stripe Checkout → returns URL
GET  /billing/subscription            # Current user subscription
POST /billing/cancel
POST /billing/portal                  # Stripe Customer Portal URL
GET  /billing/invoices
POST /webhooks/stripe                 # Stripe event handler (public, signature-verified)
```

### 6.5 Account Endpoints (New)
```
GET  /account/me
PUT  /account/profile
POST /account/change-password
GET  /account/sessions
DELETE /account/sessions/{id}
GET  /account/meta-account
POST /account/meta-account
DELETE /account/meta-account/lock     # Force-release EA lock
POST /account/api-key/rotate
```

### 6.6 Existing UI Endpoints
All existing `/api/v1/ui/*` routes remain, protected by JWT middleware. `presets` endpoints add `user_id` filter automatically from JWT subject.

---

## 7. MQL5 EA Changes

The EA needs these input changes:
- `InpServerURL` — user sets to `https://api.yourdomain.com/ea/edca_live_xxx` (the API key is baked in)
- No other code changes needed — the API key routing is transparent to the EA

The EA download flow:
1. User subscribes → sets up Meta ID → server shows their personalized `InpServerURL`
2. User downloads `.mq5` file (same for all users)
3. User attaches to ONE chart, enters their personal `InpServerURL`
4. Server routes by API key; no other configuration needed

---

## 8. Multi-Tenancy Engine Design

### `EngineManager` (new file: `app/services/engine_manager.py`)
```python
class EngineManager:
    _instances: dict[str, DcaEngine]  # user_id → engine
    
    def get_or_create(user_id: str, db: Session) -> DcaEngine:
        # Load existing engine or restore from engine_states table
        
    def persist_state(user_id: str, db: Session):
        # Serialize engine.state → engine_states row
        
    def destroy(user_id: str):
        # Subscription expired / user deleted
```

`DcaEngine` is modified minimally:
- Remove singleton pattern (becomes a plain instantiable class)
- `__init__` accepts optional `saved_state` dict to restore from DB
- `session_id` in `GridState` is stored/restored — if EA was disconnected mid-session, grid state is fully restored

---

## 9. Security Hardening

| Concern | Solution |
|---|---|
| CORS | Lock to `app.yourdomain.com` and `yourdomain.com` only |
| JWT signing | RS256 asymmetric key pair; private key in env/secrets manager |
| Password storage | bcrypt with work factor 12 |
| EA API key | Treated as a bearer secret; always HTTPS; rotation available |
| Stripe webhooks | Verify `Stripe-Signature` header using endpoint secret |
| Rate limiting | Slowapi on auth routes (5/min login), EA tick (5/sec per user), public API |
| SQL injection | Parameterized queries via SQLAlchemy ORM only |
| XSS | React renders safely; CSP headers via Nginx |
| CSRF | SameSite=Strict on refresh token cookie; CSRF token on forms |
| Secrets | Never in source; `.env` for local, AWS Secrets Manager for production |
| Admin routes | Double-checked: JWT `role == admin` middleware + role check in every handler |
| Audit logging | All admin actions logged with actor, target, timestamp |

---

## 10. Infrastructure

### Docker Compose (Development)
```
services:
  api:         FastAPI on :8000
  web:         Vite dev server on :5173
  marketing:   Next.js dev server on :3000
  postgres:    PostgreSQL on :5432
  redis:       Redis on :6379
  worker:      Celery worker (emails, scheduled tasks)
```

### Production Architecture
```
Internet → Cloudflare (DDoS, CDN, SSL)
         → AWS ALB
         → ECS (Fargate) tasks:
              - api (FastAPI)     → auto-scales horizontally
              - worker (Celery)   → scales separately
         → RDS PostgreSQL (Multi-AZ)
         → ElastiCache Redis
         → S3 + CloudFront for marketing (Next.js static export or Vercel)
         → S3 + CloudFront for web app (React SPA build)
```

Alternatively (simpler/cheaper solo): single VPS (Hetzner/DO), Docker Compose in production, Nginx reverse proxy, managed PostgreSQL add-on, Upstash Redis.

---

## 11. Delivery Phases & Time Estimates (Solo Developer)

Assumes: ~6-8 hours/day focus time, existing familiarity with FastAPI and React.

### Phase 1 — Foundation (4–5 weeks)
| Task | Est. |
|---|---|
| Monorepo restructure, Docker Compose, PostgreSQL setup, Alembic | 3 days |
| User model, auth endpoints (register/login/verify/reset) | 4 days |
| JWT middleware, refresh token rotation | 2 days |
| Password reset email flow (Resend/SendGrid) | 2 days |
| Frontend: React Router setup, auth pages (login/register/forgot/reset) | 4 days |
| Auth guards, protected routes, token refresh interceptor | 3 days |
| Testing auth flow end-to-end | 2 days |
| **Milestone:** Logged-in user, email verification working | |

### Phase 2 — Multi-Tenant Engine (5–7 weeks)
| Task | Est. |
|---|---|
| `EngineManager` class, remove DcaEngine singleton | 3 days |
| `engine_states` table + persist/restore logic | 3 days |
| EA endpoint refactor: API key routing, meta_id binding | 3 days |
| Redis single-script lock system | 2 days |
| Meta account registration UI + force-unlock feature | 2 days |
| WebSocket authentication + per-user rooms | 3 days |
| Subscription enforcement middleware (Redis cache check) | 2 days |
| Presets — add `user_id` scope | 1 day |
| Integration testing all engine paths | 4 days |
| **Milestone:** Two users can run in parallel with full isolation | |

### Phase 3 — Subscriptions & Billing (4–5 weeks)
| Task | Est. |
|---|---|
| Stripe account setup, products/prices created in Stripe dashboard | 1 day |
| Plans table, `subscriptions` table, Stripe customer creation | 2 days |
| Stripe Checkout session endpoint | 2 days |
| Webhook handler: all critical Stripe events | 3 days |
| Stripe Customer Portal integration (billing management) | 1 day |
| Subscription status enforcement on all protected endpoints | 2 days |
| Trial period logic + pre-expiry reminder emails (Celery task) | 2 days |
| Frontend: pricing page, checkout flow, subscription/billing pages | 5 days |
| **Milestone:** Full end-to-end subscribe → trade → cancel flow | |

### Phase 4 — Marketing Site (3–4 weeks)
| Task | Est. |
|---|---|
| Next.js project setup, Tailwind, shared design system | 2 days |
| Landing page (hero, features, social proof, pricing teaser, CTA) | 4 days |
| Pricing page (plan cards, feature table, FAQ) | 2 days |
| Features page | 2 days |
| Documentation (getting started, EA setup, dashboard guide) | 4 days |
| About + Contact pages | 1 day |
| Legal pages (ToS, Privacy, Cookies) | 2 days |
| SEO metadata, sitemap, robots.txt | 1 day |
| **Milestone:** Public site live, converts visitors to signups | |

### Phase 5 — Admin Panel (3–4 weeks)
| Task | Est. |
|---|---|
| Admin role middleware | 1 day |
| Admin overview dashboard (MRR, signups, churn) | 3 days |
| User list + search + detail + suspend/unsuspend | 3 days |
| Subscription management + manual grant/extend | 2 days |
| Platform health page | 2 days |
| Audit log | 2 days |
| **Milestone:** Admin can manage all users and subscriptions | |

### Phase 6 — Hardening & Launch (3–4 weeks)
| Task | Est. |
|---|---|
| Security audit: CORS, headers, rate limiting, input validation | 3 days |
| Error handling: user-facing error pages, Sentry integration | 2 days |
| Load testing EA tick endpoint | 1 day |
| CI/CD pipeline (GitHub Actions: test + build + deploy) | 2 days |
| Production infrastructure setup (VPS or AWS) | 3 days |
| HTTPS, certificates (Let's Encrypt or ACM) | 1 day |
| Backup strategy (DB daily snapshots) | 1 day |
| Smoke testing all user journeys in production | 2 days |
| **Milestone:** Platform live, accepting paying customers | |

### Total Solo Estimate
| Phase | Min | Max |
|---|---|---|
| Phase 1: Foundation | 4 weeks | 5 weeks |
| Phase 2: Multi-Tenant Engine | 5 weeks | 7 weeks |
| Phase 3: Billing | 4 weeks | 5 weeks |
| Phase 4: Marketing | 3 weeks | 4 weeks |
| Phase 5: Admin Panel | 3 weeks | 4 weeks |
| Phase 6: Hardening & Launch | 3 weeks | 4 weeks |
| **Total** | **22 weeks** | **29 weeks** |

> **Realistic solo timeline: 5.5–7 months** with focused daily work.  
> Buffer for real life, debugging unknown unknowns, and iteration: add 20–30%.

---

## 12. Complexity Assessment

### By Component

| Component | Complexity | Notes |
|---|---|---|
| Auth system | Medium | Well-understood patterns; libraries do heavy lifting |
| JWT + refresh rotation | Medium | fiddly but documented |
| Stripe integration | Medium–High | Webhook state machine has many edge cases |
| Multi-tenant engine | **High** | Biggest architectural lift; singleton → per-user factory |
| EA single-script lock | Medium | Redis TTL + refresh; logic is clear but must be bulletproof |
| State persistence | Medium | Serialize/restore engine state; risk: version mismatches |
| WebSocket auth + rooms | Medium | JWT at upgrade handshake; room management |
| Marketing site (Next.js) | Low–Medium | Standard Next.js; main work is design/content |
| Admin panel | Medium | CRUD + charts; no novel logic |
| Production infra | Medium | Standard containerized deployment |
| MQL5 EA changes | **Low** | Only URL change needed — no logic changes |

### Biggest Technical Risks

1. **Engine state serialization**: If `GridSettings`/`GridState` schema changes, stored JSON may be incompatible. Mitigation: version field on stored JSON + migration scripts.
2. **EA lock edge cases**: MT5 crash leaves lock held for 15 seconds. Mitigation: force-unlock UI, tune TTL, clear lock on confirmed EA disconnect.
3. **Stripe webhook delivery**: Must be idempotent — same webhook may arrive twice. Mitigation: store `stripe_event_id`, skip if already processed.
4. **Single-server bottleneck on engine**: If engine processing blocks async loop, all users suffer. Mitigation: run engine evaluation in `asyncio.run_in_executor` or separate threads per user.
5. **Meta ID uniqueness enforcement**: Race condition if two accounts try to register same Meta ID simultaneously. Mitigation: DB unique constraint + optimistic locking.

---

## 13. What Can Be Parallelized / Deferred

### Parallelize
- Marketing site can be built while Phase 2 engine work is in progress
- Admin panel UI can be partially scaffolded during Phase 2

### Defer to Post-MVP (v2)
| Feature | Why Defer |
|---|---|
| Google OAuth | JWT auth alone is sufficient for launch |
| 2FA | Adds significant complexity; not critical |
| Discord/Slack webhooks | Nice-to-have; not core |
| Blog | Content work; no impact on core SaaS |
| Symbol multi-instance per user | Major engine change; wait for demand signal |
| Mobile app | Desktop trading tool; mobile not needed at launch |
| Advanced analytics for users | Feature, not critical path |

---

## 14. Deliverables Summary

At platform launch, the user receives:

1. **A running marketing website** with landing, pricing, docs, legal
2. **A working auth system** with email verification and sessions
3. **A subscription system** backed by Stripe with at least 2 plans (monthly + annual)
4. **A Meta ID binding system** that prevents multi-script abuse
5. **A fully isolated, per-user trading engine** — each subscriber gets their own DCA engine instance with persistent state
6. **An enhanced trading dashboard** with subscription status and Meta ID management
7. **A personal API key** per user; EA points to `api.domain.com/ea/{api_key}`
8. **An admin panel** to manage users, subscriptions, and platform health
9. **Transactional emails** for all critical lifecycle events
10. **A production-ready deployment** with HTTPS, monitoring, and backups

---

*Spec version: 1.0 | Status: Planning | Last updated: 2026-04-04*
</parameter>
<parameter name="path">/memories/session/plan.md</parameter>
</invoke>etaTrader 5 terminal to a cloud-hosted Elastic DCA trading engine. The trader installs the provided `.mq5` EA on one chart, configures it with their personal API key, and the cloud engine handles all logic. The dashboard gives real-time visibility and control. Subscriptions gate access with hard enforcement on the server side.

---

## 2. Feature Inventory

### 2.1 Authentication & Identity
| Feature | Description |
|---|---|
| Email/Password Registration | Standard signup with unique email requirement |
| Email Verification | Verification link sent on signup; unverified users can browse but not use trading features |
| Login / Logout | JWT access token (15 min) + refresh token (7-30 days, httpOnly cookie) |
| Forgot Password | Sends time-limited reset link to registered email |
| Password Reset | Token-validated form to set new password |
| Session Management | View active sessions, revoke individual sessions |
| Role System | `user`, `admin` roles stored on user record |
| Optional: Google OAuth | One-click sign-in; links accounts by email |
| 2FA (Post-MVP) | TOTP-based (Google Authenticator compatible) |

### 2.2 Subscription & Billing
| Feature | Description |
|---|---|
| Plan Tiers | At least: Free Trial, Monthly, Quarterly, Annual |
| Stripe Integration | Checkout sessions, subscription lifecycle, customer portal |
| Free Trial | N-day trial with full access; auto-expires, no card required OR card required with auto-charge |
| Plan Upgrade/Downgrade | Prorated via Stripe, effective immediately |
| Subscription Cancellation | Cancel at period end (access until end_date) or immediately |
| Grace Period | If payment fails, configurable N-day grace period before access revoked |
| Invoice History | View all invoices with PDF download links (from Stripe) |
| Payment Method Management | Update card, view last 4 digits — delegated to Stripe Customer Portal |
| Webhook Handler | Handles Stripe events: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `customer.subscription.updated` |
| Trial-to-Paid Conversion Emails | Automated reminders at 3 days before trial end |

### 2.3 Meta ID (MT5 Account) Binding System
This is the **core enforcement mechanism** replacing the current zero-auth model.
| Feature | Description |
|---|---|
| Meta ID Registration | User submits their MT5 numeric account ID from MT4/5 terminal. Stored server-side. |
| Unique Binding | One MT5 account ID can be bound to exactly one platform user account. No sharing. |
| Single-Script Lock | Per-user Redis key: `ea_lock:{user_id}`. When EA sends first tick, lock is acquired with 15-second TTL, refreshed every tick. Second EA connection for same user gets `403 CONFLICT` response. |
| Lock Override | User can force-release the lock from the dashboard ("Emergency Disconnect") to recover from a crashed MT5 without waiting for TTL expiry. |
| Meta ID Change | User can update Meta ID only if no active EA session (lock is free). Old binding is archived. |
| Meta ID Verification | When EA sends first tick, `tick.account_id` must match `user.meta_account_id`. Mismatch → `403 FORBIDDEN`. |
| Credential Delivery | After binding, server shows user their personal EA Server URL (`https://api.domain.com/ea/USER_API_KEY`) which they enter in MT5 `InpServerURL`. No email. Shown once, copyable. |

### 2.4 Multi-Tenant Trading Engine
| Feature | Description |
|---|---|
| Per-User Engine Instance | `EngineManager` class: `dict[user_id → DcaEngine]`. Engines are created on first authenticated EA tick and destroyed on subscription expiry. |
| Engine State Persistence | Engine's `GridSettings`, `GridState` serialized to PostgreSQL `engine_states` table every tick. Server restart restores all active users' states. |
| Per-User Presets | Presets table gains `user_id` FK. Users cannot see or load other users' presets. |
| Per-User WebSocket Room | WebSocket connections are authenticated (JWT or API key). Each connection is keyed to `user_id`. `SystemState` broadcasts only to that user's sockets. |
| Subscription Enforcement | Before processing any tick, check `user.subscription_status` in Redis cache (5-second TTL). Expired → `403 FORBIDDEN`, engine is suspended. |
| Symbol Multi-Instance (Post-MVP) | Future: allow multiple MetaId/symbol pairs per account on higher-tier plans. |

### 2.5 API Key System
| Feature | Description |
|---|---|
| Auto-Generated on Signup | `user_api_key`: `edca_live_{uuid4_hex}` — 40+ char random key |
| EA-Facing Endpoint | `POST /ea/{api_key}/tick` — key is in URL path, not header (because MQL5 `InpServerURL` param is the only injection point) |
| Key Rotation | User can regenerate key from account settings; old key immediately invalidated. Warning shown that EA config must be updated. |
| Key Visibility | Masked display (`edca_live_****...****xyz`); full key revealed behind password confirmation or "Click to reveal" with audit log entry. |

### 2.6 Real-Time Trading Dashboard
Enhanced version of the existing React app:
| Feature | Description |
|---|---|
| All existing dashboard features | Grid tables, controls, presets, TP/SL, etc. — unchanged |
| EA Connection Status | Shows `connected` / `disconnected` + last ping time |
| Subscription Status Badge | Prominently shows plan name, days remaining, renewal date |
| Meta ID Status | Shows registered Meta ID + lock status (active / free) |
| Quick Stats | Today's P&L, open positions count, total equity delta |
| Persistent State on Reconnect | Engine state restored from DB if browser was closed; no state loss |
| Alert History | Last N triggered row alerts stored and viewable |

### 2.7 Account Management Pages
| Feature | Description |
|---|---|
| Profile | Name, email, timezone, profile picture |
| Security | Change password, active sessions list, revoke sessions |
| Meta Account | Register / update MT5 account ID, view EA download + configuration instructions |
| API Key | View/reveal/rotate personal API key |
| Subscription | Current plan, billing cycle, usage, upgrade/downgrade CTA, cancel |
| Billing & Invoices | Invoice table with amount, date, status, PDF link (Stripe data) |

### 2.8 Marketing & Landing Site
| Feature | Description |
|---|---|
| Landing Page | Hero, features overview, social proof, CTA |
| Pricing Page | Plan comparison table, FAQ, toggle monthly/annual |
| Features Page | Deep-dive on DCA engine, grid trading explanation |
| Documentation | Setup guide, EA configuration, troubleshooting, API ref |
| Blog (Post-MVP) | Content marketing for SEO |
| About / Contact | Team, support form or Discord link |
| Legal Pages | Terms of Service, Privacy Policy, Cookie Policy |

### 2.9 Admin Panel
| Feature | Description |
|---|---|
| Overview Dashboard | DAU, MRR, active subscriptions, churn, new signups chart |
| User Management | Search, view profile, change role, suspend/unsuspend, impersonate |
| Subscription Management | View by user, manually extend, grant free access, refund trigger |
| Plan Configuration | Create/edit/deactivate plans, set prices and feature flags |
| Platform Health | EA connections count, engine instances running, Redis status, DB health |
| Audit Log | Log of all admin actions |

### 2.10 Notification System
| Feature | Description |
|---|---|
| Transactional Emails | Verify email, welcome, password reset, trial expiry warning, payment failed, subscription cancelled, payment receipt |
| In-App Toasts | Enhanced version of existing toast system — subscription warnings, connection events |
| Webhook Alerts (Post-MVP) | User-configurable Discord/Slack webhook for TP/SL hit events |

---

## 3. Pages Inventory

### Marketing Site (Next.js — server-rendered for SEO)
| Route | Page | Purpose |
|---|---|---|
| `/` | Landing | Hero section, features overview, testimonials, pricing teaser, CTAs |
| `/pricing` | Pricing | Plan cards, monthly/annual toggle, feature comparison table, FAQ |
| `/features` | Features | Detailed DCA explanation, grid visualization, use cases |
| docs | Documentation Index | Links to setup guide, configuration, troubleshooting |
| `/docs/getting-started` | Getting Started | Step-by-step: subscribe → configure EA → connect |
| `/docs/ea-setup` | EA Setup Guide | Download link, MT5 configuration, `InpServerURL` setup |
| `/docs/dashboard` | Dashboard Guide | Controls, settings, presets explained |
| `/about` | About | Mission statement, contact info |
| `/contact` | Contact | Support form (or redirect to Discord) |
| `/legal/terms` | Terms of Service | Full ToS |
| `/legal/privacy` | Privacy Policy | GDPR-compliant privacy policy |
| `/legal/cookies` | Cookie Policy | Cookie usage disclosure |
| `/blog` | Blog Index | *(Post-MVP)* Article listing |

### Auth Pages (React App or shared Next.js)
| Route | Page | Purpose |
|---|---|---|
| `/register` | Sign Up | Email, password, name; CTA to pricing before this |
| `/login` | Sign In | Email + password; "Forgot password" link |
| `/verify-email` | Email Verification | Sends link; shows "check your inbox" state; resend button |
| `/verify-email/:token` | Verification Handler | Validates token, redirects to `/dashboard` or shows error |
| `/forgot-password` | Forgot Password | Email input → sends reset link |
| `/reset-password/:token` | Reset Password | New password form; validates token expiry |

### App — Trading Dashboard (React SPA)
| Route | Page | Purpose |
|---|---|---|
| `/dashboard` | Main Dashboard | Full trading dashboard (enhanced existing) |
| `/dashboard/alerts` | Alert History | Historical log of triggered row alerts |

### App — Account Management
| Route | Page | Purpose |
|---|---|---|
| `/account` | Account Overview | Quick summary: plan, meta ID status, API key status |
| `/account/profile` | Profile Settings | Name, email, timezone |
| `/account/security` | Security | Password change, active sessions, revoke session buttons |
| `/account/meta-account` | MT5 Account | Register/view/update Meta ID; EA setup instructions; force-unlock button |
| `/account/api-key` | API Key | View masked key, reveal button, rotate button, usage snippet |
| `/account/subscription` | Subscription | Current plan card, upgrade/downgrade, cancel flow |
| `/account/billing` | Billing & Invoices | Invoice history table, update payment method link |

### Checkout Flow
| Route | Page | Purpose |
|---|---|---|
| `/checkout` | Plan Selection | Plan cards with "Subscribe" CTA; redirects to Stripe Checkout |
| `/checkout/success` | Success | Post-payment confirmation; next-step CTA (set up Meta ID) |
| `/checkout/cancel` | Cancelled | Returns user to pricing; optionally shows a discount offer |

### Admin Panel (protected by `admin` role)
| Route | Page | Purpose |
|---|---|---|
| `/admin` | Overview | MRR chart, active users, new signups, churn gauge |
| `/admin/users` | User List | Searchable table: email, plan, status, joined date; row actions |
| `/admin/users/:id` | User Detail | Full user profile, subscription history, EA activity, impersonate |
| `/admin/subscriptions` | Subscription List | All subs: active, trialing, past_due, cancelled |
| `/admin/plans` | Plan Manager | CRUD for subscription plans and feature flags |
| `/admin/health` | Platform Health | Live: engine count, EA connections, Redis, DB, Celery (if used) |
| `/admin/audit` | Audit Log | Admin action log |

---

## 4. Technical Architecture

### 4.1 Repository Structure (Monorepo)
```
elastic-dca-saas/
├── apps/
│   ├── server/          # FastAPI — trading API + auth + billing
│   ├── web/             # React SPA — dashboard + account pages
│   └── marketing/       # Next.js — landing site (NEW)
├── packages/
│   └── shared-types/    # TypeScript interfaces shared between web/ and marketing/
├── scripts/
│   └── automation.mq5   # Updated MQL5 EA
├── infra/
│   ├── docker/          # Dockerfiles per service
│   ├── nginx/           # Reverse proxy config
│   └── aws/             # IaC (CDK or Terraform)
├── docs/
└── .env.example
```

### 4.2 Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Trading API | FastAPI (Python 3.12) | Keep existing; minimal disruption |
| Auth | `python-jose` (JWT) + `passlib[bcrypt]` | Industry standard |
| ORM | SQLAlchemy 2.x + Alembic | Keep existing; add migrations |
| Database | PostgreSQL 16 | Replace SQLite; production-grade, multi-tenant safe |
| Cache / Locks | Redis 7 | EA single-script lock, subscription status cache, refresh token store |
| Task Queue | Celery + Redis broker | Async email sending, scheduled subscription checks |
| Payment | Stripe (Python SDK) | Industry standard; handles PCI compliance |
| Email | Resend or SendGrid | Transactional emails |
| Marketing Site | Next.js 14 (App Router) | SSR for SEO |
| Dashboard | React 18 + Vite | Keep existing; add routing |
| Router (web) | React Router v6 | Add route-based navigation |
| HTTP Client | TanStack Query + Axios | Replace raw `fetch`; caching + loading states |
| CSS | Tailwind CSS (if not already) | Keep or add; consistent styling across apps |
| Containerization | Docker + Docker Compose | Local dev + production parity |
| Reverse Proxy | Nginx | Route `/ea/*`, `/api/*`, `/` to correct services |
| CI/CD | GitHub Actions | Test + build + deploy pipeline |
| Monitoring | Sentry (errors) + Prometheus/Grafana (metrics) | Production observability |

### 4.3 Domain Architecture

```
yourdomain.com          → Next.js marketing site
app.yourdomain.com      → React SPA (dashboard + account)
api.yourdomain.com      → FastAPI backend
```

All under Nginx or a cloud load balancer. EA `InpServerURL` is set to `https://api.yourdomain.com/ea/{user_api_key}`.

---

## 5. Database Schema

### 5.1 `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR unique | |
| `password_hash` | VARCHAR | bcrypt |
| `name` | VARCHAR | |
| `role` | ENUM `user/admin` | default `user` |
| `email_verified` | BOOLEAN | default false |
| `api_key` | VARCHAR unique | `edca_live_{hex}` |
| `is_active` | BOOLEAN | false = suspended |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.2 `meta_accounts`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK users | |
| `mt5_account_id` | BIGINT unique | The numeric MT5 account ID |
| `broker_name` | VARCHAR | Captured from EA on first tick |
| `is_active` | BOOLEAN | Only one active per user |
| `created_at` | TIMESTAMP | |

### 5.3 `email_verifications`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 24h |
| `used` | BOOLEAN | |

### 5.4 `password_reset_tokens`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 1h |
| `used` | BOOLEAN | |

### 5.5 `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `token_hash` | VARCHAR | SHA-256 of actual token |
| `expires_at` | TIMESTAMP | |
| `revoked` | BOOLEAN | |
| `user_agent` | VARCHAR | For session list display |
| `ip_address` | VARCHAR | |

### 5.6 `plans`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR | e.g., "Monthly", "Annual" |
| `slug` | VARCHAR unique | e.g., `monthly`, `annual` |
| `price_monthly_cents` | INTEGER | in cents |
| `stripe_price_id_monthly` | VARCHAR | |
| `stripe_price_id_annual` | VARCHAR | |
| `trial_days` | INTEGER | 0 = no trial |
| `features` | JSONB | Feature flags for plan gating |
| `is_active` | BOOLEAN | |

### 5.7 `subscriptions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `plan_id` | UUID FK | |
| `stripe_subscription_id` | VARCHAR unique | |
| `stripe_customer_id` | VARCHAR | |
| `status` | ENUM | `trialing / active / past_due / cancelled / expired` |
| `current_period_start` | TIMESTAMP | |
| `current_period_end` | TIMESTAMP | Access granted until this time even if cancelled |
| `cancel_at_period_end` | BOOLEAN | |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.8 `engine_states`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK unique | One row per user |
| `buy_settings` | JSONB | Serialized `GridSettings` |
| `sell_settings` | JSONB | Serialized `GridSettings` |
| `buy_state` | JSONB | Serialized `GridState` |
| `sell_state` | JSONB | Serialized `GridState` |
| `updated_at` | TIMESTAMP | |

### 5.9 `presets` (modified from existing)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Changed from INTEGER |
| `user_id` | UUID FK | **NEW** — scoped to user |
| `name` | VARCHAR | Unique per user (not globally) |
| `rows_json` | TEXT | Existing JSON serialization |

### 5.10 `audit_logs` (admin)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `admin_user_id` | UUID FK | |
| `action` | VARCHAR | e.g., `impersonate_user`, `grant_subscription` |
| `target_user_id` | UUID FK nullable | |
| `metadata` | JSONB | Extra context |
| `created_at` | TIMESTAMP | |

### Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `ea_lock:{user_id}` | 15s (refreshed each tick) | Single-script enforcement lock |
| `sub_status:{user_id}` | 5s | Subscription status cache |
| `refresh:{token_hash}` | 30d | Refresh token store (alternative to DB) |
| `rate_limit:ea:{user_id}` | 1s | EA tick rate limiting (max 5/sec) |
| `rate_limit:api:{ip}` | 60s | Public API rate limiting |

---

## 6. API Design Changes

### 6.1 EA Endpoint (Critical Change)

**Before:** `POST /api/v1/ea/tick`  
**After:** `POST /ea/{api_key}/tick`

The API key is embedded in the URL path because `InpServerURL` in the MT5 EA is the only injection point. The user sets their InpServerURL to `https://api.yourdomain.com/ea/edca_live_xxxx`. The server:
1. Extracts `api_key` from path
2. Resolves `user` from `api_key`
3. Verifies `tick.account_id == user.meta_account_id`
4. Acquires/refreshes `ea_lock:{user_id}` in Redis (15s TTL)
5. If lock already held by different connection token → `403 CONFLICT`
6. Routes tick to `engine_manager.get_or_create(user_id)`
7. Returns actions JSON

### 6.2 Dashboard WebSocket

**Before:** `WS /api/v1/ui/ws` (open to all)  
**After:** `WS /ws?token={jwt_access_token}` — authenticated at connection time

Server validates JWT, extracts `user_id`, adds socket to `user_rooms[user_id]`. State broadcasts go only to that user's sockets. Multiple browser tabs per user are allowed.

### 6.3 Auth Endpoints (New)
```
POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/refresh
POST /auth/verify-email/{token}
POST /auth/forgot-password
POST /auth/reset-password/{token}
GET  /auth/me
```

### 6.4 Subscription Endpoints (New)
```
GET  /billing/plans
POST /billing/checkout-session        # Creates Stripe Checkout → returns URL
GET  /billing/subscription            # Current user subscription
POST /billing/cancel
POST /billing/portal                  # Stripe Customer Portal URL
GET  /billing/invoices
POST /webhooks/stripe                 # Stripe event handler (public, signature-verified)
```

### 6.5 Account Endpoints (New)
```
GET  /account/me
PUT  /account/profile
POST /account/change-password
GET  /account/sessions
DELETE /account/sessions/{id}
GET  /account/meta-account
POST /account/meta-account
DELETE /account/meta-account/lock     # Force-release EA lock
POST /account/api-key/rotate
```

### 6.6 Existing UI Endpoints
All existing `/api/v1/ui/*` routes remain, protected by JWT middleware. `presets` endpoints add `user_id` filter automatically from JWT subject.

---

## 7. MQL5 EA Changes

The EA needs these input changes:
- `InpServerURL` — user sets to `https://api.yourdomain.com/ea/edca_live_xxx` (the API key is baked in)
- No other code changes needed — the API key routing is transparent to the EA

The EA download flow:
1. User subscribes → sets up Meta ID → server shows their personalized `InpServerURL`
2. User downloads `.mq5` file (same for all users)
3. User attaches to ONE chart, enters their personal `InpServerURL`
4. Server routes by API key; no other configuration needed

---

## 8. Multi-Tenancy Engine Design

### `EngineManager` (new file: `app/services/engine_manager.py`)
```python
class EngineManager:
    _instances: dict[str, DcaEngine]  # user_id → engine
    
    def get_or_create(user_id: str, db: Session) -> DcaEngine:
        # Load existing engine or restore from engine_states table
        
    def persist_state(user_id: str, db: Session):
        # Serialize engine.state → engine_states row
        
    def destroy(user_id: str):
        # Subscription expired / user deleted
```

`DcaEngine` is modified minimally:
- Remove singleton pattern (becomes a plain instantiable class)
- `__init__` accepts optional `saved_state` dict to restore from DB
- `session_id` in `GridState` is stored/restored — if EA was disconnected mid-session, grid state is fully restored

---

## 9. Security Hardening

| Concern | Solution |
|---|---|
| CORS | Lock to `app.yourdomain.com` and `yourdomain.com` only |
| JWT signing | RS256 asymmetric key pair; private key in env/secrets manager |
| Password storage | bcrypt with work factor 12 |
| EA API key | Treated as a bearer secret; always HTTPS; rotation available |
| Stripe webhooks | Verify `Stripe-Signature` header using endpoint secret |
| Rate limiting | Slowapi on auth routes (5/min login), EA tick (5/sec per user), public API |
| SQL injection | Parameterized queries via SQLAlchemy ORM only |
| XSS | React renders safely; CSP headers via Nginx |
| CSRF | SameSite=Strict on refresh token cookie; CSRF token on forms |
| Secrets | Never in source; `.env` for local, AWS Secrets Manager for production |
| Admin routes | Double-checked: JWT `role == admin` middleware + role check in every handler |
| Audit logging | All admin actions logged with actor, target, timestamp |

---

## 10. Infrastructure

### Docker Compose (Development)
```
services:
  api:         FastAPI on :8000
  web:         Vite dev server on :5173
  marketing:   Next.js dev server on :3000
  postgres:    PostgreSQL on :5432
  redis:       Redis on :6379
  worker:      Celery worker (emails, scheduled tasks)
```

### Production Architecture
```
Internet → Cloudflare (DDoS, CDN, SSL)
         → AWS ALB
         → ECS (Fargate) tasks:
              - api (FastAPI)     → auto-scales horizontally
              - worker (Celery)   → scales separately
         → RDS PostgreSQL (Multi-AZ)
         → ElastiCache Redis
         → S3 + CloudFront for marketing (Next.js static export or Vercel)
         → S3 + CloudFront for web app (React SPA build)
```

Alternatively (simpler/cheaper solo): single VPS (Hetzner/DO), Docker Compose in production, Nginx reverse proxy, managed PostgreSQL add-on, Upstash Redis.

---

## 11. Delivery Phases & Time Estimates (Solo Developer)

Assumes: ~6-8 hours/day focus time, existing familiarity with FastAPI and React.

### Phase 1 — Foundation (4–5 weeks)
| Task | Est. |
|---|---|
| Monorepo restructure, Docker Compose, PostgreSQL setup, Alembic | 3 days |
| User model, auth endpoints (register/login/verify/reset) | 4 days |
| JWT middleware, refresh token rotation | 2 days |
| Password reset email flow (Resend/SendGrid) | 2 days |
| Frontend: React Router setup, auth pages (login/register/forgot/reset) | 4 days |
| Auth guards, protected routes, token refresh interceptor | 3 days |
| Testing auth flow end-to-end | 2 days |
| **Milestone:** Logged-in user, email verification working | |

### Phase 2 — Multi-Tenant Engine (5–7 weeks)
| Task | Est. |
|---|---|
| `EngineManager` class, remove DcaEngine singleton | 3 days |
| `engine_states` table + persist/restore logic | 3 days |
| EA endpoint refactor: API key routing, meta_id binding | 3 days |
| Redis single-script lock system | 2 days |
| Meta account registration UI + force-unlock feature | 2 days |
| WebSocket authentication + per-user rooms | 3 days |
| Subscription enforcement middleware (Redis cache check) | 2 days |
| Presets — add `user_id` scope | 1 day |
| Integration testing all engine paths | 4 days |
| **Milestone:** Two users can run in parallel with full isolation | |

### Phase 3 — Subscriptions & Billing (4–5 weeks)
| Task | Est. |
|---|---|
| Stripe account setup, products/prices created in Stripe dashboard | 1 day |
| Plans table, `subscriptions` table, Stripe customer creation | 2 days |
| Stripe Checkout session endpoint | 2 days |
| Webhook handler: all critical Stripe events | 3 days |
| Stripe Customer Portal integration (billing management) | 1 day |
| Subscription status enforcement on all protected endpoints | 2 days |
| Trial period logic + pre-expiry reminder emails (Celery task) | 2 days |
| Frontend: pricing page, checkout flow, subscription/billing pages | 5 days |
| **Milestone:** Full end-to-end subscribe → trade → cancel flow | |

### Phase 4 — Marketing Site (3–4 weeks)
| Task | Est. |
|---|---|
| Next.js project setup, Tailwind, shared design system | 2 days |
| Landing page (hero, features, social proof, pricing teaser, CTA) | 4 days |
| Pricing page (plan cards, feature table, FAQ) | 2 days |
| Features page | 2 days |
| Documentation (getting started, EA setup, dashboard guide) | 4 days |
| About + Contact pages | 1 day |
| Legal pages (ToS, Privacy, Cookies) | 2 days |
| SEO metadata, sitemap, robots.txt | 1 day |
| **Milestone:** Public site live, converts visitors to signups | |

### Phase 5 — Admin Panel (3–4 weeks)
| Task | Est. |
|---|---|
| Admin role middleware | 1 day |
| Admin overview dashboard (MRR, signups, churn) | 3 days |
| User list + search + detail + suspend/unsuspend | 3 days |
| Subscription management + manual grant/extend | 2 days |
| Platform health page | 2 days |
| Audit log | 2 days |
| **Milestone:** Admin can manage all users and subscriptions | |

### Phase 6 — Hardening & Launch (3–4 weeks)
| Task | Est. |
|---|---|
| Security audit: CORS, headers, rate limiting, input validation | 3 days |
| Error handling: user-facing error pages, Sentry integration | 2 days |
| Load testing EA tick endpoint | 1 day |
| CI/CD pipeline (GitHub Actions: test + build + deploy) | 2 days |
| Production infrastructure setup (VPS or AWS) | 3 days |
| HTTPS, certificates (Let's Encrypt or ACM) | 1 day |
| Backup strategy (DB daily snapshots) | 1 day |
| Smoke testing all user journeys in production | 2 days |
| **Milestone:** Platform live, accepting paying customers | |

### Total Solo Estimate
| Phase | Min | Max |
|---|---|---|
| Phase 1: Foundation | 4 weeks | 5 weeks |
| Phase 2: Multi-Tenant Engine | 5 weeks | 7 weeks |
| Phase 3: Billing | 4 weeks | 5 weeks |
| Phase 4: Marketing | 3 weeks | 4 weeks |
| Phase 5: Admin Panel | 3 weeks | 4 weeks |
| Phase 6: Hardening & Launch | 3 weeks | 4 weeks |
| **Total** | **22 weeks** | **29 weeks** |

> **Realistic solo timeline: 5.5–7 months** with focused daily work.  
> Buffer for real life, debugging unknown unknowns, and iteration: add 20–30%.

---

## 12. Complexity Assessment

### By Component

| Component | Complexity | Notes |
|---|---|---|
| Auth system | Medium | Well-understood patterns; libraries do heavy lifting |
| JWT + refresh rotation | Medium | fiddly but documented |
| Stripe integration | Medium–High | Webhook state machine has many edge cases |
| Multi-tenant engine | **High** | Biggest architectural lift; singleton → per-user factory |
| EA single-script lock | Medium | Redis TTL + refresh; logic is clear but must be bulletproof |
| State persistence | Medium | Serialize/restore engine state; risk: version mismatches |
| WebSocket auth + rooms | Medium | JWT at upgrade handshake; room management |
| Marketing site (Next.js) | Low–Medium | Standard Next.js; main work is design/content |
| Admin panel | Medium | CRUD + charts; no novel logic |
| Production infra | Medium | Standard containerized deployment |
| MQL5 EA changes | **Low** | Only URL change needed — no logic changes |

### Biggest Technical Risks

1. **Engine state serialization**: If `GridSettings`/`GridState` schema changes, stored JSON may be incompatible. Mitigation: version field on stored JSON + migration scripts.
2. **EA lock edge cases**: MT5 crash leaves lock held for 15 seconds. Mitigation: force-unlock UI, tune TTL, clear lock on confirmed EA disconnect.
3. **Stripe webhook delivery**: Must be idempotent — same webhook may arrive twice. Mitigation: store `stripe_event_id`, skip if already processed.
4. **Single-server bottleneck on engine**: If engine processing blocks async loop, all users suffer. Mitigation: run engine evaluation in `asyncio.run_in_executor` or separate threads per user.
5. **Meta ID uniqueness enforcement**: Race condition if two accounts try to register same Meta ID simultaneously. Mitigation: DB unique constraint + optimistic locking.

---

## 13. What Can Be Parallelized / Deferred

### Parallelize
- Marketing site can be built while Phase 2 engine work is in progress
- Admin panel UI can be partially scaffolded during Phase 2

### Defer to Post-MVP (v2)
| Feature | Why Defer |
|---|---|
| Google OAuth | JWT auth alone is sufficient for launch |
| 2FA | Adds significant complexity; not critical |
| Discord/Slack webhooks | Nice-to-have; not core |
| Blog | Content work; no impact on core SaaS |
| Symbol multi-instance per user | Major engine change; wait for demand signal |
| Mobile app | Desktop trading tool; mobile not needed at launch |
| Advanced analytics for users | Feature, not critical path |Let me explore the codebase thoroughly before drafting the plan. 

Explore trading app codebase

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/README.md)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/new_flow_blueprint.md)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/docs/ARCHITECTURE.md#1-1), lines 1 to 200

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/docs/API_REFERENCE.md#1-1), lines 1 to 200

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/docs/API_REFERENCE.md#201-201), lines 201 to 400

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/config.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/database/models.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/database/session.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/models/schemas.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/routers/ea_api.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/routers/ui_api.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/services/utils.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/services/engine.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/main.py)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/services/api.ts)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/types.ts)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/App.tsx)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/SidePanel.tsx#1-1), lines 1 to 300

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/SidePanel.tsx#300-300), lines 300 to 600

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/GridTable.tsx)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/TopBar.tsx)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/CreatePresetModal.tsx#1-1), lines 1 to 150

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/ManagePresetsModal.tsx#1-1), lines 1 to 100

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/scripts/automation.mq5#1-1), lines 1 to 400

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/scripts/automation.mq5#400-400), lines 400 to 599

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/web/src/components/NumberInput.tsx)

Read [](file:///home/all_father/Documents/workshop/trading/Elastic_DCA_Trading/apps/server/app/logger.py)

Read [](file:///home/all_father/.config/Code/User/workspaceStorage/2b518a02c7afe2d66c8583c5c71ffb5c/GitHub.copilot-chat/chat-session-resources/06679fe0-1339-4c64-bd6c-b0770935a9c2/toolu_bdrk_01AnJrUHNbeVhr2pdemxVofB__vscode-1775289188998/content.txt)

Excellent. I have a thorough understanding of the existing system. Let me now build the comprehensive plan document. 

Created memory file [](file:///home/all_father/.config/Code/User/workspaceStorage/2b518a02c7afe2d66c8583c5c71ffb5c/GitHub.copilot-chat/memory-tool/memories/MDY2NzlmZTAtMTMzOS00YzY0LWJkNmMtYjA3NzA5MzVhOWMy/plan.md)

Now let me write the full document: 

Updated memory file [](file:///home/all_father/.config/Code/User/workspaceStorage/2b518a02c7afe2d66c8583c5c71ffb5c/GitHub.copilot-chat/memory-tool/memories/MDY2NzlmZTAtMTMzOS00YzY0LWJkNmMtYjA3NzA5MzVhOWMy/plan.md)

Here is the **God-Level SaaS Specification** for converting Elastic DCA Trader into a full SaaS platform:

---

## Plan: Elastic DCA Trader — SaaS Platform Specification

**TL;DR:** Convert the current single-user, open-API algorithmic trading tool into a multi-tenant SaaS with user accounts, subscription tiers, payment processing, a marketing/pricing website, single-script enforcement per user via MT5 Meta ID binding, and an admin control panel — all while keeping the core DCA engine logic intact.

---

# ELASTIC DCA TRADER — SAAS PLATFORM SPEC

---

## 1. What This Platform Is

A subscription-based SaaS that lets retail traders connect their MetaTrader 5 terminal to a cloud-hosted Elastic DCA trading engine. The trader installs the provided `.mq5` EA on one chart, configures it with their personal API key, and the cloud engine handles all logic. The dashboard gives real-time visibility and control. Subscriptions gate access with hard enforcement on the server side.

---

## 2. Feature Inventory

### 2.1 Authentication & Identity
| Feature | Description |
|---|---|
| Email/Password Registration | Standard signup with unique email requirement |
| Email Verification | Verification link sent on signup; unverified users can browse but not use trading features |
| Login / Logout | JWT access token (15 min) + refresh token (7-30 days, httpOnly cookie) |
| Forgot Password | Sends time-limited reset link to registered email |
| Password Reset | Token-validated form to set new password |
| Session Management | View active sessions, revoke individual sessions |
| Role System | `user`, `admin` roles stored on user record |
| Optional: Google OAuth | One-click sign-in; links accounts by email |
| 2FA (Post-MVP) | TOTP-based (Google Authenticator compatible) |

### 2.2 Subscription & Billing
| Feature | Description |
|---|---|
| Plan Tiers | At least: Free Trial, Monthly, Quarterly, Annual |
| Stripe Integration | Checkout sessions, subscription lifecycle, customer portal |
| Free Trial | N-day trial with full access; auto-expires, no card required OR card required with auto-charge |
| Plan Upgrade/Downgrade | Prorated via Stripe, effective immediately |
| Subscription Cancellation | Cancel at period end (access until end_date) or immediately |
| Grace Period | If payment fails, configurable N-day grace period before access revoked |
| Invoice History | View all invoices with PDF download links (from Stripe) |
| Payment Method Management | Update card, view last 4 digits — delegated to Stripe Customer Portal |
| Webhook Handler | Handles Stripe events: `invoice.paid`, `invoice.payment_failed`, `customer.subscription.deleted`, `customer.subscription.updated` |
| Trial-to-Paid Conversion Emails | Automated reminders at 3 days before trial end |

### 2.3 Meta ID (MT5 Account) Binding System
This is the **core enforcement mechanism** replacing the current zero-auth model.
| Feature | Description |
|---|---|
| Meta ID Registration | User submits their MT5 numeric account ID from MT4/5 terminal. Stored server-side. |
| Unique Binding | One MT5 account ID can be bound to exactly one platform user account. No sharing. |
| Single-Script Lock | Per-user Redis key: `ea_lock:{user_id}`. When EA sends first tick, lock is acquired with 15-second TTL, refreshed every tick. Second EA connection for same user gets `403 CONFLICT` response. |
| Lock Override | User can force-release the lock from the dashboard ("Emergency Disconnect") to recover from a crashed MT5 without waiting for TTL expiry. |
| Meta ID Change | User can update Meta ID only if no active EA session (lock is free). Old binding is archived. |
| Meta ID Verification | When EA sends first tick, `tick.account_id` must match `user.meta_account_id`. Mismatch → `403 FORBIDDEN`. |
| Credential Delivery | After binding, server shows user their personal EA Server URL (`https://api.domain.com/ea/USER_API_KEY`) which they enter in MT5 `InpServerURL`. No email. Shown once, copyable. |

### 2.4 Multi-Tenant Trading Engine
| Feature | Description |
|---|---|
| Per-User Engine Instance | `EngineManager` class: `dict[user_id → DcaEngine]`. Engines are created on first authenticated EA tick and destroyed on subscription expiry. |
| Engine State Persistence | Engine's `GridSettings`, `GridState` serialized to PostgreSQL `engine_states` table every tick. Server restart restores all active users' states. |
| Per-User Presets | Presets table gains `user_id` FK. Users cannot see or load other users' presets. |
| Per-User WebSocket Room | WebSocket connections are authenticated (JWT or API key). Each connection is keyed to `user_id`. `SystemState` broadcasts only to that user's sockets. |
| Subscription Enforcement | Before processing any tick, check `user.subscription_status` in Redis cache (5-second TTL). Expired → `403 FORBIDDEN`, engine is suspended. |
| Symbol Multi-Instance (Post-MVP) | Future: allow multiple MetaId/symbol pairs per account on higher-tier plans. |

### 2.5 API Key System
| Feature | Description |
|---|---|
| Auto-Generated on Signup | `user_api_key`: `edca_live_{uuid4_hex}` — 40+ char random key |
| EA-Facing Endpoint | `POST /ea/{api_key}/tick` — key is in URL path, not header (because MQL5 `InpServerURL` param is the only injection point) |
| Key Rotation | User can regenerate key from account settings; old key immediately invalidated. Warning shown that EA config must be updated. |
| Key Visibility | Masked display (`edca_live_****...****xyz`); full key revealed behind password confirmation or "Click to reveal" with audit log entry. |

### 2.6 Real-Time Trading Dashboard
Enhanced version of the existing React app:
| Feature | Description |
|---|---|
| All existing dashboard features | Grid tables, controls, presets, TP/SL, etc. — unchanged |
| EA Connection Status | Shows `connected` / `disconnected` + last ping time |
| Subscription Status Badge | Prominently shows plan name, days remaining, renewal date |
| Meta ID Status | Shows registered Meta ID + lock status (active / free) |
| Quick Stats | Today's P&L, open positions count, total equity delta |
| Persistent State on Reconnect | Engine state restored from DB if browser was closed; no state loss |
| Alert History | Last N triggered row alerts stored and viewable |

### 2.7 Account Management Pages
| Feature | Description |
|---|---|
| Profile | Name, email, timezone, profile picture |
| Security | Change password, active sessions list, revoke sessions |
| Meta Account | Register / update MT5 account ID, view EA download + configuration instructions |
| API Key | View/reveal/rotate personal API key |
| Subscription | Current plan, billing cycle, usage, upgrade/downgrade CTA, cancel |
| Billing & Invoices | Invoice table with amount, date, status, PDF link (Stripe data) |

### 2.8 Marketing & Landing Site
| Feature | Description |
|---|---|
| Landing Page | Hero, features overview, social proof, CTA |
| Pricing Page | Plan comparison table, FAQ, toggle monthly/annual |
| Features Page | Deep-dive on DCA engine, grid trading explanation |
| Documentation | Setup guide, EA configuration, troubleshooting, API ref |
| Blog (Post-MVP) | Content marketing for SEO |
| About / Contact | Team, support form or Discord link |
| Legal Pages | Terms of Service, Privacy Policy, Cookie Policy |

### 2.9 Admin Panel
| Feature | Description |
|---|---|
| Overview Dashboard | DAU, MRR, active subscriptions, churn, new signups chart |
| User Management | Search, view profile, change role, suspend/unsuspend, impersonate |
| Subscription Management | View by user, manually extend, grant free access, refund trigger |
| Plan Configuration | Create/edit/deactivate plans, set prices and feature flags |
| Platform Health | EA connections count, engine instances running, Redis status, DB health |
| Audit Log | Log of all admin actions |

### 2.10 Notification System
| Feature | Description |
|---|---|
| Transactional Emails | Verify email, welcome, password reset, trial expiry warning, payment failed, subscription cancelled, payment receipt |
| In-App Toasts | Enhanced version of existing toast system — subscription warnings, connection events |
| Webhook Alerts (Post-MVP) | User-configurable Discord/Slack webhook for TP/SL hit events |

---

## 3. Pages Inventory

### Marketing Site (Next.js — server-rendered for SEO)
| Route | Page | Purpose |
|---|---|---|
| `/` | Landing | Hero section, features overview, testimonials, pricing teaser, CTAs |
| `/pricing` | Pricing | Plan cards, monthly/annual toggle, feature comparison table, FAQ |
| `/features` | Features | Detailed DCA explanation, grid visualization, use cases |
| docs | Documentation Index | Links to setup guide, configuration, troubleshooting |
| `/docs/getting-started` | Getting Started | Step-by-step: subscribe → configure EA → connect |
| `/docs/ea-setup` | EA Setup Guide | Download link, MT5 configuration, `InpServerURL` setup |
| `/docs/dashboard` | Dashboard Guide | Controls, settings, presets explained |
| `/about` | About | Mission statement, contact info |
| `/contact` | Contact | Support form (or redirect to Discord) |
| `/legal/terms` | Terms of Service | Full ToS |
| `/legal/privacy` | Privacy Policy | GDPR-compliant privacy policy |
| `/legal/cookies` | Cookie Policy | Cookie usage disclosure |
| `/blog` | Blog Index | *(Post-MVP)* Article listing |

### Auth Pages (React App or shared Next.js)
| Route | Page | Purpose |
|---|---|---|
| `/register` | Sign Up | Email, password, name; CTA to pricing before this |
| `/login` | Sign In | Email + password; "Forgot password" link |
| `/verify-email` | Email Verification | Sends link; shows "check your inbox" state; resend button |
| `/verify-email/:token` | Verification Handler | Validates token, redirects to `/dashboard` or shows error |
| `/forgot-password` | Forgot Password | Email input → sends reset link |
| `/reset-password/:token` | Reset Password | New password form; validates token expiry |

### App — Trading Dashboard (React SPA)
| Route | Page | Purpose |
|---|---|---|
| `/dashboard` | Main Dashboard | Full trading dashboard (enhanced existing) |
| `/dashboard/alerts` | Alert History | Historical log of triggered row alerts |

### App — Account Management
| Route | Page | Purpose |
|---|---|---|
| `/account` | Account Overview | Quick summary: plan, meta ID status, API key status |
| `/account/profile` | Profile Settings | Name, email, timezone |
| `/account/security` | Security | Password change, active sessions, revoke session buttons |
| `/account/meta-account` | MT5 Account | Register/view/update Meta ID; EA setup instructions; force-unlock button |
| `/account/api-key` | API Key | View masked key, reveal button, rotate button, usage snippet |
| `/account/subscription` | Subscription | Current plan card, upgrade/downgrade, cancel flow |
| `/account/billing` | Billing & Invoices | Invoice history table, update payment method link |

### Checkout Flow
| Route | Page | Purpose |
|---|---|---|
| `/checkout` | Plan Selection | Plan cards with "Subscribe" CTA; redirects to Stripe Checkout |
| `/checkout/success` | Success | Post-payment confirmation; next-step CTA (set up Meta ID) |
| `/checkout/cancel` | Cancelled | Returns user to pricing; optionally shows a discount offer |

### Admin Panel (protected by `admin` role)
| Route | Page | Purpose |
|---|---|---|
| `/admin` | Overview | MRR chart, active users, new signups, churn gauge |
| `/admin/users` | User List | Searchable table: email, plan, status, joined date; row actions |
| `/admin/users/:id` | User Detail | Full user profile, subscription history, EA activity, impersonate |
| `/admin/subscriptions` | Subscription List | All subs: active, trialing, past_due, cancelled |
| `/admin/plans` | Plan Manager | CRUD for subscription plans and feature flags |
| `/admin/health` | Platform Health | Live: engine count, EA connections, Redis, DB, Celery (if used) |
| `/admin/audit` | Audit Log | Admin action log |

---

## 4. Technical Architecture

### 4.1 Repository Structure (Monorepo)
```
elastic-dca-saas/
├── apps/
│   ├── server/          # FastAPI — trading API + auth + billing
│   ├── web/             # React SPA — dashboard + account pages
│   └── marketing/       # Next.js — landing site (NEW)
├── packages/
│   └── shared-types/    # TypeScript interfaces shared between web/ and marketing/
├── scripts/
│   └── automation.mq5   # Updated MQL5 EA
├── infra/
│   ├── docker/          # Dockerfiles per service
│   ├── nginx/           # Reverse proxy config
│   └── aws/             # IaC (CDK or Terraform)
├── docs/
└── .env.example
```

### 4.2 Technology Stack

| Layer | Technology | Reason |
|---|---|---|
| Trading API | FastAPI (Python 3.12) | Keep existing; minimal disruption |
| Auth | `python-jose` (JWT) + `passlib[bcrypt]` | Industry standard |
| ORM | SQLAlchemy 2.x + Alembic | Keep existing; add migrations |
| Database | PostgreSQL 16 | Replace SQLite; production-grade, multi-tenant safe |
| Cache / Locks | Redis 7 | EA single-script lock, subscription status cache, refresh token store |
| Task Queue | Celery + Redis broker | Async email sending, scheduled subscription checks |
| Payment | Stripe (Python SDK) | Industry standard; handles PCI compliance |
| Email | Resend or SendGrid | Transactional emails |
| Marketing Site | Next.js 14 (App Router) | SSR for SEO |
| Dashboard | React 18 + Vite | Keep existing; add routing |
| Router (web) | React Router v6 | Add route-based navigation |
| HTTP Client | TanStack Query + Axios | Replace raw `fetch`; caching + loading states |
| CSS | Tailwind CSS (if not already) | Keep or add; consistent styling across apps |
| Containerization | Docker + Docker Compose | Local dev + production parity |
| Reverse Proxy | Nginx | Route `/ea/*`, `/api/*`, `/` to correct services |
| CI/CD | GitHub Actions | Test + build + deploy pipeline |
| Monitoring | Sentry (errors) + Prometheus/Grafana (metrics) | Production observability |

### 4.3 Domain Architecture

```
yourdomain.com          → Next.js marketing site
app.yourdomain.com      → React SPA (dashboard + account)
api.yourdomain.com      → FastAPI backend
```

All under Nginx or a cloud load balancer. EA `InpServerURL` is set to `https://api.yourdomain.com/ea/{user_api_key}`.

---

## 5. Database Schema

### 5.1 `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `email` | VARCHAR unique | |
| `password_hash` | VARCHAR | bcrypt |
| `name` | VARCHAR | |
| `role` | ENUM `user/admin` | default `user` |
| `email_verified` | BOOLEAN | default false |
| `api_key` | VARCHAR unique | `edca_live_{hex}` |
| `is_active` | BOOLEAN | false = suspended |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.2 `meta_accounts`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK users | |
| `mt5_account_id` | BIGINT unique | The numeric MT5 account ID |
| `broker_name` | VARCHAR | Captured from EA on first tick |
| `is_active` | BOOLEAN | Only one active per user |
| `created_at` | TIMESTAMP | |

### 5.3 `email_verifications`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 24h |
| `used` | BOOLEAN | |

### 5.4 `password_reset_tokens`
| Column | Type | Notes |
|---|---|---|
| `token` | VARCHAR PK | UUID |
| `user_id` | UUID FK | |
| `expires_at` | TIMESTAMP | 1h |
| `used` | BOOLEAN | |

### 5.5 `refresh_tokens`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `token_hash` | VARCHAR | SHA-256 of actual token |
| `expires_at` | TIMESTAMP | |
| `revoked` | BOOLEAN | |
| `user_agent` | VARCHAR | For session list display |
| `ip_address` | VARCHAR | |

### 5.6 `plans`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR | e.g., "Monthly", "Annual" |
| `slug` | VARCHAR unique | e.g., `monthly`, `annual` |
| `price_monthly_cents` | INTEGER | in cents |
| `stripe_price_id_monthly` | VARCHAR | |
| `stripe_price_id_annual` | VARCHAR | |
| `trial_days` | INTEGER | 0 = no trial |
| `features` | JSONB | Feature flags for plan gating |
| `is_active` | BOOLEAN | |

### 5.7 `subscriptions`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK | |
| `plan_id` | UUID FK | |
| `stripe_subscription_id` | VARCHAR unique | |
| `stripe_customer_id` | VARCHAR | |
| `status` | ENUM | `trialing / active / past_due / cancelled / expired` |
| `current_period_start` | TIMESTAMP | |
| `current_period_end` | TIMESTAMP | Access granted until this time even if cancelled |
| `cancel_at_period_end` | BOOLEAN | |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

### 5.8 `engine_states`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | UUID FK unique | One row per user |
| `buy_settings` | JSONB | Serialized `GridSettings` |
| `sell_settings` | JSONB | Serialized `GridSettings` |
| `buy_state` | JSONB | Serialized `GridState` |
| `sell_state` | JSONB | Serialized `GridState` |
| `updated_at` | TIMESTAMP | |

### 5.9 `presets` (modified from existing)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Changed from INTEGER |
| `user_id` | UUID FK | **NEW** — scoped to user |
| `name` | VARCHAR | Unique per user (not globally) |
| `rows_json` | TEXT | Existing JSON serialization |

### 5.10 `audit_logs` (admin)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `admin_user_id` | UUID FK | |
| `action` | VARCHAR | e.g., `impersonate_user`, `grant_subscription` |
| `target_user_id` | UUID FK nullable | |
| `metadata` | JSONB | Extra context |
| `created_at` | TIMESTAMP | |

### Redis Keys
| Key Pattern | TTL | Purpose |
|---|---|---|
| `ea_lock:{user_id}` | 15s (refreshed each tick) | Single-script enforcement lock |
| `sub_status:{user_id}` | 5s | Subscription status cache |
| `refresh:{token_hash}` | 30d | Refresh token store (alternative to DB) |
| `rate_limit:ea:{user_id}` | 1s | EA tick rate limiting (max 5/sec) |
| `rate_limit:api:{ip}` | 60s | Public API rate limiting |

---

## 6. API Design Changes

### 6.1 EA Endpoint (Critical Change)

**Before:** `POST /api/v1/ea/tick`  
**After:** `POST /ea/{api_key}/tick`

The API key is embedded in the URL path because `InpServerURL` in the MT5 EA is the only injection point. The user sets their InpServerURL to `https://api.yourdomain.com/ea/edca_live_xxxx`. The server:
1. Extracts `api_key` from path
2. Resolves `user` from `api_key`
3. Verifies `tick.account_id == user.meta_account_id`
4. Acquires/refreshes `ea_lock:{user_id}` in Redis (15s TTL)
5. If lock already held by different connection token → `403 CONFLICT`
6. Routes tick to `engine_manager.get_or_create(user_id)`
7. Returns actions JSON

### 6.2 Dashboard WebSocket

**Before:** `WS /api/v1/ui/ws` (open to all)  
**After:** `WS /ws?token={jwt_access_token}` — authenticated at connection time

Server validates JWT, extracts `user_id`, adds socket to `user_rooms[user_id]`. State broadcasts go only to that user's sockets. Multiple browser tabs per user are allowed.

### 6.3 Auth Endpoints (New)
```
POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/refresh
POST /auth/verify-email/{token}
POST /auth/forgot-password
POST /auth/reset-password/{token}
GET  /auth/me
```

### 6.4 Subscription Endpoints (New)
```
GET  /billing/plans
POST /billing/checkout-session        # Creates Stripe Checkout → returns URL
GET  /billing/subscription            # Current user subscription
POST /billing/cancel
POST /billing/portal                  # Stripe Customer Portal URL
GET  /billing/invoices
POST /webhooks/stripe                 # Stripe event handler (public, signature-verified)
```

### 6.5 Account Endpoints (New)
```
GET  /account/me
PUT  /account/profile
POST /account/change-password
GET  /account/sessions
DELETE /account/sessions/{id}
GET  /account/meta-account
POST /account/meta-account
DELETE /account/meta-account/lock     # Force-release EA lock
POST /account/api-key/rotate
```

### 6.6 Existing UI Endpoints
All existing `/api/v1/ui/*` routes remain, protected by JWT middleware. `presets` endpoints add `user_id` filter automatically from JWT subject.

---

## 7. MQL5 EA Changes

The EA needs these input changes:
- `InpServerURL` — user sets to `https://api.yourdomain.com/ea/edca_live_xxx` (the API key is baked in)
- No other code changes needed — the API key routing is transparent to the EA

The EA download flow:
1. User subscribes → sets up Meta ID → server shows their personalized `InpServerURL`
2. User downloads `.mq5` file (same for all users)
3. User attaches to ONE chart, enters their personal `InpServerURL`
4. Server routes by API key; no other configuration needed

---

## 8. Multi-Tenancy Engine Design

### `EngineManager` (new file: `app/services/engine_manager.py`)
```python
class EngineManager:
    _instances: dict[str, DcaEngine]  # user_id → engine
    
    def get_or_create(user_id: str, db: Session) -> DcaEngine:
        # Load existing engine or restore from engine_states table
        
    def persist_state(user_id: str, db: Session):
        # Serialize engine.state → engine_states row
        
    def destroy(user_id: str):
        # Subscription expired / user deleted
```

`DcaEngine` is modified minimally:
- Remove singleton pattern (becomes a plain instantiable class)
- `__init__` accepts optional `saved_state` dict to restore from DB
- `session_id` in `GridState` is stored/restored — if EA was disconnected mid-session, grid state is fully restored

---

## 9. Security Hardening

| Concern | Solution |
|---|---|
| CORS | Lock to `app.yourdomain.com` and `yourdomain.com` only |
| JWT signing | RS256 asymmetric key pair; private key in env/secrets manager |
| Password storage | bcrypt with work factor 12 |
| EA API key | Treated as a bearer secret; always HTTPS; rotation available |
| Stripe webhooks | Verify `Stripe-Signature` header using endpoint secret |
| Rate limiting | Slowapi on auth routes (5/min login), EA tick (5/sec per user), public API |
| SQL injection | Parameterized queries via SQLAlchemy ORM only |
| XSS | React renders safely; CSP headers via Nginx |
| CSRF | SameSite=Strict on refresh token cookie; CSRF token on forms |
| Secrets | Never in source; `.env` for local, AWS Secrets Manager for production |
| Admin routes | Double-checked: JWT `role == admin` middleware + role check in every handler |
| Audit logging | All admin actions logged with actor, target, timestamp |

---

## 10. Infrastructure

### Docker Compose (Development)
```
services:
  api:         FastAPI on :8000
  web:         Vite dev server on :5173
  marketing:   Next.js dev server on :3000
  postgres:    PostgreSQL on :5432
  redis:       Redis on :6379
  worker:      Celery worker (emails, scheduled tasks)
```

### Production Architecture
```
Internet → Cloudflare (DDoS, CDN, SSL)
         → AWS ALB
         → ECS (Fargate) tasks:
              - api (FastAPI)     → auto-scales horizontally
              - worker (Celery)   → scales separately
         → RDS PostgreSQL (Multi-AZ)
         → ElastiCache Redis
         → S3 + CloudFront for marketing (Next.js static export or Vercel)
         → S3 + CloudFront for web app (React SPA build)
```

Alternatively (simpler/cheaper solo): single VPS (Hetzner/DO), Docker Compose in production, Nginx reverse proxy, managed PostgreSQL add-on, Upstash Redis.

---

## 11. Delivery Phases & Time Estimates (Solo Developer)

Assumes: ~6-8 hours/day focus time, existing familiarity with FastAPI and React.

### Phase 1 — Foundation (4–5 weeks)
| Task | Est. |
|---|---|
| Monorepo restructure, Docker Compose, PostgreSQL setup, Alembic | 3 days |
| User model, auth endpoints (register/login/verify/reset) | 4 days |
| JWT middleware, refresh token rotation | 2 days |
| Password reset email flow (Resend/SendGrid) | 2 days |
| Frontend: React Router setup, auth pages (login/register/forgot/reset) | 4 days |
| Auth guards, protected routes, token refresh interceptor | 3 days |
| Testing auth flow end-to-end | 2 days |
| **Milestone:** Logged-in user, email verification working | |

### Phase 2 — Multi-Tenant Engine (5–7 weeks)
| Task | Est. |
|---|---|
| `EngineManager` class, remove DcaEngine singleton | 3 days |
| `engine_states` table + persist/restore logic | 3 days |
| EA endpoint refactor: API key routing, meta_id binding | 3 days |
| Redis single-script lock system | 2 days |
| Meta account registration UI + force-unlock feature | 2 days |
| WebSocket authentication + per-user rooms | 3 days |
| Subscription enforcement middleware (Redis cache check) | 2 days |
| Presets — add `user_id` scope | 1 day |
| Integration testing all engine paths | 4 days |
| **Milestone:** Two users can run in parallel with full isolation | |

### Phase 3 — Subscriptions & Billing (4–5 weeks)
| Task | Est. |
|---|---|
| Stripe account setup, products/prices created in Stripe dashboard | 1 day |
| Plans table, `subscriptions` table, Stripe customer creation | 2 days |
| Stripe Checkout session endpoint | 2 days |
| Webhook handler: all critical Stripe events | 3 days |
| Stripe Customer Portal integration (billing management) | 1 day |
| Subscription status enforcement on all protected endpoints | 2 days |
| Trial period logic + pre-expiry reminder emails (Celery task) | 2 days |
| Frontend: pricing page, checkout flow, subscription/billing pages | 5 days |
| **Milestone:** Full end-to-end subscribe → trade → cancel flow | |

### Phase 4 — Marketing Site (3–4 weeks)
| Task | Est. |
|---|---|
| Next.js project setup, Tailwind, shared design system | 2 days |
| Landing page (hero, features, social proof, pricing teaser, CTA) | 4 days |
| Pricing page (plan cards, feature table, FAQ) | 2 days |
| Features page | 2 days |
| Documentation (getting started, EA setup, dashboard guide) | 4 days |
| About + Contact pages | 1 day |
| Legal pages (ToS, Privacy, Cookies) | 2 days |
| SEO metadata, sitemap, robots.txt | 1 day |
| **Milestone:** Public site live, converts visitors to signups | |

### Phase 5 — Admin Panel (3–4 weeks)
| Task | Est. |
|---|---|
| Admin role middleware | 1 day |
| Admin overview dashboard (MRR, signups, churn) | 3 days |
| User list + search + detail + suspend/unsuspend | 3 days |
| Subscription management + manual grant/extend | 2 days |
| Platform health page | 2 days |
| Audit log | 2 days |
| **Milestone:** Admin can manage all users and subscriptions | |

### Phase 6 — Hardening & Launch (3–4 weeks)
| Task | Est. |
|---|---|
| Security audit: CORS, headers, rate limiting, input validation | 3 days |
| Error handling: user-facing error pages, Sentry integration | 2 days |
| Load testing EA tick endpoint | 1 day |
| CI/CD pipeline (GitHub Actions: test + build + deploy) | 2 days |
| Production infrastructure setup (VPS or AWS) | 3 days |
| HTTPS, certificates (Let's Encrypt or ACM) | 1 day |
| Backup strategy (DB daily snapshots) | 1 day |
| Smoke testing all user journeys in production | 2 days |
| **Milestone:** Platform live, accepting paying customers | |

### Total Solo Estimate
| Phase | Min | Max |
|---|---|---|
| Phase 1: Foundation | 4 weeks | 5 weeks |
| Phase 2: Multi-Tenant Engine | 5 weeks | 7 weeks |
| Phase 3: Billing | 4 weeks | 5 weeks |
| Phase 4: Marketing | 3 weeks | 4 weeks |
| Phase 5: Admin Panel | 3 weeks | 4 weeks |
| Phase 6: Hardening & Launch | 3 weeks | 4 weeks |
| **Total** | **22 weeks** | **29 weeks** |

> **Realistic solo timeline: 5.5–7 months** with focused daily work.  
> Buffer for real life, debugging unknown unknowns, and iteration: add 20–30%.

---

## 12. Complexity Assessment

### By Component

| Component | Complexity | Notes |
|---|---|---|
| Auth system | Medium | Well-understood patterns; libraries do heavy lifting |
| JWT + refresh rotation | Medium | fiddly but documented |
| Stripe integration | Medium–High | Webhook state machine has many edge cases |
| Multi-tenant engine | **High** | Biggest architectural lift; singleton → per-user factory |
| EA single-script lock | Medium | Redis TTL + refresh; logic is clear but must be bulletproof |
| State persistence | Medium | Serialize/restore engine state; risk: version mismatches |
| WebSocket auth + rooms | Medium | JWT at upgrade handshake; room management |
| Marketing site (Next.js) | Low–Medium | Standard Next.js; main work is design/content |
| Admin panel | Medium | CRUD + charts; no novel logic |
| Production infra | Medium | Standard containerized deployment |
| MQL5 EA changes | **Low** | Only URL change needed — no logic changes |

### Biggest Technical Risks

1. **Engine state serialization**: If `GridSettings`/`GridState` schema changes, stored JSON may be incompatible. Mitigation: version field on stored JSON + migration scripts.
2. **EA lock edge cases**: MT5 crash leaves lock held for 15 seconds. Mitigation: force-unlock UI, tune TTL, clear lock on confirmed EA disconnect.
3. **Stripe webhook delivery**: Must be idempotent — same webhook may arrive twice. Mitigation: store `stripe_event_id`, skip if already processed.
4. **Single-server bottleneck on engine**: If engine processing blocks async loop, all users suffer. Mitigation: run engine evaluation in `asyncio.run_in_executor` or separate threads per user.
5. **Meta ID uniqueness enforcement**: Race condition if two accounts try to register same Meta ID simultaneously. Mitigation: DB unique constraint + optimistic locking.

---

## 13. What Can Be Parallelized / Deferred

### Parallelize
- Marketing site can be built while Phase 2 engine work is in progress
- Admin panel UI can be partially scaffolded during Phase 2

### Defer to Post-MVP (v2)
| Feature | Why Defer |
|---|---|
| Google OAuth | JWT auth alone is sufficient for launch |
| 2FA | Adds significant complexity; not critical |
| Discord/Slack webhooks | Nice-to-have; not core |
| Blog | Content work; no impact on core SaaS |
| Symbol multi-instance per user | Major engine change; wait for demand signal |
| Mobile app | Desktop trading tool; mobile not needed at launch |
| Advanced analytics for users | Feature, not critical path |

---

## 14. Deliverables Summary

At platform launch, the user receives:

1. **A running marketing website** with landing, pricing, docs, legal
2. **A working auth system** with email verification and sessions
3. **A subscription system** backed by Stripe with at least 2 plans (monthly + annual)
4. **A Meta ID binding system** that prevents multi-script abuse
5. **A fully isolated, per-user trading engine** — each subscriber gets their own DCA engine instance with persistent state
6. **An enhanced trading dashboard** with subscription status and Meta ID management
7. **A personal API key** per user; EA points to `api.domain.com/ea/{api_key}`
8. **An admin panel** to manage users, subscriptions, and platform health
9. **Transactional emails** for all critical lifecycle events
10. **A production-ready deployment** with HTTPS, monitoring, and backups

---

*Spec version: 1.0 | Status: Planning | Last updated: 2026-04-04*
</parameter>
<parameter name="path">/memories/session/plan.md</parameter>
</invoke>

---

## 14. Deliverables Summary

At platform launch, the user receives:

1. **A running marketing website** with landing, pricing, docs, legal
2. **A working auth system** with email verification and sessions
3. **A subscription system** backed by Stripe with at least 2 plans (monthly + annual)
4. **A Meta ID binding system** that prevents multi-script abuse
5. **A fully isolated, per-user trading engine** — each subscriber gets their own DCA engine instance with persistent state
6. **An enhanced trading dashboard** with subscription status and Meta ID management
7. **A personal API key** per user; EA points to `api.domain.com/ea/{api_key}`
8. **An admin panel** to manage users, subscriptions, and platform health
9. **Transactional emails** for all critical lifecycle events
10. **A production-ready deployment** with HTTPS, monitoring, and backups

---

*Spec version: 1.0 | Status: Planning | Last updated: 2026-04-04*
</parameter>
<parameter name="path">/memories/session/plan.md</parameter>
</invoke>