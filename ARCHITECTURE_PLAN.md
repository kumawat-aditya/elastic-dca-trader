
This plan assumes one shared Vite SPA for user and admin routes, a provider-agnostic email adapter, exactly three active plans stored in PostgreSQL, and one MT5 account binding per user at launch. One technical addition is required for the MT5 lock to be race-safe: the EA payload should keep using `account_id` to identify the user, but also send a per-terminal `terminal_instance_id`; otherwise the server cannot reliably distinguish the original terminal from a second terminal reconnecting under the same account.

**PHASE 1: Database Schema & API Contracts**
1. Freeze the business invariants before coding anything. Enforce exactly three active plans, identical features across all plans, one active MT5 account binding per user, and one active subscription per user. Test: write these rules into the migration and service-layer tests first, then fail any attempt to create a fourth active plan or a second active MT5 binding for the same user.

2. Replace SQLite with PostgreSQL and create the core tables.
- `users`: `id UUID PK`, `email CITEXT UNIQUE`, `password_hash`, `role` (`user|admin`), `email_verified_at`, `is_active`, `is_suspended`, `created_at`, `updated_at`, `last_login_at`.
- `meta_accounts`: `id UUID PK`, `user_id UUID UNIQUE FK users`, `account_id BIGINT UNIQUE`, `is_active`, `created_at`, `updated_at`, `deactivated_at`.
- `engine_states`: `id UUID PK`, `user_id UUID UNIQUE FK users`, `meta_account_id UUID UNIQUE FK meta_accounts`, `state_json JSONB`, `tick_queue_json JSONB`, `pending_actions_json JSONB`, `engine_version BIGINT`, `last_tick_at`, `created_at`, `updated_at`.
- `plans`: `id UUID PK`, `code UNIQUE`, `name`, `duration_days`, `price_kobo`, `currency`, `paystack_plan_code`, `is_active`, `created_at`, `updated_at`.
- `subscriptions`: `id UUID PK`, `user_id FK users`, `plan_id FK plans`, `source` (`paystack|admin`), `status` (`pending|active|expired|cancelled`), `starts_at`, `ends_at`, `granted_by_user_id FK users NULL`, `provider_customer_code`, `provider_subscription_code`, `created_at`, `updated_at`. Add a partial unique index so each user has only one active subscription.
- `invoices`: `id UUID PK`, `user_id FK users`, `subscription_id FK subscriptions NULL`, `plan_id FK plans`, `provider` (`paystack|admin`), `provider_reference UNIQUE NULL`, `amount_kobo`, `currency`, `status` (`pending|paid|failed|waived|refunded`), `period_start`, `period_end`, `paid_at`, `raw_payload JSONB`, `created_at`, `updated_at`.
Test: generate the Alembic migration, run it on an empty Postgres database, then inspect indexes, unique constraints, and foreign keys manually and with tests.

3. Add only the support tables required by the strict scope.
- `user_sessions`: refresh-token hash storage for active session management.
- `email_verification_tokens`: hashed verification tokens with expiry and single-use markers.
- `password_reset_tokens`: hashed reset tokens with expiry and single-use markers.
- `webhook_events`: unique provider event log for Paystack idempotency.
Test: prove that no flow requires plaintext token storage and that duplicate webhook processing is blocked by a unique database constraint, not by in-memory checks.

4. Seed exactly three active plans. Use codes such as `monthly`, `quarterly`, and `annual`, but keep `duration_days` and `price_kobo` editable in the database. Test: add a service-layer test that rejects a fourth active plan and another that proves inactive plans cannot be selected at checkout or via admin grant.

