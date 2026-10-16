# Phase 1: report quality and workflow continuity

## Scope and architectural decision

This slice adds report requirements to the existing planner/writer calls, a
versioned structured evidence document, conservative answer-quality presentation,
account-scoped composer recovery, and local history projection updates. It does
not introduce another queue, model call, provider, retry layer, or budget increase.
Exports, library/projects, ingestion, threads, sharing and monitoring remain later
milestones. Markdown download and browser printing continue to work.

`ResearchRun.status` remains execution state. It must not be used as proof that
the research question was satisfactorily answered. A completed execution can
produce `partial` or `insufficient_evidence` answer quality.

## Report document v1

- `reports.document` is nullable JSONB, bounded to 512 KiB by migration `0008`.
- Existing Markdown reports stay unchanged. Null documents are presented as
  `not_assessed`; no retrospective verification or coverage is inferred.
- V1 includes mode, section membership, the mandatory original question, explicit
  requirements, question/evidence associations, and quality metadata.
- Finding, citation and source references use persisted UUIDs, not display numbers.
  Report, claims, citations, gaps and document commit in the existing publication
  transaction. A failed publication does not leave a half-published document.
- Zod/JSON Schema/generated Pydantic describe the shape; deterministic validation
  additionally checks internal IDs, section placement and assessment consistency.
- Only findings admitted by the existing exact-span and fully supportive semantic
  gate can enter the document. Rejected candidates remain in the audit records.
- API report-version selection returns the assessment for that exact version.

## What coverage means (and does not mean)

The writer may nominate zero-based requirement indices. Invalid indices are
ignored, and nominations from excluded findings never become published links.
An `addressed` entry means **evidence linked**, not independently established
fulfillment. Sub-question associations use collection provenance, not a semantic
coverage guarantee. Keyword overlap does not establish satisfaction.

The original free-text question is always retained and its completeness remains
unassessed. V1 emits `partial` when verified findings exist and
`insufficient_evidence` otherwise. The shared status vocabulary reserves
`answered` for a future independently validated acceptance policy; this
assessment version cannot certify it. No minimum word count pads thin evidence.

Focused, Balanced and Deep retain the existing 6/12/20 source and provider-operation
ceilings, 12/24/40 candidate bounds, and active-time/token limits. Requirement-aware
passage ranking stays inside the same context allowance. The quick path retains
its existing two-operation behavior. Requirements do not silently increase effort.

## Recovery and compatibility

New jobs use `research-v4`. Existing `research-v3` jobs are admitted only when the
immutable run brief has an empty requirement list: their paid request/parser
contract is unchanged. V3 jobs with requirements fail closed with
`graph_version_incompatible`; operators may explicitly create a fresh attempt.
Unknown versions stay rejected. Cancellation still takes precedence. Stored job
versions are not silently rewritten, and uncertain spend is not refunded or
redispatched without existing receipt proof.

Requirements are read tenant-scoped from the immutable run brief rather than
copied into checkpoints. Existing report receipts are reused; stored reports are
not reassessed on recovery. Initial planning reads budget and requirements in one
query, avoiding an added database round trip.

## Frontend continuity and privacy

- Optional requirements: one nonblank line each, at most 20, 500 characters each.
- Drafts use a bounded, versioned `sessionStorage` envelope keyed by the verified
  public account ID. No credentials, session objects or tokens are stored.
- Storage failure is nonfatal. Failed submissions retain the draft; only successful
  creation clears it. Hydration must not overwrite edits or leak another account's
  draft. Session drafts are local browser data, not cross-device persistence.
- Submissions include a draft-account consistency hint checked against the BFF's
  verified identity on that same request. A mismatch returns 409 without upstream
  dispatch; the hint is never trusted as identity or forwarded to the service.
  Account-generation guards prevent late responses from changing another account's
  composer. This adds no per-submission authentication preflight round trip.
- History subscribes to validated local snapshot notifications. Updates patch
  existing rows and replay over an older in-flight list response. This is not an
  authorization boundary or a replacement for the durable SSE outbox.
- Manual history refresh remains available. Existing independent scroll regions,
  keyboard behavior and reduced-motion safeguards are preserved.
- Structured-document parsing is memoized by the selected document, not repeated
  for every follow-up keystroke. This is not a measured production speed claim.

## Validation and rollout

1. Generate contracts and Python models; verify generated output is stable.
2. Run unit/contract tests, full local integration tests with paid boundaries
   mocked, lint/type checks and the Next.js production build.
3. Exercise composer recovery, requirements, failure retention, history updates,
   assessment/legacy UI, reduced motion and mobile overflow in the isolated browser
   fixture. No live user sessions or paid research are needed for these tests.
4. Rehearse `0008` on loopback PostgreSQL; retain existing RLS and role grants.
5. Apply `0008` with the migration principal before deploying updated runtime code.
   Hosted application is a separate authorized operation, not implied by local tests.
6. Roll back application code without dropping the additive column. Downgrading
   the migration deletes structured documents and is not the normal rollback path.

Regression gates cover long questions, duplicate requirement text, invalid IDs,
zero findings, rejected/contradicting/nonexact evidence, legacy/versioned reports,
atomic publication, unchanged request replay, incompatible jobs and cancellation.

Existing `operation.outcome` node/provider timings and request IDs remain the
latency measurement inputs. Local fixture timings are not production P50/P95.
Before claiming faster research, benchmark queue wait, submission acknowledgement,
first evidence and publication by mode with a fixed workload/environment and
report the distribution, cost and quality together. No production latency target
or quality certification was invented by this slice.

## Validation receipt — 2026-10-16

- Full local backend suite, including disposable auth/RLS schema checks:
  **489 passed**, one live-provider test deselected. Paid boundaries were mocked.
- Contracts: **30 tests passed**; web: **83 tests passed**.
- Isolated browser fixture: **36 checks passed**, zero defects, including account
  switching during submission, stale focus responses, draft recovery, history
  updates, legacy/partial reports, mobile overflow and reduced-motion preference.
- Type checks, repository lint scripts, Python Ruff checks, strict mypy and the
  Next.js production build passed. All 12 touched Python files passed formatting;
  the unrelated pre-existing citation-test formatting difference was not edited.
- All 38 generated JSON Schema documents validated. Regenerating the structured
  report's Pydantic model produced the same SHA-256 hash.
- After these gates, authorized migration `0008` was applied to configured
  Supabase. Metadata verification confirmed the nullable JSONB column, validated
  constraint, enabled/forced report RLS, and denied direct report SELECT for
  `anon` and `authenticated`. No hosted research records were rewritten.

This receipt does not establish live-provider answer quality, production P50/P95,
or deployment of the updated application. Those checks remain explicit rollout
gates, not claims implied by the synthetic tests or schema migration.
