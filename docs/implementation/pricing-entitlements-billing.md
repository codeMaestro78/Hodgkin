# Pricing, Entitlements, and Billing — Implementation Specification

**Status:** implementation-ready proposal; product and finance decisions remain open
**As of:** 2026-10-16
**Scope:** Free, Scholar, and Investigator plans; server-enforced usage; future paid subscriptions
**Non-goal:** this document does not authorize production billing, database changes, or a Supabase migration.

## 1. Executive decision

The pricing page currently presents three plans, prices, and substantial feature/usage claims. The application does not yet have an authoritative subscription and monthly-entitlement system. Treat the displayed plans as a product proposal, not as active purchasable entitlements.

Recommended first release:

| Plan | Proposed price | Proposed monthly allowance | Intended audience |
| --- | ---: | ---: | --- |
| Free | $0 | 5 research units | Try evidence-backed, focused research |
| Scholar | $14/month or $132/year ($11/month equivalent) | 40 research units | Individual researchers doing regular work |
| Investigator | $36/month or $348/year ($29/month equivalent) | 120 research units | High-volume individual researchers |

These amounts and allowances are **hypotheses**, not approved commercial terms. Validate actual per-mode provider spend, payment fees, storage, support, failed-run cost, and willingness to pay before enabling checkout. Keep citation quality, exact-span verification, source attribution, and honest “answer not established” behavior identical across tiers. A higher tier buys capacity and workflow convenience, never weaker evidence standards or guaranteed findings.

Meter work in **research units** rather than claiming that all runs cost the same:

| Run mode | Provisional unit cost |
| --- | ---: |
| Focused | 1 |
| Balanced | 2 |
| Deep | 4 |

Reserve units before dispatch. Never trust a browser-supplied plan, price, unit cost, provider budget, or quota. Keep monthly subscription allowance separate from per-run safety budgets and concurrency controls.

## 2. Evidence labels and current-state audit

This specification distinguishes:

- **Observed:** verified in the current repository.
- **Recommended:** proposed product or engineering behavior.
- **Open:** requires explicit product, finance, legal, or operations approval.

### 2.1 Observed in this checkout

- `apps/web/app/pricing/pricing-plans.tsx` advertises Free, Scholar, and Investigator. It currently encodes $0, $14/month or $11/month billed annually ($132/year), and $36/month or $29/month billed annually ($348/year). Its CTAs point to signup with a plan query parameter; there is no checkout flow in that component.
- `apps/web/app/pricing/page.tsx` advertises 10 / 60 / 200 “research runs each month,” Deep mode and 20-source copy, citations, library/history/PDF export, comparison, sharing, batches, and scheduled runs. These are not all enforced or fully present. Specifically, the export API currently exposes Markdown and BibTeX, not PDF. Existing interval schedules are not timezone-aware.
- `docs/onboarding.md` says onboarding preferences live in Supabase Auth user metadata and are not authorization, quota, or billing state. Preserve that boundary.
- `services/research-api/src/research_api/repositories/runs.py` provides per-run defaults, including `max_search_calls=12`, a 120-second wall-clock budget, and a $5 estimated-cost ceiling. `services/research-api/src/research_api/api.py` accepts per-run budget overrides. These are **not** plan allowances or actual provider invoices; `pricing.py` describes cost figures as estimates.
- Existing code has run creation, projects/library, report comparison, sharing/export, batches, schedules, tenant-scoped persistence, and a restricted runtime database role. Reuse these capabilities; do not invent duplicate product subsystems.
- `services/research-api/src/research_api/jobs.py` schedules by interval minutes. Do not promise timezone-aware schedules in pricing until supported and tested.
- The current Alembic head should be checked from the target checkout before implementation. A future billing migration number must be chosen from the actual graph, not assumed from this document.

### 2.2 Required pricing-page corrections before billing launch