5. Redefine `POST /api/v1/ea/tick` before implementation.
- Request body keeps the current market fields and adds `terminal_instance_id`.
- `200` returns `{"actions":[...]}`.
- Unregistered or inactive MT5 account returns `401` with `{"actions":[{"action":"STOP","reason":"MT5_ACCOUNT_NOT_REGISTERED"}]}`.
- Suspended user returns `403` with `{"actions":[{"action":"STOP","reason":"USER_SUSPENDED"}]}`.
- No active subscription returns `403` with `{"actions":[{"action":"STOP","reason":"SUBSCRIPTION_INACTIVE"}]}`.
- Second MT5 terminal conflict returns `409` with `{"actions":[{"action":"STOP","reason":"EA_ALREADY_CONNECTED"}]}`.
- Unexpected server exceptions still return `200 {"actions":[]}` after logging.
Test: write API-contract tests for every status/body combination before wiring real engine logic.

6. Lock the exact routing logic for `POST /api/v1/ea/tick`.
- Validate payload.
- Normalize and validate `account_id`.
- Lookup `meta_accounts.account_id` where `is_active = true`, joining `users`.
- If no active account mapping exists, return `401 STOP`.
- If user is suspended, return `403 STOP`.
- Resolve active subscription from Redis cache `subscription_status:{user_id}`; on miss, query PostgreSQL and cache for 5 seconds.
- If no active subscription exists, return `403 STOP`.
- Run a Redis Lua script on `ea_lock:{user_id}` with TTL 15 seconds and owner `terminal_instance_id`.
- If lock result is conflict, return `409 STOP`.
- Call `EngineManager.get_or_create(user_id, meta_account_id)`.
- Hydrate from PostgreSQL if the engine is not in memory.
- Process the tick on that user’s engine instance only.
- Pull and return only that engine’s pending actions.
- Enqueue async state persistence to `engine_states`.
Test: implement this as an integration-test matrix with one happy path and one denial test for each branch.

7. Define the supporting backend contracts needed by the dashboards.
- Auth: `register`, `login`, `refresh`, `logout`, `verify-email`, `resend-verification`, `forgot-password`, `reset-password`, `me`.
- Account: `profile`, `mt5-account`, `sessions`, `revoke-session`.
- Billing: `plans`, `checkout`, `subscription`, `invoices`, Paystack webhook.
- Admin: list users, user detail, suspend, unsuspend, manual grant.
- Trading UI: existing UI routes remain but become authenticated and user-scoped.
Test: create an endpoint checklist and require route coverage before frontend work starts.

**PHASE 2: Backend Foundation & Auth (File-by-file tasks)**
1. Upgrade the server dependencies and configuration.
- Modify apps/server/requirements.txt to add PostgreSQL driver, Redis client, Alembic, JWT library, password hashing, Celery, Resend/SendGrid SDKs, and test dependencies.
- Modify apps/server/app/config.py to add `DATABASE_URL`, `REDIS_URL`, JWT secrets, cookie settings, email provider settings, Paystack keys, and Celery settings.
- Modify apps/server/main.py to stop creating SQLite tables directly, initialize shared services, mount new routers, and tighten CORS.
Test: a clean environment should fail fast on missing env vars and boot cleanly when all required settings are present.

2. Replace the DB bootstrap path.
- Modify apps/server/app/database/session.py for PostgreSQL engine/session setup.
- Expand apps/server/app/database/models.py to include all ORM models from Phase 1.
- Create `apps/server/alembic.ini`, `apps/server/alembic/env.py`, and an initial migration under `apps/server/alembic/versions/`.
Test: `alembic upgrade head` must succeed on an empty DB, and the app must work without `Base.metadata.create_all()`.

3. Add the auth/security layer.
- Create `apps/server/app/services/security.py` for password hashing, JWT issue/verify, refresh-token hashing, and secure token generation.
- Create `apps/server/app/services/auth_service.py` for registration, login, refresh, logout, email verification, and password reset orchestration.
- Create `apps/server/app/api/deps.py` for `get_current_user` and `get_current_admin`.
- Create `apps/server/app/models/auth_schemas.py` for auth request/response DTOs.
Test: unit tests must prove hash verification, token expiry, token rotation, and invalid-token rejection.

4. Add provider-agnostic email delivery through Celery.
- Create `apps/server/app/services/email_provider.py`.
- Create `apps/server/app/services/email_resend.py`.
- Create `apps/server/app/services/email_sendgrid.py`.
- Create `apps/server/app/tasks/celery_app.py`.
- Create `apps/server/app/tasks/email_tasks.py`.
- Optionally add HTML templates for verification and reset emails.
Test: mocked provider tests must prove emails enqueue correctly, render the right links, and retry on transient failures.

