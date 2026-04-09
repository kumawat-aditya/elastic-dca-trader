# ELASTIC DCA TRADER — SAAS PLATFORM BLUEPRINT

> **Version 1.1 — 2026-04-04**
> Payments: Paystack | Auth: JWT email/password | EA: Single shared endpoint, Meta ID resolution

---

## Table of Contents

1. [What This Platform Is](#1-what-this-platform-is)
2. [Feature Inventory](#2-feature-inventory)
3. [Pages Inventory](#3-pages-inventory)
4. [Technical Architecture](#4-technical-architecture)
5. [Database Schema](#5-database-schema)
6. [API Design](#6-api-design)
7. [MQL5 EA Changes](#7-mql5-ea-changes)
8. [Multi-Tenancy Engine Design](#8-multi-tenancy-engine-design)
9. [Security Hardening](#9-security-hardening)
10. [Infrastructure](#10-infrastructure)
11. [Delivery Phases & Time Estimates](#11-delivery-phases--time-estimates-solo-developer)
12. [Complexity Assessment](#12-complexity-assessment)
13. [What Can Be Parallelized / Deferred](#13-what-can-be-parallelized--deferred)
14. [Deliverables Summary](#14-deliverables-summary)
15. [Deliverable Packages & Pricing Tiers](#15-deliverable-packages--pricing-tiers)

---

## 1. What This Platform Is

A subscription-based SaaS that lets retail traders connect their MetaTrader 5 terminal to a cloud-hosted Elastic DCA trading engine. The trader installs the provided `.mq5` EA (Expert Advisor) on one chart — the same EA file for all users, no personalization needed. The EA automatically sends the trader's MT5 account ID with every heartbeat, and the server uses that ID to identify which subscriber it belongs to. The cloud engine handles all trading logic per user in isolation. The dashboard gives real-time visibility and control. Subscriptions gate access with hard enforcement on the server side.

**What exists today (the engine):** A Python state machine that receives live market data from MT5 every second and tells it what trades to open/close. Two independent DCA grids (buy side + sell side) with configurable rows, TP/SL, hedging, and cyclic mode. A React dashboard for live control.

**What needs to be built:** Multi-tenancy, user accounts, subscriptions (Paystack), a marketing website, enforced single-script-per-user, and an admin control panel.

---

## 2. Feature Inventory

### 2.1 Authentication & Identity

| Feature                     | Description                                                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------- |
| Email/Password Registration | Standard signup with unique email requirement                                                 |
| Email Verification          | Verification link sent on signup; unverified users can browse but cannot use trading features |
| Login / Logout              | JWT access token (15-min expiry) + refresh token (30-day, stored in httpOnly cookie)          |
| Forgot Password             | Sends a time-limited reset link to the registered email                                       |
| Password Reset              | Token-validated form to set a new password                                                    |
| Session Management          | View all active login sessions, revoke individual sessions                                    |
| Role System                 | `user` and `admin` roles stored on user record                                                |
| Optional: Google OAuth      | One-click sign-in; links accounts by matching email _(Post-MVP)_                              |

> **Not included:** TOTP 2FA, SMS-based verification, or hardware keys — kept simple by design.

---

### 2.2 Subscription & Billing (Paystack)

| Feature                    | Description                                                                                                                                                                                  |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Plan Tiers                 | Minimum: Free Trial, Monthly, Annual. Can add Quarterly anytime                                                                                                                              |
| Paystack Integration       | Transaction initialization, subscription management, webhook processing                                                                                                                      |
| Free Trial                 | Configurable N-day trial with full feature access. No card required variant OR card-required-with-auto-charge variant                                                                        |
| Subscription Creation      | User selects plan → backend calls Paystack `/transaction/initialize` with plan code → user is redirected to Paystack-hosted payment page → on success, subscription is created automatically |
| Payment Verification       | After Paystack redirect, backend calls `/transaction/verify/{reference}` to confirm payment before granting access                                                                           |
| Plan Upgrade/Downgrade     | Disable current Paystack subscription → create new subscription at new plan level (Paystack does not natively support prorated upgrades)                                                     |
| Subscription Cancellation  | Calls Paystack `/subscription/disable`; user retains access until `current_period_end`                                                                                                       |
| Grace Period               | If renewal payment fails, configurable N-day grace before subscription is suspended                                                                                                          |
| Invoice History            | All charge events stored in platform database from Paystack webhooks; displayed in user account                                                                                              |
| Payment Method Management  | Paystack `update_authorization` API; no pre-built portal (must be custom built — adds ~3–5 days vs having a pre-built portal)                                                                |
| Webhook Handler            | Processes Paystack events: `charge.success`, `subscription.create`, `subscription.disable`, `invoice.payment_failed`, `invoice.update`                                                       |
| Pre-expiry Reminder Emails | Celery scheduled tasks send trial/subscription expiry warnings at 3 days before end                                                                                                          |

> **Paystack vs alternatives:** Paystack supports NGN natively and many African markets; also accepts international cards. If targeting a global audience with very high USD volume, evaluate whether Paystack's international card acceptance rates are sufficient for your market.

---

### 2.3 Meta ID (MT5 Account) Binding System

This is the **core enforcement mechanism** that replaces the previous zero-auth, single-user model. The EA is the same file for every user — identification happens automatically through the MT5 account ID embedded in every ping.

| Feature                  | Description                                                                                                                                                                                                                                                                                                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Meta ID Registration     | User enters their MT5 numeric account ID (visible in the MT5 terminal top bar) into the platform's "MT5 Account" settings page. The platform records this ID against their user account                                                                                                                                               |
| Unique Binding           | One MT5 account ID is bound to exactly one platform account. If a second user tries to register the same ID, they are rejected with a clear error message                                                                                                                                                                             |
| How Identification Works | The EA sends `account_id` (MT5 account number) in every tick payload to `POST /ea/tick`. The server looks up which registered user owns that `account_id`. No key in the URL. No personalized EA file needed                                                                                                                          |
| Unregistered IDs         | If an account ID arrives at `/ea/tick` and is not registered to any user, the request is silently dropped with a 401. Unknown IDs are rate-limited by source IP to prevent brute-force scanning                                                                                                                                       |
| Single-Script Lock       | When a registered EA begins sending ticks, the server acquires a Redis key `ea_lock:{user_id}` with a 15-second TTL. Every subsequent tick from that same user refreshes the TTL. If a second MT5 terminal for the same user pings the server while the lock is held, it receives a `409 CONFLICT` response and is instructed to stop |
| Lock Override            | User can click "Force Disconnect" on the dashboard to immediately release the lock — useful when MT5 crashed and the 15-second timeout feels too long                                                                                                                                                                                 |
| Meta ID Change           | User can only update their Meta ID when no active EA session is running (lock must be free). Previous Meta ID is archived, not deleted (for audit)                                                                                                                                                                                    |
| Meta ID Verification     | On every tick, `tick.account_id` is matched against the user's registered `meta_account_id`. Any mismatch is rejected — prevents accidental or malicious cross-tenant interference                                                                                                                                                    |
| EA Setup Instructions    | Platform shows clear instructions: download the EA, open MT5, attach to one chart, set `InpServerURL = https://api.yourdomain.com`. No unique credentials needed per user                                                                                                                                                             |

---

### 2.4 Multi-Tenant Trading Engine

| Feature                  | Description                                                                                                                                                                                                           |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Per-User Engine Instance | `EngineManager` maintains a `dict[user_id → DcaEngine]`. Engines are created when a user's EA first connects after registration and destroyed when the subscription expires                                           |
| Engine State Persistence | After every tick evaluation, the engine's `GridSettings` and `GridState` are serialized to the `engine_states` PostgreSQL table. Server restart fully restores all active users' states — no data loss                |
| Per-User Presets         | The existing `presets` table gains a `user_id` foreign key. Users cannot see, load, or modify other users' presets                                                                                                    |
| Per-User WebSocket Room  | WebSocket connections are authenticated using the JWT at connection time. `SystemState` broadcasts go only to that specific user's connected sessions                                                                 |
| Subscription Enforcement | Before processing any tick, the server checks `user.subscription_status` from a Redis 5-second cache. Expired subscription → engine is paused, EA receives empty action list, dashboard shows access-suspended banner |
| EA Timeout Handling      | Existing `check_ea_timeout()` logic is preserved per-user; if a user's EA goes silent for `EA_TIMEOUT_SECONDS`, only that user's grids are hard-reset                                                                 |

---

### 2.5 Real-Time Trading Dashboard

Enhanced version of the existing React dashboard:

| Feature                       | Description                                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| All Existing Features         | Grid tables (buy/sell sides), row controls, TP/SL configuration, presets, hedge management — all unchanged in functionality                             |
| EA Connection Status          | Shows `Connected` / `Disconnected` + last ping timestamp                                                                                                |
| Subscription Status Banner    | Prominently displays plan name, days remaining, and renewal date. Shows "Suspended" state with upgrade CTA if subscription is lapsed                    |
| Meta ID Status Panel          | Shows registered MT5 account ID, EA lock status (Active / Free), Force Disconnect button                                                                |
| Quick Stats Strip             | Today's cumulative P&L, total open position count, account equity delta since session start                                                             |
| Persistent State on Reconnect | Because engine state is stored in DB, refreshing the browser or reopening the dashboard shows the exact same grid state — no data loss on browser close |
| Alert History                 | Last 50 triggered row alerts are stored and displayed in a dedicated view (with timestamp, side, row index, price)                                      |

---

### 2.6 Account Management Pages

| Feature            | Description                                                                                                                   |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| Profile            | Name, email, timezone preference                                                                                              |
| Security           | Change password; view all active login sessions with device/IP; revoke individual sessions                                    |
| MT5 Account        | Register / update MT5 account ID; view current lock status; Force Disconnect button; download EA + configuration instructions |
| Subscription       | Current plan card, billing cycle, days remaining, upgrade/downgrade CTA, cancellation flow                                    |
| Billing & Invoices | Invoice table showing date, amount, status (paid/failed); populated from Paystack webhook events                              |

---

### 2.7 Marketing & Landing Site

| Feature         | Description                                                                                      |
| --------------- | ------------------------------------------------------------------------------------------------ |
| Landing Page    | Hero section, product overview, key features, social proof/testimonials, CTA buttons             |
| Pricing Page    | Plan comparison cards, monthly/annual billing toggle (with savings callout), FAQ section         |
| Features Page   | Deep-dive explanation of DCA strategy, grid trading visualization, use cases                     |
| Documentation   | Getting started guide, EA installation and configuration, dashboard walkthrough, troubleshooting |
| About / Contact | Team overview, support contact form or Discord community link                                    |
| Legal Pages     | Terms of Service, Privacy Policy, Cookie Policy                                                  |

---

### 2.8 Admin Panel

| Feature                 | Description                                                                                                           |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Overview Dashboard      | MRR, total active subscribers, new signups (chart), trial conversions, churn rate                                     |
| User Management         | Searchable/filterable user table; view user detail; suspend/unsuspend; manually extend subscription; impersonate user |
| Subscription Management | Filter by status (active, trialing, past_due, cancelled); manually grant or revoke access                             |
| Plan Configuration      | Create, edit, deactivate subscription plans; update Paystack plan codes; set feature flags per plan                   |
| Platform Health         | Live count of EA connections, engine instances in memory, Redis status, DB connection health                          |
| Audit Log               | Timestamped record of all admin actions (who did what, to which user)                                                 |

---

### 2.9 Notification System

| Feature                       | Description                                                                                           |
| ----------------------------- | ----------------------------------------------------------------------------------------------------- |
| Email: Verify Account         | Sent on registration; re-sendable from account page                                                   |
| Email: Welcome                | Sent after successful email verification                                                              |
| Email: Password Reset         | Time-limited reset link                                                                               |
| Email: Trial Expiry Warning   | Sent 3 days before trial ends, via Celery scheduled task                                              |
| Email: Payment Failed         | Sent when `invoice.payment_failed` webhook fires                                                      |
| Email: Subscription Cancelled | Sent when subscription is disabled                                                                    |
| Email: Payment Receipt        | Sent on `charge.success` for every successful renewal                                                 |
| In-App Toast Notifications    | Enhanced existing toast system — EA connect/disconnect, row alerts, TP/SL hits, subscription warnings |

---

## 3. Pages Inventory

### Marketing Site (Next.js — server-rendered for SEO)

| Route                   | Page                | Purpose                                                            |
| ----------------------- | ------------------- | ------------------------------------------------------------------ |
| `/`                     | Landing             | Hero, features overview, testimonials, pricing teaser, sign-up CTA |
| `/pricing`              | Pricing             | Plan cards, monthly/annual toggle, feature comparison table, FAQ   |
| `/features`             | Features            | Detailed DCA / grid trading explanation, animated visualizations   |
| `/docs`                 | Documentation Index | Links to all guides                                                |
| `/docs/getting-started` | Getting Started     | Step-by-step: subscribe → register MT5 ID → download EA → connect  |
| `/docs/ea-setup`        | EA Setup Guide      | Download EA, attach to MT5 chart, configure `InpServerURL`         |
| `/docs/dashboard`       | Dashboard Guide     | Controls, settings, preset system explained                        |
| `/about`                | About               | Mission, contact info                                              |
| `/contact`              | Contact             | Support enquiry form                                               |
| `/legal/terms`          | Terms of Service    | Full ToS legal copy                                                |
| `/legal/privacy`        | Privacy Policy      | GDPR-aligned privacy copy                                          |
| `/legal/cookies`        | Cookie Policy       | Cookie disclosure                                                  |

### Auth Pages

| Route                    | Page                 | Purpose                                           |
| ------------------------ | -------------------- | ------------------------------------------------- |
| `/register`              | Sign Up              | Email, password, name                             |
| `/login`                 | Sign In              | Email + password; "Forgot password" link          |
| `/verify-email`          | Verification Holding | Shows "check your inbox" state, resend button     |
| `/verify-email/:token`   | Verification Handler | Validates token, redirects to `/dashboard`        |
| `/forgot-password`       | Forgot Password      | Email submission → sends reset link               |
| `/reset-password/:token` | Password Reset       | New password form; validates token, checks expiry |

### App — Trading Dashboard (React SPA)

| Route               | Page           | Purpose                                                       |
| ------------------- | -------------- | ------------------------------------------------------------- |
| `/dashboard`        | Main Dashboard | Full trading dashboard with buy/sell grids, controls, presets |
| `/dashboard/alerts` | Alert History  | Log of all triggered row alerts                               |

### App — Account Management

| Route                   | Page               | Purpose                                                                      |
| ----------------------- | ------------------ | ---------------------------------------------------------------------------- |
| `/account`              | Account Overview   | Quick summary card: plan, meta ID status, recent activity                    |
| `/account/profile`      | Profile Settings   | Name, email, timezone                                                        |
| `/account/security`     | Security           | Password change, active sessions list, session revocation                    |
| `/account/meta-account` | MT5 Account        | Register/view/update Meta ID; EA setup instructions; Force Disconnect button |
| `/account/subscription` | Subscription       | Current plan, upgrade/downgrade, cancel flow                                 |
| `/account/billing`      | Billing & Invoices | Invoice history table, update payment method link                            |

### Checkout Flow

| Route               | Page           | Purpose                                                                  |
| ------------------- | -------------- | ------------------------------------------------------------------------ |
| `/checkout`         | Plan Selection | Plan cards with "Subscribe" CTA; redirects to Paystack payment page      |
| `/checkout/success` | Success        | Post-payment confirmation; next-step CTA (register MT5 ID → download EA) |
| `/checkout/cancel`  | Cancelled      | Returns user to pricing page                                             |

### Admin Panel (protected by `admin` role)

| Route                  | Page              | Purpose                                                                 |
| ---------------------- | ----------------- | ----------------------------------------------------------------------- |
| `/admin`               | Overview          | MRR chart, active users, new signups, churn gauge                       |
| `/admin/users`         | User List         | Searchable table: email, plan, status, joined date; row actions         |
| `/admin/users/:id`     | User Detail       | Full profile, subscription history, EA activity log, impersonate button |
| `/admin/subscriptions` | Subscription List | All subs by status: active, trialing, past_due, cancelled               |
| `/admin/plans`         | Plan Manager      | CRUD for subscription plans and Paystack plan codes                     |
| `/admin/health`        | Platform Health   | Live metrics: engine count, EA connections, Redis, DB                   |
| `/admin/audit`         | Audit Log         | Searchable admin action log                                             |

---

## 4. Technical Architecture

### 4.1 Repository Structure (Monorepo)

```
elastic-dca-saas/
├── apps/
│   ├── server/           # FastAPI — trading API + auth + billing
│   ├── web/              # React SPA — dashboard + account pages  (existing, enhanced)
│   └── marketing/        # Next.js — landing/marketing site        (NEW)
├── packages/
│   └── shared-types/     # TypeScript interfaces shared between web/ and marketing/
├── scripts/
│   └── automation.mq5    # MQL5 EA — same file for all users, updated server URL only
├── infra/
│   ├── docker/           # Dockerfiles per service
│   ├── nginx/            # Reverse proxy config
│   └── aws/              # Optional IaC
├── docs/
└── .env.example
```

### 4.2 Technology Stack

| Layer            | Technology                                                    | Reason                                                                    |
| ---------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Trading API      | FastAPI (Python 3.12)                                         | Existing; keep to avoid rewrite                                           |
| Auth             | `python-jose` (JWT) + `passlib[bcrypt]`                       | Standard; works with FastAPI's dependency system                          |
| ORM              | SQLAlchemy 2.x + Alembic                                      | Extend existing; add proper migrations                                    |
| Database         | PostgreSQL 16                                                 | Replace SQLite; multi-tenant safe, concurrent writes, JSON columns        |
| Cache / Locks    | Redis 7                                                       | EA single-script lock, subscription status cache, refresh token blocklist |
| Task Queue       | Celery + Redis broker                                         | Async email delivery, scheduled expiry checks                             |
| Payment          | Paystack (Python `requests` + HMAC-SHA512 webhook validation) | No official Python SDK needed; Paystack REST API is clean and simple      |
| Email            | Resend or SendGrid                                            | Transactional emails via SMTP or HTTP API                                 |
| Marketing Site   | Next.js 14 (App Router)                                       | SSR for SEO; React familiarity                                            |
| Dashboard        | React 18 + Vite                                               | Keep existing; add routing + auth wrapper                                 |
| Routing (web)    | React Router v6                                               | Multi-page navigation                                                     |
| HTTP Client      | TanStack Query + Axios                                        | Replace raw `fetch`; caching, loading/error states                        |
| Containerization | Docker + Docker Compose                                       | Dev/production parity                                                     |
| Reverse Proxy    | Nginx                                                         | Route `/ea/*`, `/api/*`, `/` to correct services                          |
| CI/CD            | GitHub Actions                                                | Test + build + deploy pipeline                                            |
| Monitoring       | Sentry (errors)                                               | Error tracking for production                                             |

### 4.3 Domain Architecture

```
yourdomain.com             →  Next.js marketing site
app.yourdomain.com         →  React SPA (dashboard + account pages)
api.yourdomain.com         →  FastAPI backend (all API + EA endpoint)
```

EA `InpServerURL` is set to `https://api.yourdomain.com` (the same URL for every single user — no personalization in the URL).

### 4.4 Paystack Payment Flow

```
                    User selects plan
                          │
                    POST /billing/initialize
                          │
              Paystack /transaction/initialize
              (with plan_code parameter)
                          │
              Returns authorization_url
                          │
         ┌────────────────┘
         │
   User redirected to Paystack hosted payment page
         │
   User enters card details & pays
         │
   Paystack charges card, creates subscription automatically
         │
   ┌─────┴──────────────────────────────────────────┐
   │                                                │
Webhook: charge.success              Redirect: /checkout/success
Webhook: subscription.create         GET /billing/verify/{reference}
         │
   Server updates subscription status in DB
   Celery task sends welcome / receipt email
```

---

## 5. Database Schema

### 5.1 `users`

| Column           | Type                  | Notes                  |
| ---------------- | --------------------- | ---------------------- |
| `id`             | UUID PK               |                        |
| `email`          | VARCHAR unique        |                        |
| `password_hash`  | VARCHAR               | bcrypt, work factor 12 |
| `name`           | VARCHAR               |                        |
| `role`           | ENUM `user` / `admin` | default `user`         |
| `email_verified` | BOOLEAN               | default false          |
| `is_active`      | BOOLEAN               | false = suspended      |
| `created_at`     | TIMESTAMP             |                        |
| `updated_at`     | TIMESTAMP             |                        |

### 5.2 `meta_accounts`

| Column           | Type               | Notes                                                          |
| ---------------- | ------------------ | -------------------------------------------------------------- |
| `id`             | UUID PK            |                                                                |
| `user_id`        | UUID FK → users    |                                                                |
| `mt5_account_id` | BIGINT unique      | Numeric MT5 account number                                     |
| `broker_name`    | VARCHAR            | Captured from EA's tick payload on first successful connection |
| `is_active`      | BOOLEAN            | Only one active per user at a time                             |
| `created_at`     | TIMESTAMP          |                                                                |
| `deactivated_at` | TIMESTAMP nullable | Set when user changes their Meta ID                            |

### 5.3 `email_verifications`

| Column       | Type      | Notes               |
| ------------ | --------- | ------------------- |
| `token`      | UUID PK   |                     |
| `user_id`    | UUID FK   |                     |
| `expires_at` | TIMESTAMP | 24h from creation   |
| `used`       | BOOLEAN   | Token is single-use |

### 5.4 `password_reset_tokens`

| Column       | Type      | Notes            |
| ------------ | --------- | ---------------- |
| `token`      | UUID PK   |                  |
| `user_id`    | UUID FK   |                  |
| `expires_at` | TIMESTAMP | 1h from creation |
| `used`       | BOOLEAN   |                  |

### 5.5 `refresh_tokens`

| Column       | Type      | Notes                                     |
| ------------ | --------- | ----------------------------------------- |
| `id`         | UUID PK   |                                           |
| `user_id`    | UUID FK   |                                           |
| `token_hash` | VARCHAR   | SHA-256 of actual token (never store raw) |
| `expires_at` | TIMESTAMP |                                           |
| `revoked`    | BOOLEAN   | Supports session revocation               |
| `user_agent` | VARCHAR   | Used for "active sessions" display        |
| `ip_address` | VARCHAR   |                                           |

### 5.6 `plans`

| Column                       | Type           | Notes                                                |
| ---------------------------- | -------------- | ---------------------------------------------------- |
| `id`                         | UUID PK        |                                                      |
| `name`                       | VARCHAR        | e.g., "Monthly", "Annual"                            |
| `slug`                       | VARCHAR unique | e.g., `monthly`, `annual`                            |
| `price_monthly_cents`        | INTEGER        | Display only; actual billing is in Paystack          |
| `paystack_plan_code_monthly` | VARCHAR        | e.g., `PLN_xxxx` from Paystack                       |
| `paystack_plan_code_annual`  | VARCHAR        |                                                      |
| `trial_days`                 | INTEGER        | 0 = no trial                                         |
| `features`                   | JSONB          | Feature flags per plan (e.g., max_presets, max_rows) |
| `is_active`                  | BOOLEAN        | Inactive plans not shown on pricing page             |

### 5.7 `subscriptions`

| Column                        | Type           | Notes                                                              |
| ----------------------------- | -------------- | ------------------------------------------------------------------ |
| `id`                          | UUID PK        |                                                                    |
| `user_id`                     | UUID FK        |                                                                    |
| `plan_id`                     | UUID FK        |                                                                    |
| `paystack_subscription_code`  | VARCHAR unique | e.g., `SUB_xxxx` from Paystack                                     |
| `paystack_customer_code`      | VARCHAR        | e.g., `CUS_xxxx` — identifies the user in Paystack                 |
| `paystack_authorization_code` | VARCHAR        | Stored from first `charge.success`; used for subscription renewals |
| `paystack_email_token`        | VARCHAR        | Paystack-issued token for subscription management links            |
| `status`                      | ENUM           | `trialing / active / past_due / cancelled / expired`               |
| `current_period_start`        | TIMESTAMP      |                                                                    |
| `current_period_end`          | TIMESTAMP      | Access granted until this date even after cancellation             |
| `cancel_at_period_end`        | BOOLEAN        |                                                                    |
| `created_at`                  | TIMESTAMP      |                                                                    |
| `updated_at`                  | TIMESTAMP      |                                                                    |

### 5.8 `engine_states`

| Column           | Type           | Notes                                                   |
| ---------------- | -------------- | ------------------------------------------------------- |
| `id`             | UUID PK        |                                                         |
| `user_id`        | UUID FK unique | Exactly one row per user                                |
| `buy_settings`   | JSONB          | Serialized `GridSettings`                               |
| `sell_settings`  | JSONB          | Serialized `GridSettings`                               |
| `buy_state`      | JSONB          | Serialized `GridState`                                  |
| `sell_state`     | JSONB          | Serialized `GridState`                                  |
| `schema_version` | INTEGER        | Increment when model changes; used for migration guards |
| `updated_at`     | TIMESTAMP      |                                                         |

### 5.9 `presets` (modified from existing)

| Column      | Type    | Notes                                                                |
| ----------- | ------- | -------------------------------------------------------------------- |
| `id`        | UUID PK | Changed from INTEGER                                                 |
| `user_id`   | UUID FK | **NEW** — scoped to user; unique constraint is now `(user_id, name)` |
| `name`      | VARCHAR | Unique per user (not globally unique)                                |
| `rows_json` | TEXT    | Existing JSON format unchanged                                       |

### 5.10 `audit_logs`

| Column           | Type             | Notes                                                          |
| ---------------- | ---------------- | -------------------------------------------------------------- |
| `id`             | UUID PK          |                                                                |
| `admin_user_id`  | UUID FK          | Which admin performed the action                               |
| `action`         | VARCHAR          | e.g., `impersonate_user`, `grant_subscription`, `suspend_user` |
| `target_user_id` | UUID FK nullable | Which user was affected                                        |
| `metadata`       | JSONB            | Additional context (old value, new value, etc.)                |
| `created_at`     | TIMESTAMP        |                                                                |

### Redis Key Reference

| Key Pattern            | TTL                       | Purpose                                              |
| ---------------------- | ------------------------- | ---------------------------------------------------- |
| `ea_lock:{user_id}`    | 15s (refreshed each tick) | Single-script enforcement lock                       |
| `sub_status:{user_id}` | 5s                        | Subscription status cache (avoids DB hit every tick) |
| `rate_limit:ea:{ip}`   | 60s                       | EA endpoint rate limiting by source IP               |
| `rate_limit:auth:{ip}` | 60s                       | Login/register rate limiting                         |
| `revoked_tokens:{jti}` | Access token TTL          | Immediately revoke access tokens on logout           |

---

## 6. API Design

### 6.1 EA Endpoint (Critical Change)

**Before:** `POST /api/v1/ea/tick` (single shared endpoint, but open — no user identity)

**After:** `POST /ea/tick` (still a single shared endpoint — but now user identity is resolved from the payload)

```
EA sends:  POST https://api.yourdomain.com/ea/tick
           Body: { "account_id": 12345678, "equity": ..., "positions": [...], ... }

Server:    1. Extract account_id from tick payload
           2. SELECT user_id FROM meta_accounts WHERE mt5_account_id = 12345678
              AND is_active = TRUE
           3. If not found → 401 Unauthorized (drop silently)
           4. Check subscription status (Redis cache first, DB fallback)
              If expired → 403 Forbidden; return empty action list
           5. Acquire / refresh ea_lock:{user_id} in Redis (15s TTL)
              If lock already held → 409 Conflict; respond with STOP instruction
           6. Route tick to engine_manager.get_or_create(user_id)
           7. Return pending actions for that user's engine only
```

**Key point:** The URL is the same for every user. The MT5 account number in the payload is what identifies whose engine to use. No credentials in the URL, no personalized EA file.

### 6.2 Dashboard WebSocket

**Before:** `WS /api/v1/ui/ws` (completely open)

**After:** `WS /ws?token={jwt_access_token}`

Server validates the JWT at connection time, extracts `user_id`, adds the socket to `user_rooms[user_id]`. All state broadcasts are scoped to that user's room. Multiple browser tabs for the same user are all supported simultaneously.

### 6.3 Auth Endpoints (New)

```
POST   /auth/register                  # Create account
POST   /auth/login                     # Returns access token (response body) + refresh token (httpOnly cookie)
POST   /auth/logout                    # Revoke refresh token; add access token JTI to Redis blocklist
POST   /auth/refresh                   # Exchange refresh cookie for new access token
POST   /auth/verify-email/{token}      # Validate email verification link
POST   /auth/resend-verification       # Re-send verification email
POST   /auth/forgot-password           # Send password reset link
POST   /auth/reset-password/{token}    # Set new password using reset token
GET    /auth/me                        # Return current user profile (requires auth)
```

### 6.4 Billing Endpoints (Paystack)

```
GET    /billing/plans                  # List all active subscription plans
POST   /billing/initialize             # Calls Paystack /transaction/initialize with plan_code
                                       # Returns { authorization_url, reference }
GET    /billing/verify/{reference}     # Called after Paystack redirect; confirms payment; updates DB
GET    /billing/subscription           # Return current user's subscription details
POST   /billing/cancel                 # Calls Paystack /subscription/disable
GET    /billing/invoices               # Return platform-stored invoice records
POST   /billing/update-card            # Generate Paystack link to update card authorization

POST   /webhooks/paystack              # Paystack webhook receiver
                                       # Validates X-Paystack-Signature (HMAC-SHA512)
                                       # Handles: charge.success, subscription.create,
                                       #          subscription.disable, invoice.payment_failed,
                                       #          invoice.update
                                       # Idempotent: stores paystack_event_id, skips duplicates
```

### 6.5 Account Endpoints

```
GET    /account/me                     # Full profile
PUT    /account/profile                # Update name, timezone
POST   /account/change-password        # Requires current password confirmation
GET    /account/sessions               # List active refresh tokens (sessions)
DELETE /account/sessions/{id}          # Revoke a specific session
GET    /account/meta-account           # Get registered MT5 account + lock status
POST   /account/meta-account          # Register or update MT5 account ID
DELETE /account/meta-account/lock      # Force-release EA Redis lock
```

### 6.6 Admin Endpoints

```
GET    /admin/overview                 # Stats: MRR, signups, churn
GET    /admin/users                    # Paginated user list with filters
GET    /admin/users/{id}               # User detail
PATCH  /admin/users/{id}               # Suspend/unsuspend, change role
POST   /admin/users/{id}/extend        # Manually extend subscription
POST   /admin/users/{id}/impersonate   # Get scoped access token for that user
GET    /admin/subscriptions            # All subscriptions with filters
GET    /admin/plans                    # All plans
POST   /admin/plans                    # Create plan
PUT    /admin/plans/{id}               # Update plan
GET    /admin/health                   # Platform health metrics
GET    /admin/audit                    # Audit log
```

### 6.7 Existing UI Endpoints (Preserved, Protected)

All existing `/api/v1/ui/*` routes remain unchanged in logic, but are now protected by JWT middleware. The `user_id` from the JWT is automatically injected into every DB query so each user only sees their own data.

| What changes                            | What stays the same             |
| --------------------------------------- | ------------------------------- |
| JWT auth required on all routes         | Route paths unchanged           |
| Presets filtered by `user_id`           | All route logic unchanged       |
| WebSocket authentication added          | WebSocket protocol unchanged    |
| Engine calls routed via `EngineManager` | `DcaEngine` internals unchanged |

---

## 7. MQL5 EA Changes

### What Changes

**Only one thing changes for the user:** The value they type into `InpServerURL` when attaching the EA to a chart.

Before: Each user would have needed a unique URL containing their API key.
After: All users type the same URL: `https://api.yourdomain.com`

**No changes to EA logic.** The EA already sends `account_id` (MT5 numeric account number) in every tick payload — this was always there (`TickData.account_id` field). The server now uses this existing field to identify the user. Zero code changes required in the `.mq5` file.

### The EA Setup Flow (Per User)

1. User subscribes on the platform and verifies email
2. User finds their MT5 account number (shown in the MT5 terminal title bar, e.g., `12345678`)
3. User goes to `/account/meta-account` on the platform and enters that number
4. User downloads the `.mq5` file from the platform (same file for everybody)
5. User copies file into `MetaTrader 5 / MQL5 / Experts /` folder
6. User opens MT5, attaches EA to **one** chart, sets:
   - `InpServerURL = https://api.yourdomain.com`
   - Other inputs (magic number, slippage) as preferred
7. EA starts pinging; server identifies the user; engine instance is created

### What Happens if the User Attaches to a Second Chart

1. Second EA starts pinging with the same `account_id`
2. Server resolves same `user_id` from the Meta ID
3. Redis lock is already held (refreshed by the first EA)
4. Server returns `409 CONFLICT` + a `STOP` action
5. The EA should log this and stop sending (requires one small EA addition: handle the STOP action by calling `ExpertRemove()`)

This is the only functional EA code change needed: add handling for a `STOP` action that calls `ExpertRemove()` to self-detach from the chart.

---

## 8. Multi-Tenancy Engine Design

### From Singleton to Factory

The existing `engine.py` exports a single global `engine = DcaEngine()` instance. This works for one user but breaks completely with multiple users — they'd all share the same grid state.

**The change:**

```python
# BEFORE (engine.py)
engine = DcaEngine()  # Global singleton

# AFTER (engine.py — becomes a plain class)
class DcaEngine:
    def __init__(self, user_id: str, saved_state: dict | None = None):
        # If saved_state is provided, restore from it instead of fresh init
        ...
```

### `EngineManager` (new file: `app/services/engine_manager.py`)

```python
class EngineManager:
    _instances: dict[str, DcaEngine]  # user_id → engine

    async def get_or_create(self, user_id: str, db: Session) -> DcaEngine:
        if user_id not in self._instances:
            # Try to restore from DB
            saved = db.query(EngineState).filter_by(user_id=user_id).first()
            state = saved.to_dict() if saved else None
            self._instances[user_id] = DcaEngine(user_id=user_id, saved_state=state)
        return self._instances[user_id]

    async def persist_state(self, user_id: str, db: Session):
        engine = self._instances.get(user_id)
        if engine:
            # Upsert engine_states row with current grid settings + state JSON

    def destroy(self, user_id: str):
        # Called on subscription expiry; engine removed from memory
        # State already persisted; will be restored if subscription is renewed
```

### State Persistence Strategy

Engine state is persisted **every tick** (async, non-blocking). The write is an UPSERT to `engine_states` where `user_id` is unique.

A `schema_version` integer field guards against incompatible state: if the stored schema version doesn't match the current code version, the state is discarded and the engine starts fresh. The user is notified on the dashboard.

---

## 9. Security Hardening

| Concern                   | Solution                                                                                                 |
| ------------------------- | -------------------------------------------------------------------------------------------------------- |
| CORS                      | Locked to `app.yourdomain.com` and `yourdomain.com` only                                                 |
| JWT signing               | HS256 with a strong random secret (min 256-bit); stored in env/secrets manager                           |
| JWT expiry                | Access token: 15 min; Refresh token: 30 days; logout revokes immediately                                 |
| Password storage          | bcrypt with work factor 12                                                                               |
| Paystack webhooks         | Verify `X-Paystack-Signature` header (HMAC-SHA512 with `PAYSTACK_SECRET_KEY`) for every incoming webhook |
| Webhook idempotency       | Store Paystack event ID; skip processing if already handled                                              |
| EA endpoint rate limiting | Slowapi: max 5 requests/second per source IP on `POST /ea/tick`                                          |
| Auth rate limiting        | Max 5 login attempts/minute per IP; exponential backoff on repeated failures                             |
| SQL injection             | Parameterized queries via SQLAlchemy ORM exclusively; no raw SQL strings                                 |
| XSS                       | React renders safely by design; `Content-Security-Policy` headers via Nginx                              |
| CSRF                      | SameSite=Strict on refresh cookie; state parameter on any OAuth flows                                    |
| Secrets                   | Never committed to source; `.env` for local, environment variables / secrets manager in production       |
| Admin routes              | `role == admin` middleware check + per-handler role assertion (defense in depth)                         |
| Admin audit trail         | Every admin action logged with actor ID, target, action, and timestamp                                   |
| Meta ID spoofing          | Unregistered account IDs are silently dropped; no enumeration of valid IDs possible                      |
| EA lock bypass            | Lock uses Redis atomic `SET NX PX`; no race condition on simultaneous connections                        |

---

## 10. Infrastructure

### Docker Compose (Development)

```yaml
services:
  api: FastAPI on :8000
  web: Vite dev server on :5173
  marketing: Next.js dev server on :3000
  postgres: PostgreSQL 16 on :5432
  redis: Redis 7 on :6379
  worker: Celery worker (emails, scheduled tasks)
```

### Production Architecture (Simple / Solo-Operated)

Recommended for a solo-operated platform starting out:

```
Cloudflare (SSL termination, DDoS, CDN for static assets)
    └── Single VPS (Hetzner / DigitalOcean — 4 vCPU, 8 GB RAM)
         ├── Nginx (reverse proxy)
         │    ├── api.yourdomain.com  → FastAPI (uvicorn, port 8000)
         │    └── app.yourdomain.com  → React SPA (static files)
         ├── Celery worker process
         ├── Managed PostgreSQL (provider add-on, or self-hosted)
         └── Managed Redis (Upstash free tier or provider add-on)

Marketing site (yourdomain.com):
    └── Vercel or Netlify (Next.js deploy, free tier sufficient at launch)
```

### Environment Variables Required

```bash
# Application
SECRET_KEY=                    # JWT signing secret (min 256-bit random)
DATABASE_URL=                  # postgresql+asyncpg://...
REDIS_URL=                     # redis://...

# Paystack
PAYSTACK_SECRET_KEY=           # sk_live_xxx
PAYSTACK_PUBLIC_KEY=           # pk_live_xxx  (used in frontend if doing inline checkout)
PAYSTACK_WEBHOOK_SECRET=       # Separate webhook secret from Paystack dashboard

# Email
EMAIL_PROVIDER_API_KEY=        # Resend or SendGrid API key
EMAIL_FROM=                    # noreply@yourdomain.com

# EA Engine (existing)
EA_TIMEOUT_SECONDS=10
HEDGE_TP_PCT=100.0
HEDGE_SL_PCT=50.0

# App URLs
FRONTEND_URL=                  # https://app.yourdomain.com
MARKETING_URL=                 # https://yourdomain.com
```

---

## 11. Delivery Phases & Time Estimates (Solo Developer)

Assumes ~6–8 hours/day of focused work. Does not include time for design decisions, requirements clarification, or deployment incidents.

### Phase 1 — Foundation (4–5 weeks)

| Task                                                                      | Est.   |
| ------------------------------------------------------------------------- | ------ |
| Monorepo restructure, Docker Compose, PostgreSQL migration, Alembic setup | 3 days |
| User model, auth endpoints (register / login / verify / forgot / reset)   | 4 days |
| JWT middleware, refresh token rotation, session revocation                | 3 days |
| Password reset & verification email flows (Resend/SendGrid)               | 2 days |
| Frontend: React Router, auth pages (login / register / forgot / reset)    | 4 days |
| Auth guards, protected routes, Axios interceptor for token refresh        | 3 days |
| End-to-end auth flow testing                                              | 2 days |
| **Milestone:** User can register, verify email, log in, and log out       |        |

### Phase 2 — Multi-Tenant Engine (5–7 weeks)

| Task                                                                | Est.   |
| ------------------------------------------------------------------- | ------ |
| Remove `DcaEngine` singleton; make it instantiable per user         | 2 days |
| `EngineManager` class: create, restore, persist, destroy engines    | 4 days |
| `engine_states` table + state persistence on every tick (async)     | 3 days |
| EA endpoint refactor: Meta ID resolution + Redis single-script lock | 4 days |
| Meta ID registration UI + Force Disconnect feature                  | 2 days |
| WebSocket authentication (JWT at connection) + per-user rooms       | 3 days |
| Subscription enforcement middleware (Redis cache, DB fallback)      | 2 days |
| Presets: add `user_id` scoping + fix unique constraint              | 1 day  |
| Integration testing: two users running engines in parallel          | 4 days |
| **Milestone:** Two users can run independent engines simultaneously |        |

### Phase 3 — Subscriptions & Billing / Paystack (4–6 weeks)

| Task                                                                            | Est.   |
| ------------------------------------------------------------------------------- | ------ |
| Paystack account setup; create products / plans in Paystack dashboard           | 1 day  |
| `plans` and `subscriptions` tables; Paystack customer creation on register      | 2 days |
| `/billing/initialize` endpoint (transaction init + plan code)                   | 2 days |
| `/billing/verify` endpoint (post-redirect payment confirmation)                 | 1 day  |
| Paystack webhook handler (all 5 event types, with idempotency)                  | 4 days |
| Custom billing management UI (no pre-built Paystack portal — must custom build) | 5 days |
| Subscription enforcement across all protected endpoints                         | 2 days |
| Trial period logic + pre-expiry reminder Celery tasks                           | 3 days |
| Frontend: pricing page, checkout flow, subscription pages, invoice table        | 5 days |
| End-to-end testing: subscribe → trade → cancel → re-subscribe                   | 3 days |
| **Milestone:** Full subscribe → trade → cancel flow working                     |        |

### Phase 4 — Marketing Site (3–4 weeks)

| Task                                                             | Est.   |
| ---------------------------------------------------------------- | ------ |
| Next.js project setup, Tailwind CSS, shared design tokens        | 2 days |
| Landing page (hero, features, social proof, CTA)                 | 4 days |
| Pricing page (plan cards, toggle, feature comparison, FAQ)       | 2 days |
| Features page                                                    | 2 days |
| Documentation pages (getting started, EA setup, dashboard guide) | 4 days |
| About + Contact pages                                            | 1 day  |
| Legal pages (ToS, Privacy, Cookies)                              | 2 days |
| SEO: metadata, `sitemap.xml`, `robots.txt`, Open Graph images    | 1 day  |
| **Milestone:** Public website live and indexable                 |        |

### Phase 5 — Admin Panel (3–4 weeks)

| Task                                                        | Est.   |
| ----------------------------------------------------------- | ------ |
| Admin role middleware + admin route protection              | 1 day  |
| Admin overview dashboard (MRR, signups chart, churn)        | 3 days |
| User list + search + detail + suspend/unsuspend             | 3 days |
| Subscription management + manual grant/extend               | 2 days |
| Platform health page (live metrics)                         | 2 days |
| Audit log                                                   | 2 days |
| **Milestone:** Admin can manage all users and subscriptions |        |

### Phase 6 — Hardening & Launch (3–4 weeks)

| Task                                                                         | Est.   |
| ---------------------------------------------------------------------------- | ------ |
| Security audit: CORS lockdown, rate limiting on all routes, input validation | 3 days |
| Error handling: user-facing error pages, Sentry integration                  | 2 days |
| EA tick endpoint load test (simulate 50+ concurrent users)                   | 1 day  |
| CI/CD pipeline (GitHub Actions: lint + test + build + deploy)                | 2 days |
| Production server setup (VPS provisioning, Nginx, SSL, backups)              | 3 days |
| Smoke test all user journeys in production                                   | 2 days |
| **Milestone:** Platform live, accepting real subscribers                     |        |

### Total Solo Estimate

| Phase                        | Minimum      | Maximum      |
| ---------------------------- | ------------ | ------------ |
| Phase 1: Foundation          | 4 weeks      | 5 weeks      |
| Phase 2: Multi-Tenant Engine | 5 weeks      | 7 weeks      |
| Phase 3: Paystack Billing    | 4 weeks      | 6 weeks      |
| Phase 4: Marketing Site      | 3 weeks      | 4 weeks      |
| Phase 5: Admin Panel         | 3 weeks      | 4 weeks      |
| Phase 6: Hardening & Launch  | 3 weeks      | 4 weeks      |
| **Total**                    | **22 weeks** | **30 weeks** |

> **Realistic solo timeline: 5.5–7.5 months** of focused daily work.
> Add 20–30% buffer for real-life interruptions, unexpected debugging, and iteration cycles.

---

## 12. Complexity Assessment

### By Component

| Component                    | Complexity   | Notes                                                                  |
| ---------------------------- | ------------ | ---------------------------------------------------------------------- |
| Auth system                  | Medium       | Well-understood patterns; libraries handle the hard parts              |
| JWT + refresh token rotation | Medium       | Fiddly but thoroughly documented                                       |
| Paystack integration         | Medium       | Clean REST API; no SDK needed; custom billing UI adds work             |
| Multi-tenant engine          | **High**     | Biggest architectural lift: singleton → per-user factory + persistence |
| Meta ID system + EA lock     | Medium       | Redis TTL + refresh; logic is clear but must be bulletproof            |
| Engine state persistence     | Medium       | Serialize/restore; risk: schema version drift over time                |
| WebSocket auth + rooms       | Medium       | JWT at upgrade; room management pattern is standard                    |
| Marketing site               | Low–Medium   | Standard Next.js; most work is content and design                      |
| Admin panel                  | Medium       | CRUD + basic charts; no novel technical challenges                     |
| Production infrastructure    | Medium       | Standard Docker + Nginx deployment                                     |
| MQL5 EA changes              | **Very Low** | Add STOP action handler only (~10 lines of MQL5)                       |

### Top Technical Risks

1. **Engine state schema drift** — If `GridSettings` / `GridState` fields change between versions, stored JSON becomes incompatible. Mitigation: `schema_version` field in `engine_states`; migration guard on restore.

2. **EA lock edge cases** — MT5 crash leaves lock held for 15 seconds. If user restarts MT5 quickly, they hit `409 CONFLICT`. Mitigation: Force Disconnect UI clears instantly; 15s TTL is short enough that most users just wait.

3. **Paystack webhook idempotency** — Paystack may deliver the same `charge.success` event more than once. Mitigation: store `paystack_event_id` in a processed-events table; skip any duplicate event ID.

4. **Per-user engine performance** — If many users are active simultaneously and the engine's tick evaluation blocks the async event loop, all users suffer latency. Mitigation: run `engine.update_from_tick()` in `asyncio.run_in_executor` (thread pool) so it doesn't block the event loop.

5. **Meta ID uniqueness race condition** — Two accounts trying to register the same MT5 ID at the exact same millisecond. Mitigation: `UNIQUE` constraint on `meta_accounts.mt5_account_id` at DB level; DB constraint violation is caught and returned as a user-friendly error.

---

## 13. What Can Be Parallelized / Deferred

### Can Be Built in Parallel

- Marketing site (Phase 4) development can begin while Phase 2 engine work is active — they share no dependencies
- Admin panel UI scaffolding can be started during Phase 3

### Defer to Post-MVP (v2)

| Feature                 | Why Defer                                                                   |
| ----------------------- | --------------------------------------------------------------------------- |
| Google OAuth            | Email/password is sufficient for launch; OAuth adds auth library complexity |
| Blog                    | Content work; zero impact on core SaaS functionality                        |
| Advanced user analytics | Feature, not required for monetization                                      |
| Multi-symbol per user   | Major engine redesign; wait for a clear user demand signal                  |
| Mobile app              | Desktop trading tool; mobile adds an entirely separate codebase             |
| PDF invoice generation  | Paystack charges records are sufficient display; PDFs are a polish feature  |

---

## 14. Deliverables Summary

At platform launch, subscribers receive:

1. ✅ **A running marketing website** — landing, pricing, features, documentation, legal pages
2. ✅ **Full user authentication** — register, verify email, login, logout, password reset, session management
3. ✅ **Paystack subscription system** — monthly and annual plans, free trial, payment processing, invoice history, cancellation
4. ✅ **Meta ID binding** — register MT5 account ID; single-script enforcement via Redis lock; force disconnect
5. ✅ **Fully isolated per-user trading engine** — each subscriber's grids, state, and presets are completely private
6. ✅ **Enhanced trading dashboard** — subscription status, Meta ID panel, alert history, all existing controls
7. ✅ **Account management** — profile, security, MT5 account, subscription, billing pages
8. ✅ **Admin panel** — user management, subscription management, platform health, audit log
9. ✅ **Transactional email system** — all lifecycle emails (verify, welcome, reset, expiry, receipts)
10. ✅ **Production-ready deployment** — HTTPS, Docker, Nginx, Cloudflare, monitored, backed up

---

## 15. Deliverable Packages & Pricing Tiers

> This section is a client-facing menu. Each package builds on the last. Prices shown are **suggested development cost ranges** based on an estimated solo developer timeline. Final pricing is set by the developer based on their hourly rate and market.

---

### 📦 Package A — "The Private Tool"

**What you get in plain English:**

You and your team (or a small, private group you control) can log in with email and password. Each person sees only their own trading grids and settings — completely separate from everyone else. Only one MetaTrader 5 terminal per account can be connected at a time to prevent conflicts. The existing trading dashboard works exactly as it does today, just wrapped in proper multi-user accounts.

**What this looks like for a visitor:**
There is no public website. To get access, you (the owner) manually create accounts for people you want to give access to.

**What subscribers can do:**

- Log in with email + password
- Run their own trading engine (buy/sell grids, TP/SL, hedging, cyclic mode)
- Save their own presets
- See real-time grid state and P&L in the dashboard
- Register their MT5 account ID to connect their terminal

**What you as the owner can do:**

- Manually create/delete user accounts
- No dashboard — you'd manage via the database directly

**What it does NOT include:**

- Any payment system (you manage access manually)
- A public website signups can happen on
- Admin control panel
- Automated emails

**Best for:** Internal use, testing the product with a private group, or offering access to clients on a personal arrangement before going public.

**Estimated development time:** 1-2 weeks
**Suggested price range:** 8k-10k

_Why this price:_ This is significant engineering work — converting a single-user tool into a secure multi-user system with proper authentication, data isolation, and Meta ID enforcement. The core multi-tenancy refactor alone is the most technically complex piece of the entire platform.

---

### 📦 Package B — "The Starter SaaS"

**What you get in plain English:**

Everything in Package A, PLUS: people can sign up on their own through a clean simple signup page. You collect subscription payments automatically via Paystack (the signup and payment process is fully automated — you don't need to do anything manual per user). When someone's trial or subscription expires, their access is automatically suspended.

**What this looks like for a visitor:**
A simple landing page explaining what the product is, a pricing page showing your plans, and a signup/login system. A visitor can go from "landing on your site" to "paying subscriber running their first trade" without you lifting a finger.

**What subscribers can do:**
Everything in Package A, PLUS:

- Sign up themselves and go through email verification
- Choose a subscription plan (e.g., monthly or annual)
- Pay via Paystack
- See their subscription status and next renewal date in their account
- See their payment history (invoice list)
- Cancel their subscription anytime

**What you as the owner can do:**

- Collect recurring payments automatically
- (Manual DB access still required to investigate issues — no admin dashboard yet)

**What it does NOT include:**

- Admin control panel with user management UI
- Detailed marketing/features pages
- Full documentation site
- Automated reminder/lifecycle emails (basic emails only: verify, receipt)

**Best for:** Launching your product publicly for the first time and starting to earn revenue with minimal overhead.

**Estimated development time:** 3-4 weeks (includes everything in Package A)
**Suggested price range:** 20k - 25k

_Why this price:_ Adds a complete payment system, subscription lifecycle management, Paystack webhook processing, checkout flows, and a billing UI on top of everything in Package A. The Paystack integration alone requires careful handling of multiple edge cases (webhook idempotency, failed payments, subscription state machine).

---

### 📦 Package C — "The Professional SaaS"

**What you get in plain English:**

Everything in Package B, PLUS: a proper professional marketing website, full account management pages for your users, and an admin control panel so you can manage your subscriber base without touching the database.

**What this looks like for a visitor:**
A polished website with a landing page, a features page that explains what the product does, a pricing table, and clear setup documentation. The site looks like a real SaaS product.

**What subscribers can do:**
Everything in Package B, PLUS:

- A full account settings area: update name, email, password, see active login sessions, revoke sessions
- Clear EA setup instructions in their account (step-by-step: download EA, enter server URL, done)
- Automated emails for trial ending soon, payment failure, subscription cancellation

**What you as the owner can do:**
Everything above, PLUS:

- An admin dashboard where you can see all your users in a list
- Search and filter users by plan, status, join date
- View full detail for any user (plan, subscription history, EA activity)
- Suspend or unsuspend users
- Manually extend someone's subscription (e.g., as a goodwill gesture)
- See a revenue overview: total subscribers, revenue per month, churn

**What it does NOT include:**

- Automated deployment pipeline (CI/CD)
- Performance monitoring / error tracking in production
- Platform health monitoring for the admin
- Blog or advanced SEO content

**Best for:** A serious product launch where you expect to be onboarding real paying customers at moderate scale and need to look professional from day one.

**Estimated development time:** 4-5 weeks (includes everything in Packages A + B)
**Suggested price range:** 29k-34k

_Why this price:_ Adds the marketing website (which requires significant design and content work), a full account management system, comprehensive email notifications, and a complete admin control panel. Each of these is a substantial independent deliverable.

---

### 📦 Package D — "The Full-Scale SaaS"

**What you get in plain English:**

Everything in Package C, PLUS: the kind of operational infrastructure that a serious business needs — automated deployment, error monitoring, production performance management, and a platform health dashboard for you as the operator.

**What this looks like to you as the owner:**
When you push code, it automatically tests, builds, and deploys to your server — no manual deployment steps. If something crashes in production, you get an instant error alert with a full stack trace. You can see in real-time exactly how many users are connected, how the database is performing, and whether any part of the system is under stress.

**What subscribers experience:**
Everything in Package C — no visible difference. The improvements are all on the reliability and operational side.

**What you as the owner can additionally do:**

- View real-time platform health: how many trading engines are running, database response times, Redis status
- See a complete audit trail of all admin actions (who changed what, when)
- Manage subscription plans directly from the admin UI (create, edit, deactivate plans, update pricing)
- Automated deployment: push to GitHub → tests run automatically → deploys to production

**What it does NOT include:**

- Blog / content management
- Multi-symbol trading (one currency pair per account)
- Mobile app

**Best for:** A platform that has grown past the "experiment" stage and is generating real revenue with a user base that requires reliable uptime and professional operations.

**Estimated development time:** 5-7 weeks (includes everything in Packages A + B + C)
**Suggested price range:** 40k-45k

_Why this price:_ Adding CI/CD, Sentry integration, platform health dashboards, and production infrastructure configuration is time-intensive and requires specialized DevOps knowledge. These pieces are critical for reliability but often underestimated in scope.

---

### 📦 Package E — "Enterprise / White-Label Platform"

**What you get in plain English:**

Everything in Package D, PLUS: the ability to present this as completely your own branded product (not derived from any identifiable base). Custom domain, custom color scheme and logo baked into the platform, full legal pages professionally written, a blog system for publishing trading content, and onboarding for a team of operators (not just one admin).

**What makes this different:**

- The entire visual identity is custom — visitors see _your_ brand, not a template
- Multiple admin accounts with different permission levels (e.g., a support agent can view users but cannot manage billing)
- A content management system for the blog (you can publish articles without a developer)
- Google Sign-In ("Continue with Google") for users who prefer it

**Estimated development time:** 8-9 weeks (includes everything in Packages A + B + C + D)
**Suggested price range:** 50k-60k

_Why this price:_ A fully white-labeled, enterprise-grade SaaS with custom design, multi-level admin, CMS integration, and OAuth is a substantial scope increase. The price also reflects the reduced risk for the client: they receive a polished, production-ready platform with a post-launch support window.

---

### 🔧 Individual Feature Add-Ons

> Can be added to any package above. Prices are per feature, on top of the base package cost.

| Feature                          | Plain English Description                                                                                 | Est. Dev Time | Suggested Price    |
| -------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------- | ------------------ |
| **Google Sign-In**               | Users can sign up/log in with their Google account instead of creating a password                         | 3–4 days      | 1k - 2k            |
| **Multi-Symbol Trading**         | Each subscriber can trade multiple currency pairs simultaneously (separate grid instances per symbol)     | 2-3 weeks     | 6k - 8k            |
| **Alert History**                | Dashboard panel showing the last 50 triggered row alerts with timestamps                                  | 2–3 days      | 1k - 1.5k           |
| **User Trade History / Journal** | Log of all past trades per user with date, P&L, symbol — viewable from dashboard                          | 1–2 weeks     | 3k - 4k            |
| **P&L Analytics Charts**         | Visual charts of equity curve, daily P&L, win/loss over time                                              | 1–2 weeks     | 3k - 4k            |
| **Multi-Language Support**       | Platform UI available in multiple languages (requires translated content)                                 | 1–2 weeks     | 2k - 3k            |

---

### 💡 Recommended Starting Combination

If you are building this as a new business and want to validate the market before spending heavily:

> **Start with Package B** and **Alert History** as add-ons.
>
> This gives you: working multi-user auth + automatic Paystack billing + functional trading dashboard + enough operational tooling to manage the server yourself. Total: 21k – 26k and 3-4 weeks.
>
> Upgrade to Package C once you have your first 20–30 paying subscribers and a validated pricing model.

---

_Blueprint version 1.1 | Generated: 2026-04-04 | Status: Planning_