The page must not state a monthly run quota, PDF export, Deep access, sharing, comparison, or scheduling as an active included feature until the server enforces the entitlement and the feature is usable end to end. Replace run counts with clearly explained research units only after the quota design is approved and enforced. Keep pricing content sourced from one catalog/configuration rather than duplicating numbers across cards, comparison tables, API code, and tests.

## 3. Product and commercial policy

### 3.1 Proposed tier behavior

| Capability | Free | Scholar | Investigator |
| --- | --- | --- | --- |
| Citation and evidence verification | Same quality gate | Same quality gate | Same quality gate |
| Research modes | Focused | Focused, Balanced, Deep | Focused, Balanced, Deep |
| Monthly unit allowance | 5 | 40 | 120 |
| Historical reports/evidence | Retained and readable | Retained and readable | Retained and readable |
| Personal library | Basic save/search | Organize and compare | Organize and compare |
| Report comparison | No, unless existing product decision changes | Yes, bounded | Yes, bounded |
| Read-only sharing | No | Yes, revocable | Yes, revocable |
| Export | Markdown/BibTeX if currently supported | Markdown/BibTeX | Markdown/BibTeX |
| Batch/schedules | No | No | Existing bounded batches and interval schedules only |

This is the **recommended entitlement table**, not a claim that every row is already implemented. Gate individual capabilities only after their existing route/UI behavior and security tests are confirmed. No plan should advertise PDF until PDF generation and authenticated download work.

### 3.2 Unit rules

1. Mode unit costs are catalog values, versioned for reproducibility. Start with Focused=1, Balanced=2, Deep=4 only after cost analysis approves them.
2. A submitted research run reserves its full unit cost atomically with accepted run creation, before enqueue/provider dispatch.
3. A follow-up investigation is a new run and reserves units independently. A batch reserves the sum of its children before any child is dispatched; all-or-nothing admission is preferred for v1.
4. Retries of the same idempotent request do not reserve twice. An intentional fresh attempt is a new run and a new reservation.
5. A scheduled occurrence reserves at execution time, not schedule-creation time. If insufficient units remain, mark that occurrence as quota-blocked and pause or skip according to an explicit user-visible policy; never silently purchase units.
6. Per-run operation, source, wall-clock, and estimated-cost limits remain independent hard safety bounds. A plan allowance cannot raise those bounds. Client budget overrides may only tighten a server limit, never exceed the plan/server ceiling.
7. No unlimited research, unbounded batch fan-out, rollover, paid overage, or purchased top-ups in v1.

### 3.3 Billing-cycle and settlement policy

**Recommended v1 policy:** UTC calendar-month allowance windows for all plans; paid annual billing still grants its plan allowance monthly; unused units expire at the end of the month; no rollover or overage. Activation grants the current month’s full allowance. This is simple to explain but can grant two allowances near a month boundary; measure and explicitly accept that exposure before launch. If unacceptable, choose subscription-anniversary windows before implementing the ledger.

Settlement must be deterministic and idempotent:

- **Platform terminal failure:** release the full reservation to the user, even if provider spend occurred; the platform absorbs that failure cost. This preserves user trust and makes the rule understandable.
- **User cancellation before any provider dispatch:** release the full reservation.
- **User cancellation after provider dispatch:** consume the reserved units. Do not estimate a partial refund from model/provider dollar estimates in v1.
- **Successful completed report, including a truthful “answer not established” report:** consume the reserved units. “No supported finding” is a valid result, not a platform failure.
- **Unknown outcome / worker crash / uncertain provider execution:** keep units reserved until durable recovery determines the terminal outcome; do not release on timeout alone.
- **Administrative correction/refund:** append an audited adjustment entry with actor, reason code, and idempotency key; never edit history silently.

If product or legal review changes these policies, update UI copy, ledger states, and tests together before launch.

### 3.4 Subscription lifecycle

