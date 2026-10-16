# Core reliability slice — implementation checklist

Follow-on 2026-10-14: [pre-dispatch admission and accounting operations](./extraction-admission.md)
close the persistence-only ceiling and missing operator-command gaps below.
This document retains the original slice's validation and boundaries for history.

Scope: coordinated retries, auditable estimated accounting, source ceilings,
per-source failure isolation and redacted operational telemetry. No queue,
checkpoint, HITL, billing, report-format or hosted database changes in this slice.

## Inspection and corrections

- Installed OpenAI 3.20.0 defaults to two retries. The application currently
  leaves these implicit. One retry owner is required, not nested retry wrappers.
- `model_budget.py` reserves $0.10 and a byte-length input heuristic. Tokens are
  reconciled only downwards; there is no model ProviderCall receipt. These are
  policy estimates, not invoices or guaranteed tokenizer bounds.
- `repositories/budgets.py` checks duplicate fingerprints before acquiring
  budget locks: concurrent identical requests can race the unique constraint.
- `ingestion.py` canonicalizes an entire search batch before isolation. Invalid
  URLs, unexpected response shape and cancellation can strand reservations.
- `research_limits.py` already preallocates source slots. Keep it and add an
  authoritative persistence ceiling under the existing run-row lock.
- Keep the source-persistence and ordered-outbox locks. Do not claim that they
  serialize provider network waits. No blanket lock removal.
- Versioned Markdown exists. Structured documents/immutable format exports,
  eight-source passage selection improvements and durable recovery remain later.
- Git history alone neither proves exposure nor proves secrets were never exposed.
  No CVE certification or dependency upgrade is included here.

## File-level delivery and acceptance gates

| Files | Change | Acceptance tests |
|---|---|---|
| `providers/retry_policy.py`, `config.py`, `graph/builder.py` | Explicit single-owner bounded retry policy, SDK retries disabled, finite timeouts and run-owned model client | Three maximum attempts, 429 recovery, no retry of ambiguous timeout/5xx, permanent rejection fails once, clients close, persisted cancellation stops retry and terminalizes the real graph |
| `pricing.py`, `model_budget.py` | Versioned default-model rate snapshot, per-attempt model call receipt and token/cost settlement | Successful usage reconciles both directions; missing usage stays estimated; unknown models remain policy estimates; zero search charge for model calls |
| `repositories/budgets.py` | Lock-before-dedup, atomic token admission, receipt-backed uncertain settlement | Duplicate concurrency has one reservation/dispatch, rejected reservations roll back, unresolved timeouts retain funds, receipt reconciliation is idempotent and tenant-scoped |
| `providers/tavily.py`, `ingestion.py` | Typed malformed response failures, safe pre-dispatch retry only, isolate invalid URLs/artifact failures, settle provider result before artifact I/O | Invalid URL cannot poison valid evidence; paid successful response remains accounted after storage failure; cancellation and invalid JSON leave no pending reservation |
| `ingestion.py`, `research_limits.py` | Persistence ceiling under retained run lock, quick-mode override, bounded extraction allowlist | Focused/Balanced/Deep stay at 6/12/20; concurrent ingestion cannot overshoot; quick explainers stay at two; unsolicited/duplicate extraction rejected; existing identities still merge discovery paths at full capacity |
| `telemetry.py`, associated tests | Bounded structured dependency outcomes, attempts, duration, accounting basis and source-rejection reasons | No prompts, URLs, provider bodies, credentials or exception messages in logs |

## Later gates, not claims of this slice

Worker crash/result replay, checkpoint security/versioning, approval-aware pause
tracking, lost-notification resync, duplicate run submission and cancellation
races require their own milestones. Start measurement now; do not require Redis
Streams, a specific queue or vectors without evidence. Existing PostgreSQL outbox
remains replay truth; any future notification must happen after commit.

## Validation and rollout

Use deterministic provider mocks and local PostgreSQL only. Preserve onboarding
changes already in the working tree. Do not apply migrations to hosted Supabase
or make paid provider calls. Record test results and unresolved boundaries below
after implementation. Existing pending/uncertain calls must not be refunded merely
because they are old. Recovery must require a trusted provider result receipt.

## Implemented result

The checklist's bounded slice is implemented without DDL, API contract changes,
hosted database writes, or paid provider requests. Model attempt/accounting metadata
uses the existing private ProviderCall JSON field; provider-returned accounting keys
are never interpreted as internal model metadata. Parent-task model-client ownership
is tested across graph child tasks, including failure cleanup.

The real LangGraph cancellation regression covers its installed
`NodeCancelledError` wrapper: persisted cancellation wins at the graph exception
boundary, the planner node and run terminalize as cancelled, exactly one terminal
event is emitted, accounting is released for the rejected attempt, and the parent
client closes. This does not establish crash recovery or all cancellation races.

The persistence ceiling is authoritative for stored sources. Existing graph slot
allocation bounds normal search/extract batches, but the added persistence check
does not reserve extraction slots across overlapping ingestor invocations. Such
overlap can fetch evidence later rejected at storage. Raw artifact failures are
observable, not silently counted as usable evidence. Database outages remain
fail-closed; durable recovery and startup/terminal task-write isolation remain later.

`reconcile_from_receipt` is a repository capability, not a scheduler or an operator
endpoint. Unknown outcomes lacking receipts remain reserved; no blind cleanup is
claimed. The eight-source/3,500-character evidence bundle remains unchanged and
exact-content deduplication is not publisher independence.

Validation on local infrastructure:

- 166 backend unit/integration tests passed with `RUN_AUTH_SCHEMA_TESTS=1`, including
  the disposable auth-schema/RLS migration test. Before this slice: 120 passed,
  one opt-in test skipped. Forty-five new regression cases were added.
- Strict mypy passed for all 37 source files; full service Ruff passed.
- 34 generated shared JSON Schema documents validated; no contract drift.
- 36 frontend and five shared-contract tests passed; workspace TypeScript checks
  and Next.js production build passed. Existing onboarding work was preserved.

This is deterministic regression/local persistence evidence, not live-provider
certification, invoice reconciliation, durable restart recovery or a load benchmark.

Primary references: [OpenAI SDK retries](https://github.com/openai/openai-python#retries),
[default model pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini),
[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search),
[Tavily Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract).
