# MISSION DIRECTIVE: ARCHITECTURE & EXECUTION PLAN
**Role:** You are an Elite Principal Software Architect and Lead Technical Project Manager. 
**Objective:** Create a foolproof, hyper-detailed, step-by-step execution plan for an AI Coding Agent to convert an existing single-tenant MetaTrader 5 (MT5) algorithmic trading script into a fully operational, multi-tenant "Professional SaaS" platform.

## 1. CURRENT STATE VS. TARGET STATE
**Current State:** 
We have a working Python backend running a DCA (Dollar Cost Averaging) trading engine (`DcaEngine`). Currently, the MT5 Expert Advisor (EA) is manually whitelisted by IP. The EA sends tick data to the server, the server processes it, and sends trade commands back. It is a single-user singleton instance.

**Target State:** 
A multi-tenant SaaS where the exact same `.mq5` EA file is distributed to all users. The backend API is entirely unified (no unique URLs per user). The system identifies which user the tick data belongs to by reading the `account_id` (MT5 account number) included in the JSON tick payload. 

## 2. STRICT SCOPE (PACKAGE C: THE PROFESSIONAL SAAS)
The execution plan must ONLY cover the features listed below. Do not over-engineer or add features outside this scope.

### A. Authentication & Core Infrastructure
* Email/Password Auth with JWT (Access & Refresh tokens via HTTP-only cookies).
* Email verification (via Resend/SendGrid API) and Password Reset flow.
* Migration from SQLite/Single-state to PostgreSQL (multi-tenant safe) + Redis (caching/locks).

### B. The Multi-Tenant Engine Engine (CRITICAL)
* Refactor the global `DcaEngine` into an `EngineManager` class (a factory that spins up isolated instances per user).
* Implement Redis locking (`ea_lock:{user_id}`) with a 15-second TTL. If a user connects a second MT5 terminal, it must return a `409 CONFLICT` + a `STOP` command to the EA.
* **State Persistence:** Engine state (grids, rows) must be serialized to a PostgreSQL `engine_states` table on every tick (async) to survive server restarts.

### C. MT5 Identity Binding
* Users register their numeric MT5 Account ID in their dashboard.
* The server drops any EA tick request with an unregistered/inactive MT5 ID (401 Unauthorized).

### D. Subscriptions & Billing (Paystack + Admin Manual Override)
* Integrate Paystack for automated billing.
* **Pricing Model Constraint:** There are exactly THREE plans. All plans have 100% identical feature access. The *only* difference is time duration (e.g., 1-Month, 3-Month, 12-Month).
* **Manual Admin Override:** The Admin Dashboard MUST include a feature allowing the admin to view the user list, click a user, and manually select/grant one of the 3 time-period plans without requiring a Paystack payment.

### E. Frontend Interfaces
1. **Marketing Site (Next.js):** Landing page, features, pricing table, docs (setup instructions), legal pages.
2. **User Dashboard (React SPA):** The existing trading dashboard wrapped in authentication. Plus: Account settings, MT5 ID registration, billing history/invoices, and active session management.
3. **Admin Panel (React SPA):** Protected by `admin` role. Search/filter users, view user details, suspend/unsuspend, and the manual subscription granting tool.

## 3. TECH STACK MANDATE
* **Backend:** FastAPI (Python), SQLAlchemy, PostgreSQL, Redis, Celery (for async emails/expiry checks).
* **Frontend Apps:** React (Vite) for User/Admin Dashboard. Next.js for Marketing site.
* **Payments:** Paystack API (REST + Webhooks with HMAC-SHA512 verification).

## 4. INSTRUCTIONS FOR THE PLANNING AGENT
You must output a highly granular, sequential execution plan designed for an AI Coding Agent to follow blindly. Omissions are unacceptable. 

Your output MUST be structured in the following format:

**PHASE 1: Database Schema & API Contracts**
* Write out the exact PostgreSQL schema (Tables: Users, MetaAccounts, EngineStates, Plans, Subscriptions, Invoices).
* Detail the precise logic for the `POST /ea/tick` API endpoint (the routing logic from payload -> DB lookup -> lock check -> engine instance).

**PHASE 2: Backend Foundation & Auth (File-by-file tasks)**
* Detail exactly which files to create/modify in the FastAPI backend for Auth, JWT, and Email sending.

**PHASE 3: Engine Multi-Tenancy Refactor (The Hardest Part)**
* Detail the transition from singleton to `EngineManager`. Provide the architectural pattern for loading state from Postgres -> Memory -> Upserting back to Postgres asynchronously.

**PHASE 4: Subscription Logic & Paystack Webhooks**
* Detail the flow for Paystack checkout, webhook idempotency handling, and the logic for the Admin Manual Subscription Grant.

**PHASE 5: Frontend Dashboards & Next.js Site**
* Provide the route structure and component hierarchy for the React User App, React Admin App, and Next.js Marketing App.

**Crucial Directive:** At every step, explicitly state *how* the coding agent should test that the specific step is complete before moving to the next one. Anticipate race conditions in the MT5 lock and webhook idempotency, and provide the exact mitigation strategy the coder must use.

Begin the plan now.