- Checkout success redirects to a pending/processing page. It does not grant access.
- A verified Stripe webhook and canonical subscription/payment state activate the paid entitlement.
- Cancellation at period end retains the tier until `access_until`; immediate cancellation/revocation follows the recorded effective date.
- Recommended failed-renewal policy: retain the currently paid tier for a clearly disclosed 3-day grace period, then downgrade to Free if payment remains unresolved. **Open for product/legal approval.** A paid state must always include an explicit expiry; never infer indefinite access from a stale `active` boolean.
- Existing reports, saved sources, and exports remain readable after downgrade/cancellation. Only new usage and currently gated actions change. Never delete user work as a consequence of nonpayment.
- Refund, dispute, fraud, tax, currency, consumer cancellation rights, and invoice requirements need legal/finance review for launch countries.

## 4. Architecture and trust boundaries

### 4.1 Source of truth

1. Supabase Auth identifies the user. The server verifies the Auth subject and resolves the application `user_id` / `tenant_id`.
2. PostgreSQL stores current subscription projection, entitlement snapshot, usage periods, reservations, and append-only usage ledger.
3. Stripe is the payment processor and source of billing events. The application’s verified local projection is the online authorization source; webhook processing and a reconciliation job keep it current.
4. A static, versioned server-side catalog maps plan keys to prices, modes, unit allowances, and feature flags. The browser may display the catalog but cannot authoritatively choose a price or entitlement.
5. User metadata, query parameters, local storage, client-side React state, unverified checkout redirects, and Stripe event payloads before signature verification are never authorization sources.

Do not put authorization claims in Supabase `user_metadata`; Supabase explicitly warns that users can update it. Avoid relying on stale JWT claims for rapidly changing subscription status. [Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security)

### 4.2 Service boundaries

- **Next.js UI/BFF:** renders catalog and current entitlement; proxies authenticated checkout/portal requests; never has Stripe secret credentials or database service credentials in the browser.
- **Research API (FastAPI):** owns entitlement resolution, quota reservation/settlement, run admission, and authenticated billing endpoints.
- **Stripe webhook endpoint:** public transport endpoint in the API, but accepts only raw-body requests with a valid Stripe signature; enqueue/process idempotently and return promptly after durable receipt.
- **PostgreSQL:** transactionally enforces quota and idempotency. Never hold a row lock while calling Stripe, a model, or a search provider.
- **Reconciler:** periodically fetches canonical Stripe subscription state for recently changed or suspicious accounts, repairs projections, and alerts on drift. Webhook delivery is not the sole repair mechanism.

### 4.3 Checkout flow

1. Authenticated user clicks a plan/interval.
2. UI calls `POST /api/billing/checkout` with `{plan, interval, idempotencyKey}`; no user ID or amount is accepted.
3. API resolves subject and allowed catalog entry, creates/reuses the mapped Stripe customer, and creates a Stripe Checkout Session in subscription mode using server-configured Price IDs.
4. The API returns the hosted Checkout URL. Do not store card details.
5. Stripe sends signed webhook event(s); persist event ID once, apply status idempotently, and update entitlement projection.
6. Client return route polls the safe entitlement endpoint with bounded backoff and displays “Activating…” until webhook projection is active, or explains retry/support if it remains pending.

