# Pricing, Entitlements, and Billing — Historical Implementation Specification

> **Superseded on 2026-10-21:** Stripe subscriptions, Checkout, Customer Portal,
> webhook processing, and Stripe configuration were removed from the active
> application. This document is retained as a historical record because earlier
> migrations and persisted billing rows may still reference Stripe-named schema.
> Do not follow Stripe setup, launch, or endpoint instructions below. The active
> one-time credit-purchase provider is Razorpay; subscription checkout remains
> unavailable until a provider-specific subscription flow is implemented.

> **Current purchased-credit behavior:** One-time top-ups use Razorpay and are
> account-scoped, not plan-scoped. Any authenticated, metered account can buy a
> configured pack when the wallet, payment, terms, and database-schema gates
> pass. Remaining monthly units are used first; purchased units cover a run's
> shortfall. They do not add monthly allowance or unlock a mode excluded by the
> plan. The internal unmetered UUID allowlist is a separate operator override;
> it bypasses unit admission and its accounts intentionally do not see top-up
> checkout. Readiness diagnostics must never expose payment credentials.

### Current Razorpay credit-pack setup

Credit packs are **one-time Orders**, not Razorpay recurring Plans. The server
creates each order with its configured amount; no Razorpay Plan ID, subscription,
or dashboard product needs to be created for a credit pack. These proposed
Test-mode offers are deliberately priced above or near the monthly plan's
per-unit rate so that top-ups do not become a cheaper replacement for a plan.
That is a pricing hypothesis only—not verified unit economics or approval for
live sale.

| Pack | Price | Units | Approx. price per unit |
| --- | ---: | ---: | ---: |
| Starter | ₹199 | 5 | ₹39.80 |
| Standard | ₹499 | 15 | ₹33.27 |
| Value | ₹899 | 30 | ₹29.97 |

The exact JSON and a 60-unit wallet ceiling are in both `.env.example` files.
Keep payment and wallet gates disabled in live environments until margins,
customer terms, refund/dispute operations, and database migrations are approved.
This code currently grants on a verified captured payment and handles duplicate
capture delivery idempotently; refund/dispute webhook handling is not yet
implemented for Razorpay credit purchases. Do not enable live top-ups until that
gap is closed and tested.