5. Add persistent session management.
- Create `apps/server/app/services/session_service.py`.
- Create `apps/server/app/services/user_service.py`.
- Use HTTP-only cookies for access and refresh tokens; set `Secure` and `SameSite` by environment.
Test: login must create a `user_sessions` row, refresh must rotate the stored hash, logout must revoke it, and the sessions API must show and revoke sessions without exposing token material.

6. Add the new routers and wire them into FastAPI.
- Create `apps/server/app/routers/auth_api.py`.
- Create `apps/server/app/routers/account_api.py`.
- Create `apps/server/app/routers/billing_api.py`.
- Create `apps/server/app/routers/admin_api.py`.
- Modify apps/server/app/routers/ui_api.py to require auth and scope every action to `current_user.id`.
- Modify apps/server/app/routers/ea_api.py to use account lookup, subscription check, lock service, and `EngineManager`.
Test: end-to-end API tests should cover success and denial paths for every route.

7. Convert presets from global to user-owned.
- Extend the preset table with `user_id` ownership or replace it with a user-owned variant.
- Update apps/server/app/routers/ui_api.py preset handlers so two users can reuse the same preset name without collision.
- Adjust apps/server/app/models/schemas.py only where response contracts change.
Test: two users must be unable to read, update, delete, or load each other’s presets.

8. Add backend tests before the engine refactor.
- Create `apps/server/tests/conftest.py`.
- Create `apps/server/tests/test_auth_api.py`.
- Create `apps/server/tests/test_account_api.py`.
- Create `apps/server/tests/test_ui_presets_multi_tenant.py`.
Test: this suite must pass before Phase 3 starts.

**PHASE 3: Engine Multi-Tenancy Refactor (The Hardest Part)**
1. Decouple `DcaEngine` from the global singleton.
- Modify apps/server/app/services/engine.py so `DcaEngine` remains a pure single-user engine with no module-global runtime ownership.
- Add `to_snapshot()` and `from_snapshot()` methods to serialize and restore `SystemState`, tick queue, pending actions, and counters.
Test: direct `DcaEngine` unit tests must still pass for the existing trading behavior.

2. Introduce `EngineManager` as the only runtime owner of engines.
- Create `apps/server/app/services/engine_manager.py`.
- Store `dict[user_id, UserEngineContext]`, where each context holds the engine instance, meta account id, last access time, loaded version, and a per-user async lock.
- Expose `get_or_create`, `process_tick`, `get_state_for_user`, `mutate_user_grid`, `persist_snapshot_async`, `evict_idle_engines`, and `clear_user_engine`.
Test: concurrent requests for the same user must share one engine instance; different users must never share state.

3. Add a dedicated engine-state persistence layer.
- Create `apps/server/app/services/engine_state_store.py`.
- `load_latest(user_id)` reads `engine_states`.
- `upsert_latest(user_id, meta_account_id, snapshot, expected_version)` writes atomically and increments version.
Test: snapshot serialization and deserialization must round-trip the full engine state without losing pending actions.

4. Add async state persistence that does not block the tick response.
- Create `apps/server/app/services/engine_snapshot_queue.py`.
- Use an in-process `asyncio.Queue` worker that coalesces writes per user and only persists the latest queued snapshot.
- On every tick, snapshot the engine and enqueue the latest state.
Test: sustained tick tests must show bounded response latency while snapshots still land in order.

5. Implement the load path from PostgreSQL to memory.
- On first tick for a user, `EngineManager` checks memory.
- If absent, it loads the latest snapshot from `engine_states`.
- If snapshot exists, restore `DcaEngine` from it; otherwise create a clean engine.
Test: process a few ticks, restart the server, send one more tick, and confirm the grid resumes with the same session id, rows, and PnL state.