Stripe documents subscription state as asynchronous and recommends webhooks for changes and payment failures. Verify signatures against the exact raw body. [Stripe subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks), [Stripe webhook endpoint management](https://docs.stripe.com/events/manage-webhook-endpoints).

## 5. Persistence and migration design

Implement an additive Alembic migration after verifying the actual migration head and Supabase database target. Prefer a non-Data-API-exposed schema for billing internals if the current SQLAlchemy/runtime-role setup supports it cleanly; otherwise explicitly revoke `anon`/`authenticated` access, grant the restricted API role only necessary privileges, and enforce RLS. Do not use the Supabase `service_role` key in the web application. Keep webhook secrets and Stripe credentials in server secret management, never rows or client bundles.

Proposed logical tables (names may follow existing model conventions):

### `billing_accounts`

- `tenant_id`, `user_id`, `provider='stripe'`
- `provider_customer_id` with unique constraint
- created/updated timestamps
- unique `(tenant_id,user_id,provider)`; foreign keys scoped to the owning tenant/user

### `billing_subscriptions`

- `tenant_id`, `user_id`, `billing_account_id`
- provider subscription ID (unique), plan key, server catalog/price key
- provider status, `access_until`, `cancel_at_period_end`, billing interval
- latest accepted provider event timestamp and canonical version/update marker
- timestamps; no payment-card data

### `billing_webhook_events`

- provider + provider event ID (unique), event type, provider creation time
- received/processing/processed/failed state, attempt count, safe error code
- payload hash and minimal required normalized fields; avoid persisting raw PII-rich payload unless encrypted, access-controlled, and retention-approved
- processing lease/next-attempt time for recovery

### `usage_periods`

- `(tenant_id,user_id,period_start)` unique; `period_end`
- plan key and catalog version snapshot
- allowance units, reserved units, consumed units, version
- database checks: nonnegative counters; reserved+consumed never exceeds allowance
- one row per UTC calendar month. Include Free users; do not make “no subscription row” mean unlimited.

### `research_unit_ledger`

- scope `(tenant_id,user_id)`, period key, `run_id` (nullable only for explicit admin adjustment), entry kind (`reserve`, `consume`, `release`, `adjust`), signed unit delta, idempotency key, actor/reason, created time
- unique idempotency key scoped to account/operation
- append-only to runtime role except where existing transaction design requires a narrowly scoped operation; never use display ledger reads as an authorization decision
- link every run reservation and terminal settlement to the same run and entitlement period

If a quota-decision row is updated, use a short transaction: insert missing period with `ON CONFLICT DO NOTHING`, lock that one row, validate `consumed + reserved + requested <= allowance`, insert idempotent ledger entry, update counters, and create/enqueue the run in the same database transaction boundary where the existing job architecture permits. Do not call external services while locked. If run/outbox persistence cannot share one transaction, use a durable admission intent/outbox with replay rules; do not accept a quota reservation without a recoverable run intent.

### RLS, grants, and constraints

- Enable and force RLS on user-scoped billing tables where compatible with the restricted runtime role.
- Policies must bind both `tenant_id` and `user_id` using transaction-local identity context already established by the app; include tenant isolation and user isolation negative tests.
- Explicitly grant only required schema/table/sequence privileges to `research_app`; explicitly revoke browser `anon` and `authenticated` grants for private billing tables. Ensure schema exposure settings cannot accidentally expose them.
- Stripe webhook processing may use a narrowly scoped server identity path, not a browser-bypass credential. Audit the chosen role and policies before production.
- Add foreign keys, unique idempotency constraints, status checks, positive-unit checks, and indexes for entitlement lookup and webhook retries.
- Do not grant broad `BYPASSRLS` to the normal API role. Any elevated webhook worker role must be separate, restricted, and tested.

## 6. Entitlement and quota algorithms

### 6.1 Entitlement resolution

`resolve_entitlement(subject, now)` returns a typed server value:

```text
plan_key, subscription_state, access_until,
period_start, period_end, allowance_units,
reserved_units, consumed_units, remaining_units,
catalog_version, feature_flags
```

Resolution order: verified authenticated subject → application user/tenant → current entitlement period → active paid subscription whose status and access expiry satisfy the policy, otherwise Free. No client-selected `plan_key` overrides this result. Cache only if cache invalidation/versioning is reliable; initial implementation should prefer the authoritative database read on run admission.

### 6.2 Atomic run admission

Within one short transaction:

1. Resolve authenticated account and current period.
2. Derive requested mode and unit price from server catalog.
3. Derive per-run caps as the minimum of server safety limits and allowed plan/mode limits. Reject client overrides that attempt to raise a cap.
4. Check feature gates and plan mode permission.
5. Insert reservation idempotently. If reservation already exists for the same idempotent request, return the existing run/result and do not spend again.
6. Lock/update period counters with database constraints preventing overspend under concurrent submissions.
7. Persist run/job intent and outbox dispatch atomically or via the durable-intent pattern described above.
8. Commit, then dispatch/wake worker.

Return a typed quota error (`403` feature not included; `429` allowance exhausted with reset date; `409` conflicting idempotency reuse). Include safe `remainingUnits`, `requiredUnits`, and `periodResetsAt`; never return internal ledger/provider costs.

### 6.3 Terminal settlement

On terminal state, perform one idempotent transition. Use a unique terminal settlement key per run; update period counters and append ledger entry in one transaction. A repeated terminal event, worker replay, or webhook must not settle twice. `uncertain` remains reserved and is visible to operators, not released merely because a process restarted.

## 7. API and contracts

Use generated contract schemas consistent with this repository; don’t hand-edit generated artifacts without regenerating and checking them.

### Public authenticated endpoints

- `GET /billing/entitlement` — current plan/status, feature flags, period, allowance/remaining units, next reset or access expiry. Exclude email, Stripe IDs, payment method, and internal costs.
- `POST /billing/checkout` — body `{plan: "scholar"|"investigator", interval: "month"|"year", idempotencyKey}`; returns hosted checkout URL and an operation ID.
- `POST /billing/portal` — returns a Stripe Customer Portal URL only for the authenticated user’s mapped customer.
- Run creation, follow-up, batch, and scheduled execution admission must call the same entitlement/quota domain service. Do not create a second quota path.

### Webhook endpoint

- `POST /billing/webhooks/stripe` accepts raw bytes and `Stripe-Signature`; verify signature with configured endpoint secret and pinned Stripe SDK/API version.
- Persist event receipt with unique event ID before returning success.
- Process allowed event types idempotently; unknown types are safely recorded/ignored.
- Handle duplicate and out-of-order delivery. Prefer retrieving canonical current subscription state when ordering is ambiguous; don’t let stale events downgrade or reactivate an account incorrectly.
- Use durable retry/dead-letter visibility and reconciliation. Never log raw signed payloads, customer email, card data, or secrets.

### Next.js BFF

Add authenticated same-origin routes under `apps/web/app/api/billing/...` following existing `research-proxy.ts` patterns, with CSRF/Origin protections where mutation routes require them. Validate request schemas at the boundary. Never accept arbitrary redirect destinations; allow only configured application URLs.

## 8. Pricing and account UI

### Pricing page

- One authoritative plan catalog drives cards and comparison rows.
- Display exact cadence: “$14 billed monthly” or “$132 billed yearly ($11/month equivalent).” Do not imply monthly cancellation terms on annual plans.
- Explain research units with visible mode weights and the allowance consumed before the user starts research.
- Show which limits are monthly entitlements vs per-run safety ceilings.
- State no rollover and whether taxes are added only after legal/finance confirms jurisdictional copy.
- Keep features honest: no PDF, timezone-aware scheduling, SSO, or team seats unless implemented and separately entitled.
- Accessible comparison table on mobile; clear selected plan, focus state, error/loading state, and reduced-motion behavior.

### Workspace composer

- Before submission, show mode and its unit cost, remaining allowance, and reset date.
- If quota is exhausted, explain when it resets and offer plan comparison without blocking existing reports or research history.
- For a batch, show total required units and reject before any child starts if insufficient.
- For schedules, show that each occurrence uses quota and explain what happens when allowance is exhausted.

### Account billing

- Current plan, subscription state, next renewal/access expiry, monthly allowance used/remaining, and billing interval.
- “Manage billing” opens authenticated Customer Portal.
- Explicit pending activation state while awaiting webhook confirmation.
- Payment failure/grace/cancel-at-period-end states have next steps and dates.
- On downgrade, explain that prior reports/library remain readable; identify which new actions will be unavailable.

## 9. Implementation sequence for an AI coding agent

Do not begin by wiring a payment button. Follow these gates in order.

### Phase 0 — Product economics and claim audit

1. Confirm actual plan prices, unit allowance, mode weights, features, billing-cycle rules, failed-run policy, grace period, cancellation, refund, tax, currency, annual renewal, and legal copy with product/finance.
2. Analyze persisted actual provider usage by mode, including failed/uncertain calls and repeated runs. Do not treat `max_estimated_cost_usd` as an invoice.
3. Replace unsupported pricing-page claims or visibly mark the page as planned until server enforcement exists.

**Exit gate:** signed-off catalog and policy; expected worst-case gross margin is acceptable; legal/finance review complete for launch geography.

### Phase 1 — Catalog and entitlement read model

1. Add a typed, versioned server plan catalog; keep UI fed from a safe public projection.
2. Add entitlement response contracts and authenticated read endpoint.
3. Implement account/period resolution with Free fallback and no checkout.
4. Add contract and endpoint tests; confirm onboarding metadata cannot change the plan.

**Exit gate:** pricing catalog and entitlement endpoint agree; invalid/stale subscription state fails safely to the approved policy.

### Phase 2 — Durable usage ledger and run admission

1. Inspect Alembic graph and target; design additive migration, constraints, RLS, and explicit restricted-role grants.
2. Implement period initialization and atomic reserve/consume/release operations.
3. Integrate the single quota gate with normal runs, fresh retries, follow-ups, batches, and scheduled occurrences.
4. Make run/job/outbox intent recoverable if process crashes between admission and dispatch.
5. Add migration upgrade/rollback procedure; avoid destructive downgrade of ledger data.

**Exit gate:** concurrency tests prove the allowance cannot be overspent; replay and duplicate requests do not double charge; all admission paths are covered.

### Phase 3 — Stripe test mode

1. Create/test Stripe products/prices outside code; bind exact Price IDs via server configuration.
2. Add hosted Checkout and Customer Portal endpoints.
3. Add signature-verified webhook inbox, idempotent projection, event retry and reconciliation.
4. Exercise checkout success, delayed payment, duplicate/out-of-order webhooks, failed renewal, cancellation, portal updates, refunds/disputes per policy.

**Exit gate:** no entitlement is granted from a redirect alone; events can replay safely; operational drift is detectable.

### Phase 4 — UI and plan rollout

1. Update pricing, composer, account billing, quota errors, and downgrade continuity.
2. Run accessibility, mobile, keyboard, reduced-motion, and empty/error/pending-state checks.
3. Enable for internal users in Stripe test mode, then a small opt-in cohort in live mode only after explicit launch approval.

**Exit gate:** server entitlements match visible copy; user sees clear unit cost before every new run; no existing work disappears on downgrade.

## 10. File-level implementation map

Paths are starting points; inspect the checked-out architecture before editing and keep changes localized.

| Area | Likely files / additions | Required responsibility |
| --- | --- | --- |
| Catalog + types | `services/research-api/src/research_api/billing/catalog.py` (new), config | versioned plan/price/feature/unit mapping; no user-controlled prices |
| Entitlement domain | `.../billing/entitlements.py`, `.../billing/usage.py` (new) | resolve plan; atomic reserve and terminal settlement; idempotent rules |
| Persistence | `db/models.py`, repository under `repositories/`, next Alembic revision | billing tables, scoped constraints, RLS, grants, indexes |
| Run admission | `api.py`, `runtime_api.py`, `jobs.py`, run/follow-up paths | one quota gate for every path, before dispatch; server-owned caps |
| Stripe boundary | `.../billing/stripe_api.py`, `.../billing/webhooks.py` (new) | checkout/portal, raw-body signature check, durable inbox, idempotency |
| Contracts | API contract source, generated schemas, `packages/contracts` | typed entitlement/checkout/quota response and error contracts |
| Web BFF | `apps/web/app/api/billing/**/route.ts` (new), `apps/web/lib/research-proxy.ts` patterns | auth forwarding, schema validation, safe redirects |
| Pricing UI | `apps/web/app/pricing/page.tsx`, `pricing-plans.tsx` | catalog-backed honest prices/features/allowances |
| Workspace/account UI | research composer components, account/settings routes | unit disclosure, quota states, manage billing, cancellation continuity |
| Documentation | `docs/onboarding.md`, billing/product docs | metadata boundary, policies, rollout/support instructions |

## 11. Required validation matrix

### Unit/domain tests

- Free, active paid, canceled-at-period-end, expired, past-due/grace, incomplete, absent subscription, and webhook-lag states.
- Every research mode maps to exactly one versioned unit cost; unsupported modes fail closed.
- Client-submitted plan, amount, unit cost, `maxEstimatedCostUsd`, search limits, and extra budget fields cannot raise entitlement or safety limits.
- Settlement policy matrix; “answer not established” consumes normally; platform failure releases; uncertain outcome retains reservation.
- Period boundary, annual plan monthly allowance, zero remaining, exact remaining, and one unit over.

### Database/concurrency/security tests

- Run two concurrent admissions for the last available units: at most one succeeds; no negative or over-allowance counters.
- Duplicate HTTP idempotency key returns the same admission without new reservation; conflicting payload with same key is rejected.
- Duplicate worker terminal event settles once; crash/replay from each transaction boundary remains consistent.
- Tenant A cannot read or mutate tenant B billing, usage, webhook, or period data; user-level scope is tested where applicable.
- `anon` and `authenticated` cannot read private billing tables; `research_app` has only the required grants; no broad RLS bypass.
- Migration upgrade from the actual prior head on disposable PostgreSQL; validate constraints/policies/grants and operator rollback procedure. Do not apply hosted migration without explicit authorization.

### API/integration tests

- Checkout accepts only known plan/interval pairs and server-configured Price IDs; user cannot select another account’s Stripe customer.
- Checkout redirect success alone does not grant paid entitlement.
- Invalid signature rejected; exact raw body signature accepted; repeated event ID has no duplicate effect.
- Out-of-order subscription events converge to canonical current Stripe state.
- Reconciliation repairs missed webhook; safe errors and no secret/PII logs.
- All normal run, follow-up, retry, batch child, and schedule occurrence paths are metered.

### Frontend/e2e tests

- Displayed monthly/annual prices, units, modes, and features match server catalog.
- Pending activation, payment failure, cancellation, exhausted quota, reset date, and API outage states are clear and recoverable.
- Existing reports, source links, library, and permitted exports remain readable after downgrade.
- Keyboard/screen reader, mobile table overflow, focus states, reduced motion, and safe external checkout navigation.

## 12. Observability, abuse controls, and operations

Record low-cardinality metrics: checkout creation/result, webhook receive/process age and failure count by event type, entitlement lookup latency, quota allow/deny, reservation/settlement drift, uncertain reservations, reconciliation corrections, units by plan/mode, and actual provider cost by mode. Do not log raw webhook payloads, user email, full prompts, card data, or secrets. Use internal account/run identifiers only where access-controlled and retention-limited.

Alert on webhook processing lag, repeated signature failures, negative/over-allowance counter constraint violations, unresolved reservations beyond the recovery window, subscription projection drift, and a run path with no matching reservation. Apply rate limits to checkout session creation and account portal requests. Consider one active subscription per personal user unless product explicitly supports teams; enforce the rule in the service and database.

## 13. Rollout and rollback

1. Keep billing disabled by default behind server-side feature flags.
2. Deploy additive schema and code compatible with existing Free behavior. The migration should not delete or rewrite research data.
3. In shadow mode, compute proposed unit costs and remaining allowance without blocking runs; compare with actual costs and detect uncovered admission paths.
4. Enable quota enforcement for internal/test accounts; then test-mode checkout/webhooks; then a limited live cohort after explicit authorization.
5. Monitor settlement correctness, cost distributions, support incidents, and cancellation outcomes before broad launch.
6. Application rollback: turn off checkout and enforcement flags, preserve usage/subscription records, keep old reports readable, and deploy prior app build. Reconcile events before re-enabling.
7. Do not drop billing tables or erase ledger history during rollback. Prefer forward repair; document any manual operator action with audit trail.

## 14. Open decisions required before implementation/launch

1. Approve prices and currency/region strategy: Free $0, Scholar $14/month or $132/year, Investigator $36/month or $348/year are provisional.
2. Approve research-unit weights and allowances: 1/2/4 and 5/40/120 are provisional pending measured unit economics.
3. Confirm which currently built features are actually available per plan; remove claims that are not implemented (notably PDF and timezone-aware schedules).
4. Approve UTC calendar periods vs subscription anniversaries, no rollover, and annual-plan monthly grants.
5. Approve settlement behavior for user cancellation after provider dispatch and the recommended 3-day payment grace policy.
6. Confirm subscription quantity policy: one personal subscription vs future organizations/seat billing.
7. Confirm launch countries, taxes, refunds, receipts/invoicing, academic discounts, accessibility/legal review, and support obligations.
8. Approve Stripe as processor and the production secret/webhook rotation/incident owner.
9. Explicitly authorize any production/Supabase schema change and live billing enablement separately.

## 15. Market context (not price validation)

Public competitor pricing pages checked on 2026-10-16 show different packaging rather than directly comparable run quotas: Elicit lists Plus at $11/user/month billed annually; Consensus lists Pro at $20/month or $144/year ($12/month equivalent), and Deep at $65/month or $540/year; AnswerThis lists Pro at $35/month per seat. Competitor features and prices change and are not a substitute for willingness-to-pay tests or our own measured cost model. Keep this section dated and re-check before launch. [Elicit pricing](https://elicit.com/pricing?redirected=true), [Consensus plans](https://help.consensus.app/en/articles/10087865-subscription-plans), [AnswerThis pricing](https://answerthis.io/our-pricing).

## 16. References

### Repository references

- `apps/web/app/pricing/page.tsx`
- `apps/web/app/pricing/pricing-plans.tsx`
- `docs/onboarding.md`
- `services/research-api/src/research_api/api.py`
- `services/research-api/src/research_api/repositories/runs.py`
- `services/research-api/src/research_api/pricing.py`
- `services/research-api/src/research_api/research_limits.py`
- `services/research-api/src/research_api/sharing_exports_api.py`
- `services/research-api/src/research_api/runtime_api.py`
- `services/research-api/src/research_api/jobs.py`
- `services/research-api/src/research_api/db/models.py`
- `services/research-api/src/research_api/db/session.py`

### Primary documentation

- [Stripe Checkout Sessions](https://docs.stripe.com/api/checkout/sessions)
- [Stripe subscription webhook guide](https://docs.stripe.com/billing/subscriptions/webhooks)
- [Stripe webhook signature verification](https://docs.stripe.com/webhooks/signature)
- [Supabase Row Level Security](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase breaking change: explicit Data API exposure for new tables](https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically)

### Design principles

- Server-side entitlement and quota decisions; never trust client plan metadata.
- Atomic admission and idempotent settlement; no external calls while database locks are held.
- Append-only, auditable usage history; explicit unresolved/uncertain states.
- Same evidence verification across tiers; capacity differs, truthfulness does not.
- No feature or price claim before the end-to-end implementation and regression gate pass.