For a Test-mode end-to-end check, configure a matching Test-mode Razorpay key
pair, `RAZORPAY_LIVEMODE=false`, a Test-mode webhook secret, the offers above,
and the credit gates. In Razorpay Dashboard Test Mode, configure the webhook at
the API's `/billing/webhooks/razorpay` URL and subscribe to `payment.captured`
(retain any subscription events already used by the same endpoint). Apply the
credit-wallet/order migrations (0030 and 0033, or the current full migration
head) to the API database before turning the gates on. A successful checkout
must pass server signature verification and captured-payment amount/currency
checks before the account wallet is credited. Razorpay's [Orders integration
guide](https://razorpay.com/docs/server-integration/python/test-app/) requires
server-side callback signature verification, and its [security
checklist](https://razorpay.com/security/checklist) recommends retrieving
payment amounts from a trusted backend source.

**Status:** historical design; current checkout implementation and provider decisions are documented in the active Razorpay billing code and environment examples
**As of:** 2026-10-19
**Scope:** Free, Scholar, and Investigator plans; server-enforced usage; future paid subscriptions
**Non-goal:** this document does not authorize production billing, database changes, or a Supabase migration.

## 1. Executive decision

The pricing page presents the lower-price proposal and tier/mode split for local implementation. Core subscription and entitlement paths now exist behind configuration, but paid plans are not launch-ready: allowances remain provisional, live billing is gated, and test-mode purchase/reconciliation operations still require end-to-end validation.

Recommended first release:

| Plan | Proposed launch price (not purchasable yet) | Provisional monthly allowance | Intended audience |
| --- | ---: | ---: | --- |
| Free | $0 | 5 research units | Try evidence-backed, focused research |
| Scholar | $5.99/month or $59.99/year ($5.00/month equivalent) | 20 research units | Individual researchers doing regular work |
| Investigator | $12.99/month or $129.99/year ($10.83/month equivalent) | 40 research units | Researchers needing Deep mode and higher capacity |

The lower prices and tier split are approved for local implementation by the user on 2026-10-19. The 5/20/40 monthly allowances and 1/2/4 mode weights are **provisional**, not launch-approved economics. The catalog version is bumped so historical v1 periods keep resolving against their original terms. Before checkout or enforcement, validate actual per-mode provider spend, payment fees, storage, support, failed-run cost, tail risk, and willingness to pay; revise allowances if the margin gate fails. Keep citation quality, exact-span verification, source attribution, and honest “answer not established” behavior identical across tiers. A higher tier buys capacity and workflow convenience, never weaker evidence standards or guaranteed findings.

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

- `apps/web/app/pricing/pricing-plans.tsx` shows the proposed $0 / $5.99 / $12.99 monthly prices and $0 / $59.99 / $129.99 annual reference prices. Paid CTAs depend on server checkout availability; API Checkout/Portal routes exist behind configuration, while annual checkout is disabled.
- `apps/web/app/pricing/page.tsx` previously advertised 10 / 60 / 200 research runs, PDF export, and equal cost at every depth. The implementation removes those claims, marks unit allowances provisional, and describes Markdown/BibTeX rather than PDF. Existing interval schedules are not timezone-aware.
- `docs/onboarding.md` says onboarding preferences live in Supabase Auth user metadata and are not authorization, quota, or billing state. Preserve that boundary.
- `services/research-api/src/research_api/repositories/runs.py` provides per-run defaults, including `max_search_calls=12`, a 120-second wall-clock budget, and a $5 estimated-cost ceiling. `services/research-api/src/research_api/api.py` accepts per-run budget overrides. These are **not** plan allowances or actual provider invoices; `pricing.py` describes cost figures as estimates.
- Explicit `focused`, `balanced`, and `deep` modes and versioned operational ceilings are implemented in `mode_policy.py`; current mode policy stores provider-operation/source/time/token safety budgets, not monthly unit prices or plan entitlements. `ResearchRun.mode` and `mode_policy_version` are persisted, and retry/follow-up logic preserves mode semantics. Unit pricing must be a separate server-owned catalog rather than inferred from operation/source limits.
- Batch and schedule requests now accept an optional explicit research mode. New batch records and child runs snapshot mode plus `mode_policy_version`; scheduled occurrences inherit the schedule snapshot. Legacy records remain mode-null and are not backfilled. The active billing period snapshots the catalog version used for each occurrence; this is separate from the operational mode-policy snapshot.
- The existing `UsageLedger` is unique per tenant/run and records run-level provider/model usage and reservations. `ProviderCallReservation` is also run-scoped. Neither is a monthly entitlement period or customer research-unit ledger; do not retrofit monthly account-balance semantics into those tables.
- Billing implementation has a local v2 server catalog (`research-units-v2-2026-10-19`) with proposed prices, provisional Free/Scholar/Investigator grants (5/20/40 units), provisional mode prices (1/2/4), and the settlement matrix in §3.3. The historical v1 catalog remains registered so persisted v1 periods continue to resolve. `BILLING_ENFORCEMENT_ENABLED` remains off by default; no paid plans are activated.
- Migrations `0021`–`0028` are local and have not been applied to any shared, development, staging, or hosted database. Reservations connect to run creation/replay, retries, follow-ups, all-or-nothing batches and scheduled occurrences; terminal settlement is transactional with terminal state and retried during durable recovery. Mode-null new work is rejected only when enforcement is enabled. Operator adjustments require a server-configured actor-token mapping and append actor/reason/idempotency audit details. The opt-in disposable PostgreSQL lifecycle test covers migrations, RLS/grants, concurrent admission, settlement replay, Stripe-period resets, suspension/recovery/cancellation, and the state-transition function; broader crash/failure-injection and shadow reconciliation gates remain.
- Stripe Checkout/Portal API and same-origin BFF routes, server-only Price ID validation, customer/subscription projections, and a raw-body signature-verified webhook inbox with bounded payload size and event-ID deduplication are implemented locally behind flags. Signed subscription events can provision paid periods; success redirects alone cannot. Test-mode Stripe configuration, an end-to-end test-mode purchase/webhook journey, reconciliation operations, and live paid-plan activation remain unverified. Do not present the local integration as launch-ready billing.
- `WorkspaceShell` renders shared sidebar content in desktop and mobile navigation; `.sidebar-bottom` contains the profile/sign-out row. The authenticated entitlement budget card is implemented; detailed usage history, browser-level accessibility, and failure-state/network validation remain open.
- Existing code has run creation, projects/library, report comparison, sharing/export, batches, schedules, tenant-scoped persistence, and a restricted runtime database role. Reuse these capabilities; do not invent duplicate product subsystems.
- `services/research-api/src/research_api/jobs.py` schedules by interval minutes. Do not promise timezone-aware schedules in pricing until supported and tested.
- The billing migration chain is `0021`–`0028` in this checkout and has been exercised from an empty database on a disposable PostgreSQL instance. Before applying it elsewhere, inspect that target's current revision and confirm the intended database; no shared or hosted target has been migrated.

### 2.2 Required pricing-page corrections before billing launch

The page may show the agreed commercial proposal only with a clear preview/unavailable notice. It must not imply that proposed unit amounts or plan gates are active entitlements until the server enforces them and the authenticated UI reads the authoritative catalog. Do not claim PDF export. Keep pricing content sourced from one catalog/configuration rather than duplicating numbers across cards, comparison tables, API code, and tests; the current page/catalog duplication is a known follow-up before checkout.

## 3. Product and commercial policy

### 3.1 Proposed v2 tier behavior (commercial launch still gated)

| Capability | Free | Scholar | Investigator |
| --- | --- | --- | --- |
| Citation and evidence verification | Same quality gate | Same quality gate | Same quality gate |
| Research modes | Focused | Focused, Balanced | Focused, Balanced, Deep |
| Provisional monthly unit allowance | 5 | 20 | 40 |
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
7. No unmetered usage through purchased wallets, unbounded batch fan-out, monthly rollover, or automatic top-ups. Fixed purchased packs are separate finite research units and do not raise per-run safety limits.

### 3.2.1 Mode-weighted units: product contract and economics

The allowance is a **monthly capacity grant**, denominated in research units. It is
not money, provider tokens, a source count, or an estimate of a provider invoice.
The user-facing promise is deliberately stable: a mode has a known unit price
before submission, and the same server-owned price is reserved atomically when a
run is accepted.

| Mode | Provisional unit price | User-facing meaning |
| --- | ---: | --- |
| Focused | 1 unit | A bounded, evidence-checked decision brief |
| Balanced | 2 units | Broader dimension coverage and structured analysis |
| Deep | 4 units | The largest currently supported investigation ceiling and report structure |

The mode weights are provisional catalog values, but they are **not measured cost
ratios**. Before paid launch, use settled provider-cost distributions by mode,
including failed and uncertain runs, to check gross-margin exposure and
tail risk. A mode's maximum provider budget is a safety ceiling, not expected
cost. If mode weights change, version the catalog and charge only new admissions
under the new version; never reprice an existing reservation or historical run.

Do not change a unit price based on provider/model choice,
discovered-source count, actual token usage, retries, or repair rounds. That would
make the price hard to predict and couple the customer balance to noisy provider
measurements. Keep per-run provider-operation, source, wall-clock, token, and
estimated-cost ceilings as separate safety controls. Purchased top-ups use the
separate account wallet and ledger described in §3.2.3; they never alter these
mode prices or safety limits.

**Balance formula:**

```text
available_units = period_allowance_units
                 - consumed_units
                 - active_reserved_units
```

For example, with 40 units granted, 8 consumed, and 4 reserved by in-flight work,
the UI says **28 available**, with **4 reserved** shown separately in details.
A run is admitted only if the server-authoritative available balance covers its
full mode price. There is no partial admission. The browser may show the selected
mode's price before submit, but only the API can approve the reservation.

Rules for deriving a reservation:

1. Resolve the authenticated subject, effective mode, and current versioned
   server catalog. Ignore client-supplied plan, unit price, allowance, and
   catalog version.
2. Persist `required_units` and `catalog_version` with the accepted reservation
   so policy changes cannot alter already accepted work.
3. Reserve atomically with idempotency acceptance and durable run/job intent.
   Use a unique account/period/idempotency key and a pre-existing period row
   (created safely with a unique constraint) as the serialization point for
   concurrent submissions. A read-then-write balance check is unsafe.
4. Same-key replay returns the original run and reservation. A fresh follow-up
   or intentionally new run reserves again. A retry of an existing run, a
   repair round, and model/provider retries do not reserve extra units.
5. Batch admission reserves the sum of child-mode costs before any child
   dispatch. Scheduled work reserves when its occurrence is admitted, not when
   the schedule is created. If the full amount is unavailable, reject or mark
   quota-blocked according to one explicit policy; never start a subset silently.
6. Settle exactly once under §3.3. Keep uncertain reservations unavailable
   until durable recovery resolves them. Corrections are append-only adjustments,
   never edits to historical ledger entries.

**Mode availability is separate from mode price.** A plan may have enough units
but still not include a mode; deny it before reservation. This prevents a large
balance from implying Deep access. The current pricing UI and this proposal
disagree about Free access (the page advertises Focused and Balanced, while the
proposal table says Focused only). Product must resolve that mismatch before the
server catalog or UI promises either policy.

### 3.2.3 Purchased research-unit top-ups (product policy approved; launch gated)

The requested “add credits for dollars” experience should be modeled as a
**one-time purchase of a fixed research-unit pack**, not a cash-value wallet.
This product meters research by fixed mode weights, not actual provider invoice
dollars; a dollar balance would promise metered cash settlement that the runtime
does not provide. If the product later charges against actual provider spend,
that is a separate billing architecture and customer promise.

The product owner approved the local product policy below on 2026-10-19.
This is not legal advice or authorization to sell. Customer-facing wording and
jurisdictional compliance remain launch gates. The active implementation uses
Razorpay and fails closed unless the independent payment, wallet, terms,
fulfillment, spending, webhook, currency, and database-schema gates pass. There
is no paid-plan requirement in the credit-pack purchase route.

Draft customer disclosure for finance/legal review:

> Research credits are units for research use, not cash and not a payment
> balance. They are separate from monthly plan units, do not renew monthly, and
> do not expire while your account remains active. Credits do not unlock modes
> excluded by your plan. If a purchase is refunded, unused and unreserved
> credits are reversed. If any credits have been spent or reserved, wallet use
> will be paused while we review and reconcile the account. A payment dispute
> will temporarily pause wallet use while it is unresolved. These terms do not
> limit any rights you have under applicable law.

- The UI may call these “research credits” only with an adjacent definition:
  **1 research credit = 1 research unit**. A run still costs the existing
  server-owned mode price (Focused 1, Balanced 2, Deep 4).
- Sell fixed server-configured packs through a one-time Razorpay order. The
  browser chooses a package key only; the server maps it to a configured pack
  and fixed unit grant. No arbitrary
  client-entered dollar amount, client-selected grant, or automatic recharge in
  the first release.
- Keep purchased units in a separate account-level wallet and append-only ledger;
  do not inflate `BillingPeriod.allowance_units` or represent purchases as
  operator adjustments. Monthly units retain their period expiration and
  settlement rules. Purchased units do not expire with the monthly billing
  period and do not expire while the customer account remains active. Account
  closure, dormant balances, and any legally required treatment must be resolved
  in jurisdiction-specific legal terms; do not silently delete or forfeit a
  balance.
- Spend included monthly units first, then purchased units. Reserve both sources
  atomically under the existing account serialization lock, record exact
  per-run allocation, and settle/release each allocation exactly once. Mode
  access gates and source/time/operation/token/cost safety ceilings remain
  unchanged; buying units never unlocks a plan-gated mode.
- Grant units only after a signed, deduplicated Stripe webhook proves the
  expected Checkout Session is paid and matches the server's package, owner,
  currency, and configured amount. A redirect is only a pending UX state.
  Delayed payment is not spendable before its verified payment-success event.
- Persist an order projection and an append-only purchased-credit ledger with
  unique Stripe session/payment references, exact unit grant, price/currency
  snapshot, owner, status, and reversal linkage. Never delete or rewrite a grant.
- On a verified refund, reverse unused, unreserved purchased units using an
  idempotent append-only ledger entry. If any purchased units are already
  reserved or consumed, pause wallet spending and mark the purchase/account for
  auditable reconciliation; do not create a negative balance or automatically
  claw back units from an active run. Apply any additional remedy only under the
  approved, jurisdiction-specific refund terms.
- On a payment dispute, pause wallet spending while the dispute is unresolved.
  A verified dispute win restores the purchase and wallet availability; a lost
  dispute follows the verified-refund/reconciliation path. Every transition
  must be idempotent, tied to the Stripe event/payment, and recoverable after a
  crash. A dispute notification alone is not proof that a refund completed.
- Expose monthly included and purchased balances separately. Top-ups do not
  renew monthly and do not enable a mode the current plan excludes. When
  included units are insufficient, preserve the draft and show package choices
  only after purchase is fully configured.
- Add server-side wallet ceilings and purchase/rate limits before launch. Do not
  add automatic top-ups until explicit spend caps, consent, alerts, retry rules,
  and support/refund handling have been designed.

**Commercial and launch decisions still required before live checkout:**

1. Pack sizes and USD prices. The six-run matched pilot on two draft cases is
   directional only (two observations per mode; no failed-run sample, invoice
   reconciliation, or quality adjudication). Validate margins against larger
   cost distributions, failed/uncertain dispatch, payment fees, taxes, support,
   and infrastructure before approving prices.
2. Obtain jurisdiction-specific finance/legal review of the customer-facing
   non-expiry, refund, dispute, account-closure, tax, and consumer-rights terms.
   The product policy above is approved locally but is not legally reviewed.
3. Confirm balance treatment on plan cancellation/downgrade. Purchased units do
   not unlock plan-gated modes; the final customer terms must explain this.
4. Approve maximum wallet balance, purchase/rate limits, and handling of
   multiple/pending payments.

**Implementation status (2026-10-20):** The wallet/order schema and migration
`0030` passed disposable PostgreSQL tests. Authenticated package listing,
idempotent one-time Checkout, signed paid-session fulfillment, separate wallet
balance, monthly-first allocation, terminal settlement, refund reversal,
dispute pause/win/loss handling, and the budget-card top-up control are coded.
The disposable-PostgreSQL integration test covers replay, unpaid/async-success
delivery, reservation, failed-run release, dispute pause/win, full-unspent
refund reversal, refund holds for reserved units, and 21 concurrent admissions
against 20 purchased units. Additional matched quality/cost receipts,
out-of-order webhook adjudication, a real browser Checkout return, and
customer/legal review remain release gates. The three sandbox Prices are
5 units/$1.99, 12/$3.99, and
25/$6.99; these are **test offers**, not approved live prices. Wallet ceiling
is configurable and checkout limits are two pending and five starts per day.

The current API configuration points to a hosted Supabase database at migration
`0029`. Do not set `BILLING_CREDIT_*` purchase flags there until migration
`0030` is explicitly approved and applied to that target with a verified backup.
The added code tolerates the pre-`0030` schema when top-ups are off. No hosted
migration was applied by this slice. Test-mode activation also requires a
reachable Stripe webhook destination subscribed to Checkout completion/async,
refund, and dispute events, plus the matching signing secret. Live-mode
top-ups stay code-blocked even if subscription billing is live.

To exercise the test-mode UI after the target database has been backed up and
`0030` has been approved/applied, configure the existing Stripe **test** key,
webhook signing secret, API version, and app base URL, then set the credit flags
in `services/research-api/.env.example` to their enabled values in the real
environment. Use the three sandbox Prices in this order: `starter` =
`price_1USKPRA9ncihy4DE18XCfXpB` (199 cents, 5 units), `standard` =
`price_1USKPSA9ncihy4DEsInBr8n5` (399 cents, 12 units), and `value` =
`price_1USKPSA9ncihy4DEEirb1llU` (699 cents, 25 units). Each JSON pack must
have `currency: "usd"` and `expiryDays: null`; set terms version
`research-credit-terms-v1` and a positive wallet ceiling. The webhook must
forward `checkout.session.completed`, `checkout.session.expired`,
`checkout.session.async_payment_succeeded`,
`checkout.session.async_payment_failed`, `refund.created`, `refund.updated`,
`charge.dispute.created`, and `charge.dispute.closed` to the API's
`/billing/webhooks/stripe` path. Restart the API after changing settings. A
successful Checkout redirect is only pending; confirm the owner-scoped purchase
status becomes `paid` and the separate purchased balance increases exactly
once. Never use these sandbox Price IDs with a live Stripe key.

Stripe Checkout supports both one-time `payment` Sessions and `subscription`
Sessions. Fulfillment must follow verified payment events, including asynchronous
success/failure where delayed payment methods are enabled—not the success
redirect. See [Stripe Checkout Session modes](https://docs.stripe.com/api/checkout/sessions/object)
and [Stripe's payment fulfillment events](https://docs.stripe.com/payments/existing-customers?platform=web&ui=stripe-hosted).

### 3.2.2 Budget-card contract and display states

The workspace card sits immediately above the profile row on desktop and in the
same position inside the mobile navigation drawer. It is a read-only view of the
authenticated entitlement projection, not a second accounting mechanism. The
current `WorkspaceShell` renders shared sidebar content in both contexts; use
one reusable card in that shared body so the two balances cannot drift.

Recommended compact presentation:

```text
RESEARCH BUDGET                         Details →
Scholar · resets Nov 1
28 units available
[accessible usage meter]
4 units reserved · Deep uses 4
```

Prioritize available units and reset date. The selected run mode and cost belong
in the composer/submit review; show them in the card only when a mode is selected,
and label the value as an example. Do not use `$` or call units “credits” unless
the product deliberately introduces monetary-value credits. Never show per-run
operation/source ceilings as monthly usage.

States and behavior:

- **Loading:** quiet skeleton with fixed height; do not flash a guessed
  Free-plan balance.
- **Available:** show available units, period end/reset date and plan. Screen
  readers receive text such as “12 of 40 units used; 4 reserved; 24 available”;
  color is never the only signal.
- **Reserved work:** availability already subtracts active reservations. Explain
  them in Details. The admission response is the immediate source for a
  post-submit update; never decrement before the server accepts a run.
- **Low balance:** neutral guidance, e.g. “4 units available — enough for one
  Focused run.” Calculate from the authoritative balance and current catalog;
  never suggest a mode that this plan does not include.
- **Exhausted:** state the reset date and offer plan options only if a working
  upgrade path is configured. Existing reports/history remain accessible.
- **Pending activation:** show “Plan activation pending”; do not grant paid
  modes or units before the verified server projection changes.
- **Unavailable/stale:** never substitute local-storage or indefinitely cached
  numbers. Say “Budget temporarily unavailable,” provide retry, and let server
  admission return the authoritative allow/deny.
- **Period boundary:** store UTC instants; render the reset date in the user's
  timezone with an explicit date. The exact UTC `periodEnd` remains authoritative.

Use one accessible Details link/button to open usage history; do not make the
whole card an interactive target containing nested controls. Support keyboard
focus, touch targets, reduced motion, narrow drawers, long plan names, large
text, and screen-reader meter semantics. On a normal balance, avoid a persistent
upgrade CTA competing with the research composer.

The client may retain a short-lived entitlement snapshot for presentation, but
never use it to admit work. After admission/settlement, use the server-returned
balance or invalidate/refetch. Do not poll continuously; refresh on app entry,
explicit request, known local reservation/settlement events, and bounded focus
or reconnect recovery.

### 3.3 Billing-cycle and settlement policy

**Local v1 period policy:** Free allowance periods use UTC calendar months. A paid monthly plan's allowance period follows the verified Stripe subscription-item period `[current_period_start, current_period_end)` (UTC instants); the Stripe renewal boundary is also the quota reset boundary. Activation grants the catalog allowance for that verified paid period; unused units expire at its end, with no rollover or overage. The entitlement API returns the stored period end as the authoritative reset date. This avoids granting a second full paid allowance at a calendar boundary unrelated to the subscription renewal. Annual billing and annual prices are not enabled; before offering annual billing, define and test a separate monthly grant cadence. The ledger records period and catalog version so future policy changes do not reprice prior admissions.

Settlement must be deterministic and idempotent:

- **Platform terminal failure:** release the full reservation to the user, even if provider spend occurred; the platform absorbs that failure cost. This preserves user trust and makes the rule understandable.
- **User cancellation before any provider dispatch:** release the full reservation.
- **User cancellation after provider dispatch:** consume the reserved units. Do not estimate a partial refund from model/provider dollar estimates in v1.
- **Successful completed report, including a truthful “answer not established” report:** consume the reserved units. “No supported finding” is a valid result, not a platform failure.
- **Unknown outcome / worker crash / uncertain provider execution:** keep units reserved until durable recovery determines the terminal outcome; do not release on timeout alone.
- **Administrative correction/refund:** append an audited adjustment entry with actor, reason code, and idempotency key; never edit history silently.

The user explicitly approved this settlement matrix for local v1 implementation on 2026-10-19. Finance/legal review, jurisdictional consumer terms, refunds, and production launch approval remain separate gates; policy changes must update UI copy, ledger states, and tests together before launch.

### 3.4 Subscription lifecycle

- Checkout success redirects to a pending/processing page. It does not grant access.
- A verified Stripe webhook and canonical subscription/payment state activate the paid entitlement.
- Cancellation-at-period-end retains the paid tier and current allowance through the verified Stripe period end; the later canceled/deleted event ends the paid period. An immediate cancellation event ends paid access when processed. Customer-facing terms must disclose this behavior before live billing.
- **Local v1 payment-failure policy:** suspend the paid period as soon as a verified subscription event reports a non-active status; do not provide an implicit grace period. The user can use the current Free allowance window. If Stripe later reports the same paid period active again, reactivate its existing ledger snapshot without resetting consumed or reserved units. Customer-facing terms must disclose suspension and recovery behavior. A paid state must always include an explicit expiry; never infer indefinite access from a stale `active` boolean.
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
- one row per applicable allowance window: UTC calendar month for Free, verified Stripe item period for a paid monthly plan. Include Free users; do not make “no subscription row” mean unlimited.

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
reserved_units, consumed_units, available_units,
catalog_version, feature_flags, mode_unit_costs
```

Resolution order: verified authenticated subject → application user/tenant → current entitlement period → active paid subscription whose status and access expiry satisfy the policy, otherwise Free. No client-selected `plan_key` overrides this result. Cache only if cache invalidation/versioning is reliable; initial implementation should prefer the authoritative database read on run admission.

`available_units` is `allowance_units - reserved_units - consumed_units`. A
negative persisted balance is an invariant violation that should alert, not be
hidden by clamping. Return exact period timestamps, catalog version, mode prices
and allowed modes so the UI can explain the next run. This endpoint is a read
projection: admission must repeat the check transactionally and cannot trust a
GET result, cache, or browser snapshot.

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

Return a typed quota error (`403` feature not included; `429` allowance exhausted with reset date; `409` conflicting idempotency reuse). Include safe `availableUnits`, `requiredUnits`, and `periodResetsAt`; never return internal ledger/provider costs.

### 6.3 Terminal settlement

On terminal state, perform one idempotent transition. Use a unique terminal settlement key per run; update period counters and append ledger entry in one transaction. A repeated terminal event, worker replay, or webhook must not settle twice. `uncertain` remains reserved and is visible to operators, not released merely because a process restarted.

## 7. API and contracts

Use generated contract schemas consistent with this repository; don’t hand-edit generated artifacts without regenerating and checking them.

### Public authenticated endpoints

- `GET /billing/entitlement` — current plan/status, feature flags, period, allowance/remaining units, next reset or access expiry. Exclude email, Stripe IDs, payment method, and internal costs.
- The entitlement response should include `allowanceUnits`, `consumedUnits`,
  `reservedUnits`, `availableUnits`, `periodStart`, `periodEnd`,
  `catalogVersion`, `modeUnitCosts`, `allowedModes`, and safe `updatedAt`. Use
  integer units and ISO-8601 timestamps. Never expose provider dollars/tokens or
  Stripe customer identifiers. `availableUnits` is informational; admission
  remains transactional.
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

### Sidebar budget card and usage detail

- Place the reusable card immediately above `.sidebar-bottom` in the shared
  `WorkspaceShell` sidebar content so desktop and mobile drawer display the same
  server-projected balance.
- The card's primary value is **available units now**, with plan and reset date;
  secondary detail is reserved work. Do not show `allowance - consumed` as
  available while reservations exist.
- Details shows period grant, consumed, active reservations by run/mode,
  available, recent unit-ledger entries, and reset timestamp. Link entries to
  reports/runs only where the authenticated user is authorized. Uncertain
  settlements remain explicitly pending rather than disappearing.
- Composer selection shows the exact versioned mode price and projected
  post-admission balance. Replace the projection with the server admission
  response. If another tab/run used the balance first, preserve the draft and
  show the server's denial plus refreshed amount; never auto-resubmit.
- A presentation snapshot may include `updatedAt`, but lookup failures render an
  unavailable state, not a fabricated or indefinitely stale amount. It is never
  a quota decision.
- Empty, low, reserved, exhausted, activation-pending, cancel-at-period-end,
  past-due/grace, and API-unavailable states each need intentional copy. Existing
  reports and library remain readable across quota/subscription states.

### Account billing

- Current plan, subscription state, next renewal/access expiry, monthly allowance used/remaining, and billing interval.
- “Manage billing” opens authenticated Customer Portal.
- Explicit pending activation state while awaiting webhook confirmation.
- Payment failure/grace/cancel-at-period-end states have next steps and dates.
- On downgrade, explain that prior reports/library remain readable; identify which new actions will be unavailable.

## 9. Implementation sequence for an AI coding agent

Do not begin by wiring a payment button or drawing a balance in the sidebar.
The order remains economics/policy → server catalog and read projection →
shadow accounting → durable quota ledger/enforcement → Stripe lifecycle → budget
UI → controlled rollout. This checkout has an active local v2 catalog,
approved local settlement and period policies, admission/lifecycle wiring,
audited operator adjustments, Stripe subscription projections,
signed/deduplicated webhook ingress, and an authenticated budget card.
Migrations remain unapplied outside disposable test databases; enforcement and
paid launch remain off by default.

### Phase 0 — Product economics and claim audit

1. **Approved for local implementation:** use v2 proposed prices and tier/mode split, plus the versioned settlement and period policies in §3.3. The pricing page labels paid plans as a preview; allowances and mode weights remain provisional until cost validation.
2. Actual paid-plan price IDs, payment collection, refunds, tax, annual renewal terms, jurisdictional disclosures, and legal copy still require finance/legal and Stripe configuration before live billing. The local implementation deliberately has no payment grace period.
3. Decide compatibility for requests with `mode=null` and already-created schedules with no mode: do not guess from source/operation budgets or silently backfill historical runs. Pick an explicit transition (for example, require explicit modes for newly metered work while preserving legacy behavior during a dated grace period).
4. Decide batch pricing semantics. Recommended v1: one explicit batch-wide mode, all child runs use that mode, and total reservation is `question_count × mode_unit_cost`; later per-question mode selection requires a UI/API version that shows the exact sum before submit.
5. **Approved local v1 schedule rule:** persist the selected mode and operational policy on the schedule; each occurrence reserves at execution time from the user's active billing-period/catalog snapshot. Thus an already-created schedule does not itself grandfather a commercial catalog; a new period may carry a new version. If the active plan does not permit the mode or units are insufficient, mark the occurrence quota-blocked and surface it; never silently downgrade mode or launch a partial batch.
6. Analyze observed provider-cost distributions by mode, including failures, uncertain dispatch, retries and repair. Do not treat `max_estimated_cost_usd` as an invoice or assume mode operational ceilings equal expected spend.
7. Use “research units” for included monthly capacity. Under the approved local top-up policy, “research credits” may be used only when explicitly defined as units, never as a dollar/provider-spend wallet.
8. Remove unsupported live claims or mark them as planned until enforcement and the capability are usable end to end.
9. **Approved local product policy, not approved for live sale:** one-time research-unit packs follow §3.2.3 and policy version `research-credit-terms-v1`. Purchased units are non-expiring while an account remains active, do not unlock plan-gated modes, and follow the verified refund/dispute/reconciliation policy. Sandbox purchases remain disabled in the current hosted-backed environment until migration `0030` is applied to the explicitly approved target; live sales additionally require legal, finance, tax, and recovery review.

**Exit gate:** local catalog and settlement contract are versioned and approved; before paid launch, measured cost tails and finance/legal review for the launch geography must also pass.

**Implementation started (2026-10-18):** a read-only receipt analyzer is available at
`services/research-api/scripts/analyze_billing_economics.py`. It groups existing
`live_mode_evaluation.py` JSONL receipts by explicit mode, includes failed and
cancelled runs, reports missing cost observations separately from zero, and
compares estimated run-ledger/model costs with the provisional local 1/2/4 scenario.
It keeps only aggregate mode/outcome/cost data in its output; prompts, case IDs,
run IDs, tenants, and provider details are not emitted. This is an offline
economics aid, **not** the Phase 2 persistent shadow ledger, a live feature flag,
an entitlement API, or quota enforcement. No production or database behavior is
changed by running it.

Run it against receipts produced outside the repository by the already-gated
evaluation runner:

```bash
uv run python scripts/analyze_billing_economics.py /secure/path/receipts.jsonl \
  --output /secure/path/billing-economics.json
```

The generated report labels costs as estimates and does not claim that 1/2/4
weights match provider-cost ratios.
Use it only with representative matched-mode receipts; an empty or small sample
does not satisfy the economics exit gate.

**Matched live pilot (2026-10-19):** six runs across the same two draft cases
(comparison and factual), two per mode. All six completed. Mean end-to-end times
were 23s Focused, 35s Balanced, and 53s Deep; mean first-source times were 7.4s,
8.2s, and 8.7s respectively. Application ledger cost estimates averaged
$0.0506, $0.0677, and $0.1014 per run; model usage accounting averaged
$0.0026, $0.0037, and $0.0054. Estimated total ledger cost was $0.439442,
including $0.023442 in model usage estimates. These are not provider invoices.
There were no failed runs, no human quality adjudication, only two cases, and no
first-verified-finding measurement; the pilot is not sufficient to approve pack
prices, failure reserves, or product quality. Raw observations are retained
outside the repository at `/tmp/research-mode-eval.KlVLYJ/` for follow-up.

**Phase 2 shadow-observation slice (2026-10-18):** migration `0021` adds a
tenant-scoped, append-only `billing_shadow_observations` record for each newly
created run when `BILLING_SHADOW_ACCOUNTING_ENABLED=true`. Run creation is
centralized through `RunRepository.create_once`, so normal submissions, batch
children, retries/follow-ups, and scheduled occurrences share this hook.
Idempotent replays create no second record. Explicit modes snapshot the
approved-catalog 1/2/4 value, mode-policy version, and catalog version; legacy
`mode=null` runs are recorded as unpriced rather than guessed from their
operational budget. The flag defaults
off, and the record never reserves units, changes run admission, or exposes a
balance. The write uses a savepoint and is best-effort: a database storage error
is logged with sanitized operation/status facts and does not reject an otherwise
valid run. This also means shadow observations may be missing during storage
outages and must not be treated as an authoritative quota ledger. The migration
has **not** been applied to the shared local database or Supabase. This is an
observation record, not the period-grant/settlement ledger;
cost reconciliation, plan allowances, rejected-attempt observations and
quota-enforcement work remain open.

An opt-in disposable PostgreSQL check is provided as
`tests/integration/test_billing_shadow_persistence.py`; it is gated by
`RUN_BILLING_SHADOW_DB_TESTS=1`, creates a uniquely named local database, and
removes only that database after the RLS/grant checks. Do not run it against a
shared or hosted database.

**Phase 1 read-model slice (2026-10-19):** the API has an active, versioned,
server-owned local v2 catalog and authenticated `GET /billing/entitlement`
(also forwarded through `/api/billing/entitlement`). The catalog is approved
for local implementation; a caller receives `not_configured` until a period
grant exists. Enforcement can create a Free calendar-month grant on first
admission; paid grants require a verified Stripe subscription projection and
matching catalog Price. The endpoint does not trust client-supplied plan values.

**Phase 2 / Phase 3 ledger primitive slice (2026-10-19):** local revision
`0022` adds personal billing accounts, catalog-versioned period snapshots, and
an append-only unit-delta ledger, all owner-scoped by tenant and user. The API
read model fails closed on unknown/draft catalogs, mismatched allowances,
overlapping periods, or inconsistent/overdrawn balances. The ledger module
provides transaction-participating grant, reservation, and terminal settlement
operations. It serializes by `(tenant_id,user_id)` with a transaction-scoped
PostgreSQL advisory lock; this avoids granting `UPDATE` merely to use
`SELECT FOR UPDATE`, while the database unique indexes remain a second line of
defense. Migration `0023` adds only `INSERT` to the existing `SELECT` grants;
RLS remains owner-scoped and neither table `UPDATE` nor `DELETE` is granted.
Migration `0024` adds immutable adjustment actor/reason fields and a database
constraint requiring both for adjustment entries; it grants no additional SQL
privilege. The internal `adjust_units` primitive requires an actor, bounded
reason, and idempotency key, serializes on the billing account, checks balance
bounds, and rejects conflicting replays. The internal adjustment endpoint now
requires a unique configured operator token and derives the actor ID from that
configuration; no caller-supplied actor identity is trusted. Revisions
`0021`–`0028` exist locally and have not been applied to any shared,
local-development, staging, or hosted database.
Disposable PostgreSQL integration coverage now exercises
grant replay/overlap, concurrent last-unit admission, reservation and
settlement idempotency/conflicts, audited adjustment replay/conflict/bounds,
and the restricted grants. API readiness requires `0022` for entitlement reads,
`0026` when quota enforcement is enabled, and `0028` when Stripe processing is
enabled. Revision `0027` adds owner-scoped subscription and
checkout projections; `0028` adds a constrained billing-period lifecycle
function without granting table `UPDATE`. Reservations are wired to run creation/replay,
retries/follow-ups, batches, and scheduled occurrences. Terminal settlement is
wired to terminal state transitions and recovery; uncertain provider calls keep
their units reserved. The entitlement endpoint and shared sidebar budget card
are implemented locally. The lifecycle test passed on an isolated disposable
PostgreSQL service, and a fresh full Alembic upgrade reached `0028`; neither
shared nor hosted databases were touched. Enforcement remains disabled.

The lifecycle audit confirmed that normal runs, retries, and follow-ups preserve
explicit mode snapshots. Migration `0025` and the request contracts now add
optional mode plus operational policy-version snapshots to batch and schedule
records; all batch children use the batch mode, and each scheduled occurrence
uses the schedule mode. Missing mode remains legacy and is never inferred from
provider-operation or source budgets. New mode-null submissions are rejected
when enforcement is enabled, while replay of an existing mode-null run remains
unmetered and does not receive a retroactive reservation. Each accepted unit
reservation points to its immutable period/catalog snapshot; future scheduled
occurrences use the current eligible period at admission. Paid period grants
are projected from verified Stripe events locally, but Stripe remains disabled
by default. Historical work and balances are not backfilled.

### Phase 1 — Catalog and entitlement read model

1. **Implemented locally:** typed, versioned server catalog for plan allowances, allowed modes, mode unit prices, and list prices. Stripe Price IDs remain deployment configuration; `mode_policy.py` remains the per-run safety policy.
2. Define the billed subject boundary explicitly. Today verified Supabase users map to personal `user_id`/`tenant_id`; if organization/multi-seat billing is in scope, introduce an explicit billable account/membership model rather than assuming tenant equals payer.
3. **Implemented locally in `0025`:** batch and schedule contracts snapshot operational mode policy. Existing null-mode records remain legacy and are not backfilled. New null-mode work is rejected only when billing enforcement is switched on.
4. **Implemented locally:** the public safe entitlement response contract and authenticated `GET /billing/entitlement` expose only the current-period projection; without an approved grant the endpoint returns `not_configured`.
5. **Implemented locally:** FastAPI billing router uses existing authenticated-caller behavior, and the same-origin Next.js BFF forwards the entitlement response.
6. Add typed tests for missing/invalid subscription state, mode access, UTC period boundaries, catalog version and no-trust of onboarding metadata/client-supplied plan values.

**Exit gate:** API, contracts and catalog agree; client values cannot grant a plan or mode. Paid grant provisioning remains a separate Phase 4 requirement.

### Phase 2 — Durable records and shadow accounting (non-blocking)

1. Inspect the current Alembic graph and target revision before applying anything. Migrations `0021`–`0028` are local-only and remain unapplied to shared/local-development/staging/hosted databases. The opt-in isolated billing test creates a uniquely named temporary database and exercises migrations `0021`–`0028`, RLS, privileges, and lifecycle behavior. `0022` enables and forces owner-scoped RLS and grants `SELECT`; `0023` adds `INSERT` only; `0024` adds adjustment audit fields; `0025` adds nullable batch/schedule mode snapshots; `0026` adds webhook inbox and schedule quota diagnostics; `0027` adds owner-scoped Stripe customer, subscription, and checkout state; `0028` adds the owner-checked state-transition function and plan-scoped grant idempotency. No migration grants billing-ledger table `UPDATE` or `DELETE`.
2. Period-grant, immutable unit-ledger, and idempotent reservation/settlement records plus internal transaction-participating primitives now exist. Their disposable PostgreSQL test proves same-grant replay, overlapping-grant rejection, one-winner concurrent admission at the last unit, reservation/settlement replay and conflict handling, and restricted privileges. Keep subscription projection, entitlement period, reservation, and append-only ledger entry responsibilities distinct. Do not reuse per-run `UsageLedger` or provider-call reservation rows as monthly quota state.
3. **Implemented, with a bounded gap:** shadow observations attach approved mode-unit values and policy/catalog versions to newly created runs without rejecting them or storing prompt text. Rejected admission attempts are not yet observed; shadow records remain observational, not authoritative usage.
4. Reconcile shadow decisions against accepted runs, actual provider usage, failures, retries and mode mix. Measure expected spend per unit and identify every code path that bypasses the primary run endpoint.
5. Add migration upgrade/restore rehearsal on a disposable PostgreSQL target and document additive-schema rollback (disable application behavior; retain ledger records).

**Exit gate:** shadow totals reconcile to run/admission records; no missing mode or entry path is unexplained; realistic cost tails fit the signed-off economics; migrations, RLS and restricted-role grants pass isolated integration/security tests. Shadow mode does not block runs.

### Phase 3 — Atomic quota enforcement and lifecycle

**Implemented locally behind `BILLING_ENFORCEMENT_ENABLED` (default false); validation gate remains open:**

1. Re-run admission and settlement against a migrated disposable PostgreSQL database, including every call path and injected crash/recovery boundaries. Keep the enforcement flag off until this passes.
2. **Implemented locally:** per-account transaction-scoped advisory lock and database uniqueness guards serialize balance reads/writes; the disposable test proves only one of two concurrent last-unit reservations succeeds.
3. **Implemented locally:** the central run repository enforces normal run, retry/follow-up and batch-child reservations; schedule occurrences reserve when created by the scheduler. Idempotent replay reserves once; batches are all-or-nothing in their enclosing transaction. Mode-null requests fail closed only with enforcement enabled. A reservation's catalog is recoverable through its immutable billing-period foreign key and the reserved delta; schedules persist the operational mode, while their future occurrence uses the catalog on the active billing period at admission time.
4. **Implemented locally:** reservation shares the transaction that persists run, budget and durable job intent; no database lock crosses a provider/model/Stripe call.
5. **Implemented locally:** idempotent terminal settlement and recovery use §3.3; unresolved provider reservations retain quota. The disposable test exercises reservation/settlement replay and policy transitions; crash/failure-injection coverage across every runtime entrypoint remains open.
6. **Implemented locally:** safe quota errors report required/available units and period end without provider-cost or Stripe details. Reports/history remain independently readable.
7. **Pending:** run a representative shadow-versus-enforced reconciliation after disposable lifecycle coverage is complete; do not enable the flag in production before that gate.

**Exit gate:** concurrency, duplicate, crash/replay, cancellation, uncertain-provider, every-entrypoint, tenant-isolation and migration tests pass on disposable databases; no known bypass path; shadow and enforcement decisions reconcile. No paid subscription is required yet; Free test grants can validate enforcement.

### Phase 4 — Stripe test-mode subscription lifecycle

**Implemented locally, disabled by default; disposable PostgreSQL validation passed.** Revision `0027` adds owner-scoped customer/subscription/checkout projections, preserves the minimal signed-event inbox, widens the event status column for reconciliation states, and uses forced RLS. Revision `0028` keeps direct billing-period `UPDATE` privilege revoked while providing a narrow, owner-checked state transition and a composite idempotency key that permits a Free and paid snapshot to share a start instant. The API has authenticated monthly Checkout and Customer Portal routes, same-origin BFF routes, server-only Price IDs, a single-open-checkout/idempotency record, exact Stripe Price verification before Checkout, and subscription projection from signed events. Redirects do not grant access; only supported, active monthly subscriptions whose Price amount/currency match the local catalog can grant the period allowance. Annual purchases and in-portal plan switching are deliberately not enabled. The isolated lifecycle test and a separate full Alembic upgrade through `0028` passed; no shared database was migrated.

**Period-policy decision resolved locally:** Free resets on UTC calendar-month boundaries; paid monthly allowances follow Stripe's verified item-level `current_period_start/end`, so paid quota reset, renewal, expiry, and the entitlement UI's reset timestamp use the same period. Stripe documents the billing-cycle anchor as the UTC reference point for future cycles and exposes it on the subscription object ([Subscription object](https://docs.stripe.com/api/subscriptions/object), [Create a subscription](https://docs.stripe.com/api/subscriptions/create)). Payment-failure behavior is explicit locally: any verified non-active status suspends paid units immediately with no grace; a verified recovery reactivates the same period without replenishing usage. Migration `0028` adds a narrowly scoped state-transition function; it does not grant the application `UPDATE` on billing periods. Reconciliation, database validation, live key configuration, and launch terms remain gates. Live Stripe Checkout additionally requires the separate `BILLING_LIVE_LAUNCH_APPROVED` gate, default false.

Still required before even a limited test-mode cohort:

1. **Passed locally:** the opt-in lifecycle test used a uniquely named database on an isolated disposable PostgreSQL service and validated RLS, function permissions, restricted table privileges, concurrent admission, lifecycle replay, Stripe period reset, immediate suspension/recovery, cancellation and Free-period restoration. Separately, the full Alembic chain upgraded a fresh disposable database through `0028`. No shared or hosted database has been migrated.
2. Add operator visibility and a recovery procedure for `reconciliation_required` events. Stripe receives a retry response for unresolved relevant events; this is intentionally fail-closed, but a human-readable, access-controlled reconciliation queue and alert are still needed.
3. In Stripe **test mode**, create one product per paid plan and one monthly recurring USD Price per product. Configure server Price IDs, then verify Dashboard amounts exactly match this catalog: Scholar `$5.99 USD/month`; Investigator `$12.99 USD/month`. The API rechecks those values at checkout and on subscription events. Do not configure annual Prices yet.
4. Configure the Customer Portal for payment-method updates and cancellation only. Do not enable plan/Price swaps until proration, immediate-vs-period-end changes, and the cross-period allowance policy are specified and tested.
5. Register `POST https://<api-host>/billing/webhooks/stripe` in test mode for `checkout.session.completed`, `checkout.session.expired`, and `customer.subscription.created`, `.updated`, `.deleted`, `.paused`, and `.resumed`. Set the endpoint API version to the same pinned value as `STRIPE_API_VERSION`; signed events with another version are quarantined and not applied. Store the signing secret only in the API secret manager. Verify signature failure, duplicate delivery, delayed activation, immediate past-due suspension, cancellation, recovery/retry, and that a success redirect alone does not grant units. The local no-grace policy is immediate suspension on any verified non-active status; publish that policy in customer-facing terms before live billing.
6. Run test-mode Checkout → webhook activation → authenticated entitlement read → paid-mode reservation → cancellation/downgrade, with no real payment. Validate webhook-age and reconciliation alerts, then exercise the application rollback flags while preserving database history.
7. Do not switch to live keys until cost sustainability, tax/refund/legal terms, recovery, migration, and rollout gates in §§13–14 are signed off. Live billing requires a separate explicit operational authorization.

Environment variables are `BILLING_STRIPE_ENABLED`, `BILLING_ENFORCEMENT_ENABLED`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_API_VERSION`, `STRIPE_PRICE_SCHOLAR_MONTHLY`, `STRIPE_PRICE_INVESTIGATOR_MONTHLY`, `STRIPE_PORTAL_CONFIGURATION_ID`, `STRIPE_LIVEMODE`, `BILLING_LIVE_LAUNCH_APPROVED`, and `BILLING_APP_BASE_URL`. Keep all flags false by default. Readiness fails closed if Stripe is enabled without enforcement, schema, secrets, pinned API version, Price IDs, portal configuration, valid HTTPS return URL, or matching test/live key mode. Live Checkout additionally requires `BILLING_LIVE_LAUNCH_APPROVED=true`; do not set it before the separate live launch approval. Never put Stripe secret values in the web app, repository, issue, or chat.

**Exit gate:** period and no-grace policies match code, tests, and customer-facing terms; disposable migration and RLS tests pass; no unresolved collection/import failures; test-mode user journey and webhook retries are verified; reconciliation has an operator path; test-mode cancellation/downgrade leaves existing reports and sources readable. Passing this gate does not itself authorize production migrations or live charging.

### Phase 5 — Pricing, composer, budget card and usage detail

**Partially implemented locally:** the pricing page checks checkout availability and supports monthly Checkout when server flags are enabled; yearly billing stays disabled. The shared desktop/mobile sidebar displays the authenticated entitlement balance and can open the Customer Portal. API/BFF and contract unit tests pass in the isolated local suite. A detailed per-period ledger/history view and browser-level accessibility/network validation remain open.

1. Remaining: remove any still-unverified tier-feature promises and make plan display derive from the authoritative catalog where practical. Keep provisional unit amounts clearly labeled until economics passes.
2. Remaining: show selected mode cost and available balance/reset date in the composer; for batches, show the exact summed cost. If concurrent use changes the balance, preserve the draft and display the server denial.
3. **Implemented locally:** a shared sidebar card reads authenticated entitlement state in desktop and mobile layouts and links to the portal only when relevant. Verify the browser states, keyboard/screen-reader behavior, and narrow mobile layout before release.
4. Remaining: add a usage-details view showing period allowance, consumed units, active reservations grouped by run/mode, available balance, reset time and recent append-only ledger entries. Apply object-level authorization to every linked run/report.
5. Keep read failures visibly unavailable rather than showing stale local-storage data. Refresh after admission/settlement using server responses or targeted invalidation; do not add a polling loop or frontend quota logic.
6. Test the card in both rendered sidebar contexts, at narrow/mobile widths, keyboard/screen-reader paths, large text and reduced motion. Preserve reports/library access when quota is exhausted or subscription changes.

**Exit gate:** all displayed prices, features, mode weights and balances match the server catalog/entitlement endpoint; no fabricated balance state; admission remains server-authoritative; desktop/mobile/accessibility and failure-state tests pass.

### Phase 6 — Controlled rollout and operations

1. Keep billing and enforcement behind server-side flags with a named owner and expiry. Enable first for internal/test accounts, then a bounded opt-in cohort after test-mode and migration gates pass.
2. Monitor quota decisions, reservation/settlement drift, uncertain reservations, webhook age/retries, reconciliation corrections, per-mode actual cost and quota-related support events. Alert on missing reservations, negative balances, stale subscription projection and stuck unknown reservations.
3. Verify rollback by disabling checkout/enforcement while retaining immutable unit ledgers and existing research data. Do not reverse ledger migrations destructively or remove reports on downgrade.
4. Obtain explicit production/Supabase migration and live-billing authorization separately; confirm backup/restore and target revision before hosted schema changes.

**Exit gate:** operational dashboard and runbooks exist; recovery/reconciliation is rehearsed; rollback preserves data and paid access behavior is approved for the rollout jurisdiction.

## 10. File-level implementation map

Paths are starting points; inspect the checked-out architecture before editing and keep changes localized.

| Area | Likely files / additions | Required responsibility |
| --- | --- | --- |
| Catalog + types | `services/research-api/src/research_api/billing/catalog.py` (new), `mode_policy.py` remains separate | versioned plan/mode-access/unit/price mapping; no user-controlled prices or changes to historical run ceilings |
| Entitlement domain | `.../billing/entitlements.py`, `.../billing/ledger.py`, `.../billing/lifecycle.py` | resolve billable subject/period; atomic reserve and terminal settlement; idempotent rules; do not overload per-run `UsageLedger` |
| Persistence | `db/models.py`, `.../billing/ledger.py`, migrations `0021`–`0028` | billing tables, scoped constraints, RLS, grants, indexes, and owner-checked lifecycle transitions |
| Run admission | `api.py`, `runtime_api.py`, `jobs.py`, `repositories/runs.py` | one quota gate for create/retry/follow-up/batch/schedule occurrence before dispatch; server-owned caps and durable intent |
| Stripe boundary | `.../billing/api.py`, `.../billing/stripe.py`, `.../billing/subscriptions.py` | Checkout/Portal, raw-body signature check, durable inbox, subscription projection, idempotency |
| Contracts | `packages/contracts/src/billing.ts`, `packages/contracts/src/runtime.ts`, `packages/contracts/schema/BillingEntitlementSchema.json`, batch/schedule schemas, generated FastAPI schemas | typed entitlement/checkout/quota contracts; explicit batch/schedule mode fields; generated artifacts stay in sync |
| Web BFF | `apps/web/app/api/billing/**/route.ts` (new), `apps/web/lib/research-proxy.ts` patterns | auth forwarding, schema validation, safe redirects |
| Pricing UI | `apps/web/app/pricing/page.tsx`, `pricing-plans.tsx` | catalog-backed honest prices/features/allowances |
| Workspace/account UI | `apps/web/app/components/workspace-shell.tsx`, `apps/web/app/(research)/research/page.tsx`, `apps/web/app/pricing/page.tsx`, `pricing-plans.tsx`, new account/usage route | shared desktop/mobile card, mode-price disclosure, quota states, manage billing, cancellation continuity |
| Documentation | `docs/onboarding.md`, billing/product docs | metadata boundary, policies, rollout/support instructions |

## 11. Required validation matrix

### Unit/domain tests

- Free, active paid, canceled-at-period-end, expired, past-due/grace, incomplete, absent subscription, and webhook-lag states.
- Every research mode maps to exactly one versioned unit cost; unsupported modes fail closed.
- Catalog version changes cannot reprice reserved work; idempotent replay returns the original price and catalog version.
- A mixed-mode batch reserves its exact summed unit cost atomically; concurrent requests for the final units cannot overspend.
- Available always equals allowance minus consumed and reserved; uncertain reservations remain unavailable and visible in Details.
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
- Sidebar balance matches the authenticated entitlement endpoint in desktop and mobile drawer; loading/unavailable states never show a fabricated balance.
- Accessibility announces used/reserved/available counts; the visual meter is not the only representation.
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

1. Local product-owner decision: target prices are Free $0, Scholar $5.99/month or $59.99/year, and Investigator $12.99/month or $129.99/year. Currency/region strategy and finance/legal approval remain open.
2. Unit economics remain open: provisional mode weights are 1/2/4 and provisional allowances are 5/20/40. Do not expose or enforce these as paid entitlements until matched actual cost receipts establish sustainable margin, including failed/uncertain work and fees.
3. Confirm which currently built features are actually available per plan; remove claims that are not implemented (notably PDF and timezone-aware schedules).
4. **Resolved for local monthly-plan implementation:** Free UTC calendar periods; paid monthly allowance periods follow the Stripe renewal period; no rollover. Annual billing remains disabled until its monthly quota-grant cadence is designed and tested.
5. **Resolved for local implementation:** cancellation after provider dispatch consumes the reservation; verified non-active subscription status suspends the paid period immediately with no grace. Finance/legal must still approve how these terms are disclosed and any required customer protections before launch.
6. Confirm subscription quantity policy: one personal subscription vs future organizations/seat billing.
7. Confirm launch countries, taxes, refunds, receipts/invoicing, academic discounts, accessibility/legal review, and support obligations.
8. Approve Stripe as processor and the production secret/webhook rotation/incident owner.
9. Explicitly authorize any production/Supabase schema change and live billing enablement separately.

## 15. Market context (not price validation)

AnswerThis's public pricing page currently presents a $35/month Pro headline and separately includes a comparison table listing a $14/month Pro tier, with different plan names and feature packaging. Because the page is internally inconsistent, these are reference points only; they do not validate our price or unit economics. Recheck before launch and compare equivalent capabilities, not just price. [AnswerThis pricing](https://answerthis.io/our-pricing).

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
- [Stripe entitlements](https://docs.stripe.com/billing/entitlements) — feature access can follow purchased products; the application still owns transactional research-unit admission.
- [Stripe usage-based billing](https://docs.stripe.com/billing/subscriptions/usage-based) — usage meter aggregates may be asynchronous, so do not use them for synchronous quota admission.
- [Stripe billing credits](https://docs.stripe.com/billing/subscriptions/usage-based/billing-credits) — relevant only if monetary prepaid credits/top-ups are later chosen; those differ from non-monetary research units.
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

## Internal unmetered access

Set `BILLING_INTERNAL_UNMETERED_USER_IDS` to a JSON array of immutable Supabase
Auth user UUIDs in the API environment, for example `["<auth-user-uuid>"]`.
The user must still sign in normally. This server-side allowlist bypasses only
monthly and purchased-unit reservation and exposes all research modes; it does
not bypass per-run provider-operation, model-token/cost, concurrency, or tenant
limits. Do not use an email address, browser-supplied role, or Supabase
`user_metadata` for this grant. Create/reset the account through Supabase Auth;
the application does not create or store a shared password. The default list
is empty.