6. Implement the save path from memory back to PostgreSQL.
- After each successful tick, increment `engine_version`, snapshot the engine, and enqueue it.
- The writer upserts only if the incoming version is newer than the stored version.
Test: repeated ticks must increase `engine_version` monotonically; delayed stale writes must be dropped without regressing state.

7. Move all UI state access onto `EngineManager`.
- Modify apps/server/app/routers/ui_api.py so the WebSocket authenticates before `accept()` and all mutations are scoped by `current_user.id`.
- Replace direct `engine.state` mutations with `EngineManager` operations.
Test: one user’s browser must never receive another user’s trading state.

8. Implement the Redis MT5 lock as a dedicated service.
- Create `apps/server/app/services/ea_lock_service.py`.
- Use a Lua script, not `GET` plus `EXPIRE`.
- Rules: absent key means acquire; same owner means refresh TTL; different owner means conflict.
Test: simulate two terminals with the same `account_id` and different `terminal_instance_id` values; the second must receive `409 STOP`, while reconnects from the original terminal only refresh TTL.

9. Add subscription-expiry enforcement.
- Add a periodic cleanup/check task in Celery or app background tasks for cache hygiene.
- On expiry, stop admitting new ticks and optionally evict the in-memory engine after persisting the latest snapshot.
Test: expire a user in the DB, clear cache, send a tick, and verify `403 STOP` with no new actions queued.

10. Add engine-specific tests before billing work.
- Create `apps/server/tests/test_engine_manager.py`.
- Create `apps/server/tests/test_ea_tick_contract.py`.
- Create `apps/server/tests/test_ea_locking.py`.
- Create `apps/server/tests/test_engine_state_persistence.py`.
Test: include same-user concurrency, cross-user isolation, crash-recovery, and lock-conflict scenarios.

**PHASE 4: Subscription Logic & Paystack Webhooks**
1. Add plan and subscription services first.
- Create `apps/server/app/services/plan_service.py`.
- Create `apps/server/app/services/subscription_service.py`.
- Rule: new paid or admin-granted time starts at `max(now, current_active_subscription.ends_at)` so no existing time is lost.
Test: unit tests must prove extension math, active-subscription lookup, and cache invalidation.

2. Implement Paystack checkout initialization.
- Create `apps/server/app/services/paystack_service.py`.
- `POST /api/v1/billing/checkout` validates plan selection, creates a pending invoice, initializes Paystack, stores the provider reference, and returns the authorization URL.
Test: a logged-in user should receive a valid redirect URL and a pending invoice row.

3. Implement webhook verification and idempotency.
- `POST /api/v1/billing/paystack/webhook` must use the raw request body.
- Verify `x-paystack-signature` using HMAC-SHA512 and the Paystack secret before trusting the payload.
- Insert the provider event into `webhook_events` inside the same transaction used for invoice/subscription mutation.
- If the insert conflicts on the unique event id, return `200` and do nothing else.
Test: replay the same valid webhook twice; only the first call may change database state.

4. Handle only the Paystack events needed for this scope.
- `charge.success`: mark invoice paid, create or extend subscription, refresh Redis subscription cache.
- Payment failure event used by the chosen Paystack flow: mark invoice failed, do not grant access.
- Ignore unrelated events after successful signature verification and event logging.
Test: integration tests must prove invoice and subscription transitions for success, failure, and duplicate delivery.

5. Implement the admin manual grant flow.
- `POST /api/v1/admin/users/{user_id}/grant-subscription` must require `admin` role.
- It loads the chosen plan, computes `starts_at` and `ends_at`, inserts a `subscriptions` row with `source='admin'`, and inserts a zero-amount `invoices` row with `provider='admin'` and `status='waived'`.
- It refreshes the subscription cache immediately.
Test: an admin must be able to grant access without Paystack, and the user dashboard must show both the active subscription and the zero-amount invoice/audit trail.

6. Add billing/admin tests before frontend billing screens.
- Create `apps/server/tests/test_billing_checkout.py`.
- Create `apps/server/tests/test_paystack_webhooks.py`.
- Create `apps/server/tests/test_admin_subscription_grants.py`.
Test: include duplicate webhook, out-of-order webhook, and manual grant over an existing active subscription.

**PHASE 5: Frontend Dashboards & Next.js Site**
1. Keep one shared Vite SPA for user and admin workflows.
- Continue using apps/web/src/App.tsx as the SPA entry, but convert it from a single screen into a router shell.
- Reuse apps/web/src/components/TopBar.tsx, apps/web/src/components/SidePanel.tsx, apps/web/src/components/GridTable.tsx, apps/web/src/components/CreatePresetModal.tsx, and apps/web/src/components/ManagePresetsModal.tsx inside the protected trading area.
Test: authenticated users must still be able to reach the trading screen with the existing interaction model intact.

2. Introduce a route-based SPA structure.
- Public routes: `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`.
- Protected user routes: `/app/trading`, `/app/settings/profile`, `/app/settings/security`, `/app/settings/mt5-account`, `/app/billing`, `/app/sessions`.
- Protected admin routes: `/admin/users`, `/admin/users/:userId`.
Test: route guards must block unauthenticated users from `/app/*` and non-admins from `/admin/*`.

3. Refactor the frontend into layouts and providers.
- Create `apps/web/src/router.tsx`.
- Create `apps/web/src/providers/AuthProvider.tsx`.
- Create `apps/web/src/lib/apiClient.ts`.
- Create `apps/web/src/layouts/AuthLayout.tsx`.
- Create `apps/web/src/layouts/AppLayout.tsx`.
- Create `apps/web/src/layouts/AdminLayout.tsx`.
- Replace direct fetch usage in apps/web/src/services/api.ts with a cookie-aware client that handles 401 refresh.
Test: login, refresh, logout, protected navigation, and authenticated WebSocket bootstrap must work in a browser.

4. Build the user dashboard hierarchy.
- `AppLayout`
- `AccountStatusBanner`
- `TradingPage` with existing trading components
- `ProfileSettingsPage`
- `SecuritySettingsPage`
- `Mt5AccountPage`
- `BillingPage` with plan cards, current subscription card, and invoice table
- `SessionsPage` with session list and revoke action
Test: complete the full user flow: register, verify email, log in, bind MT5 account, open trading dashboard, view invoices, revoke another session.

5. Build the admin-panel hierarchy.
- `AdminLayout`
- `UsersPage` with search/filter/table
- `UserDetailPage` with subscription panel, manual grant form, suspend toggle, MT5 binding card, invoice history, and session summary
Test: an admin must be able to search users, open a detail page, suspend/unsuspend, and manually grant a plan.

6. Create the Next.js marketing site as a separate app.
- Create `apps/marketing`.
- Route structure: `/`, `/features`, `/pricing`, docs, `/docs/setup`, `/legal/terms`, `/legal/privacy`, `/legal/cookies`.
- Component hierarchy: marketing layout, hero, feature grid, pricing table, docs sidebar, legal template, CTA footer.
Test: the marketing site must build independently and link cleanly into the SPA auth routes.

7. Add frontend tests and a final verification gate.
- Route-guard tests for anonymous, user, and admin states.
- Component tests for MT5 registration, billing rendering, and admin grant form.
- At least one end-to-end flow: register -> verify email -> login -> bind MT5 account -> see trading dashboard.
Test: do not treat the frontend as complete until these pass.

**Race-condition mitigations**
1. MT5 lock: use a Redis Lua script keyed by `ea_lock:{user_id}`. The stored value is `terminal_instance_id`. Same owner refreshes TTL; different owner gets `409 STOP`. This avoids the `GET`/`EXPIRE` race and prevents a second terminal from stealing the lock mid-refresh.

2. Webhook idempotency: reserve the Paystack event in `webhook_events` with a unique provider event id inside the same DB transaction that updates invoices/subscriptions. If the insert conflicts, return `200` and do nothing. This prevents double-granting access when Paystack retries.

3. Engine snapshot ordering: include `engine_version` in every persisted snapshot and only upsert newer versions. This prevents delayed async writers from overwriting a fresher state.