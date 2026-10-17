# Phase 5 design: bounded gap repair

Status: **implemented locally, default-off for new jobs, not deployed.** New
explicit Balanced and Deep jobs that do not require approval run at most one
bounded repair round only when `BOUNDED_GAP_REPAIR_ENABLED=true` at enqueue
time. Default v13 graphs do not repair; v14 pins the opt-in repair capability.
Previously pinned repair-capable v10–v12 jobs retain their historical
semantics. Focused and approval-required runs never repair. See "Implemented
design" below; sections 1–8 are the original draft, kept for rationale. Live
latency, cost and quality are not measured.
Companion to the [plan](./research-modes-and-comprehensive-reports-plan.md)
(Phase 5) and the [status record](./research-modes-implementation-status.md).

## 1. Problem

After `assess_evidence`, some mandatory coverage dimensions can remain
`evidence_found`, `unresolved`, or `searching`. Repair should run a small number
of targeted delta searches for those dimensions and publish only the newly
verified findings, without:

- exceeding any frozen run budget (operations, sources, time, tokens, cost);
- re-dispatching an uncertain paid call;
- discarding or rewriting evidence, claims, audits, or the assessment already
  committed;
- reporting a dimension as covered without criterion review.

The current graph cannot do this safely. Re-running the whole writer, review,
criterion and narrative pipeline has a worst-case token and time cost that does
not fit default Focused or Balanced budgets.

## 2. Existing foundations (reuse, do not replace)

| Foundation | Location | Role in repair |
|---|---|---|
| `decide_repair` / `RepairInput` / `RepairDecision` | `coverage.py` | Pure, deterministic proposal selection within the task, round and resource limits. Never reserves or dispatches work. |
| `ResourceAllowance` / `BudgetSnapshot` | `coverage.py` | The six resource units every proposal must fit, against both the run budget and a repair sub-budget. |
| Write-once assessment manifest and result | `db/assessments.py`, `repositories/assessments.py` | Pins sources, passages, requests and routes before paid work. Repair adds *new* rows; it never mutates these. |
| `model_response` receipts and reservations | `model_budget.py`, `ProviderCallReservation` | Fingerprinted replay; an uncertain call raises `ReservationReplayError` instead of redispatching. |
| Exact-span and semantic gate | `exact_reviews`, `_audit_assertions` | The only publication authority for every repaired claim. |
| Narrative v4 | `narrative_composer.py`, `report_document_v4.py` | Repaired findings enter the narrative only as ledger references. |

## 3. Proposed flow (delta assessment)

```
assess_evidence (v9, committed)
   │  coverage + repair_decision (pure)
   ▼
repair_admission ── atomic reservation of the whole round allowance ──► stop (budget/time)
   │
   ▼
repair_collect (≤ max_tasks_per_round targeted searches, source cap)
   ▼
repair_assess  (delta manifest pinned → writer on NEW passages only →
                exact + semantic review → criterion review for repaired dimensions)
   ▼
synthesizer    (base ledger ∪ verified delta findings; narrative over the union)
```

1. **Decision.** Use `decide_repair` with a non-zero policy for the mode
   (proposed: Focused 0 rounds, Balanced 1 round × 2 tasks, Deep 1 round × 4
   tasks). Only mandatory dimensions that are not `verified_covered`, and that
   have an eligible candidate query, are proposed. Conflicts are **not** a
   repair trigger in v1: searching for a tie-breaker invites one-sided
   resolution.
2. **Admission.** In one transaction, lock the run budget, check
   `used + reserved + round allowance ≤ limits` for all six units, and write a
   `repair_round` row (`proposed → admitted`) with the reserved allowance. If
   any unit does not fit, record `stop_reason="budget"` and publish the base
   assessment. The time check uses the same publication margin as the
   narrative pass; the round is skipped if it cannot finish before the deadline.
3. **Collection.** Each admitted task runs one targeted search with its share of
   the source cap. New sources are deduplicated against the base manifest by
   canonical identity and content hash. Existing sources are never re-fetched
   or re-hashed.
4. **Delta assessment.** Pin a *delta manifest* that references the base
   assessment ID, lists only new passages, and fixes the writer, review and
   criterion requests before dispatch. The writer sees only new passages and
   the affected dimensions. All claims pass the unchanged exact and semantic
   gate. Criterion review runs only for the repaired dimensions, using
   base ∪ delta verified claims.
5. **Publication.** The synthesizer merges the base audited ledger with verified
   delta claims (stable IDs `uuid5(delta_assessment_id, "claim:i")`), recomputes
   coverage only for repaired dimensions, and composes the narrative once over
   the union. Without a committed delta result, publication uses the base
   result unchanged.

## 4. Persistence

Original pre-implementation proposal (superseded by the v1 design below):

- `research_repair_rounds`: tenant/run/assessment-scoped, `round_number`,
  `decision` (JSON, the `RepairDecision`), `allowance` (JSON), `state`
  (`proposed | admitted | collecting | assessing | completed | stopped |
  failed`), `stop_reason`, timestamps. Unique `(tenant_id, run_id,
  round_number)`. Forced RLS and tenant FK like the assessment tables.
- `research_assessments` gains no columns. The delta assessment is a new
  write-once row with `parent_assessment_id` (nullable FK) and
  `kind = 'repair_delta'`.
- State transitions are forward-only (a trigger rejects regressions). Rows are
  never deleted by the runtime role.

## 5. Replay and crash safety

| Crash point | Recovery |
|---|---|
| After decision, before admission commit | The decision is pure; recompute it from the committed assessment and re-attempt admission. |
| After admission, before any dispatch | Resume from `admitted`; the reservation already exists, so no double reservation. |
| During search or ingestion | Provider operations use the existing per-task idempotent attempt rows; completed sources are reused. |
| After a writer, review or criterion receipt | `model_response` replays by fingerprint. An uncertain call fails the delta closed (`stop_reason="uncertain_dispatch"`) and the base result is published. |
| After the delta result commit | The synthesizer reads the committed delta; no paid call repeats. |
| Cancellation or approval interrupt | Propagated, as in `assess_evidence`. Unused reservations are released in the same transaction that records `stopped`. |

Graph compatibility is now pinned as follows: new explicit-mode jobs default to
v13, which has repair disabled; the `BOUNDED_GAP_REPAIR_ENABLED` opt-in pins new
eligible jobs to v14. Previously pinned v10–v12 jobs retain their original
semantics, and v9 jobs remain no-repair. The migration head in this checkout is
0019; that does not establish the revision of any shared or hosted database.
Every graph continues to publish the report version encoded by its topology.

## 6. Report and UI

- Report v4 stays valid. A future v5 may add a `repair` summary (rounds,
  admitted tasks, stop reason, repaired dimension IDs) without changing
  finding semantics.
- Methodology and the run timeline show repair as
  `proposed / admitted / running / completed / stopped / failed` with the stop
  reason. Collected evidence remains visible after any stop or failure.

## 7. Acceptance tests (required before enabling)

1. Failure injection at decision → admission → dispatch → provider result →
   persistence → checkpoint: no over-budget work, no duplicate uncertain
   dispatch, no dropped base evidence, no false `verified_covered`.
2. Concurrent workers on the same run: exactly one admission per round.
3. Budget exactly at the limit: the round is stopped with `budget`, and the
   base report publishes.
4. Cancellation mid-round releases the unused reservation, and the base evidence
   stays inspectable.
5. Cross-tenant reads and writes of repair rows are denied (RLS).
6. v9 jobs never enter repair, and their report v4 output is byte-identical.
7. Live latency and cost of repair are measured in the Phase 6 evaluation before
   any product claim.

## 8. Open decisions

- Per-mode round and task limits. Proposed above; confirm against Phase 6 budgets.
- Whether Focused should ever repair. Proposed: no.
- Whether a repaired dimension needs at least one new independent source.
  Independence is still `unknown`, so v1 does not require it.

## Implemented design (v1, 2026-10-17; repository migration head later advanced to 0019)

The repair round itself reuses existing tables and required no migration when
implemented. The repository later advanced to `0018` for a separate immutable
report retrieval-accounting snapshot and `0019` to reapply forward
immutability guards; neither migration adds repair-specific tables.

- **Reservation.** `planning_admission(repair=True)` withholds operations and
  sources for one round at planning time: Balanced 4 ops / 2 sources, Deep
  8 ops / 4 sources, Focused and zero-round budgets 0.
- **Decision.** After the base assessment publishes its write-once row,
  unmet mandatory dimensions become deterministic candidates
  (`_repair_candidates`; queries built from pinned plan labels only, capped at
  `REPAIR_QUERY_CHARS`). The base result records `repair_status =
  bounded_delta_repair_v1` and the proposals.
- **Admission.** `planner_delta` → `admit_repair`, under the run lock,
  rechecks operations, sources, remaining time (allocation + 120 s
  publication tail), tokens and cost. Denial records a reason and the base
  report publishes. Success creates one child `ResearchPlan` (version + 1)
  with `repair` metadata and one sub-question per candidate (one search slot
  each). Replay finds the existing child plan by `base_assessment_id`.
- **Collection.** `research_worker` caps repair allocations at 1 and bounds
  dispatch with `asyncio.timeout` ending at the publication tail; a timeout
  keeps whatever was persisted.
- **Delta assessment.** A second write-once assessment row on the child plan
  pins a manifest with base pins + new source pins, the delta writer request
  and passage registry. Only new, non-duplicate sources are read (union capped
  at 20 sources and 40 claims). One delta writer call drafts at most
  `min(40 − base claims, 4 × questions)` claims; exact-span and semantic
  review run over the union; base reviews are reused unchanged.
- **Publication.** If at least one delta claim is fully supported, the union
  is published (narrative composition time-bounded to leave 20 s margin).
  Otherwise the run completes with the **base** assessment
  (`publication: "base"`) and a stop reason: `no_new_evidence`,
  `claim_capacity_exhausted`, `insufficient_time`, `timeout`, `failed`,
  `no_delta_claims` or `no_verified_delta_claims`. Collected base evidence is
  never discarded.
- **Replay.** Crash at admission, collection or delta review replays from the
  checkpoint and persisted receipts; no duplicate provider dispatch.

### Covered by tests

`tests/integration/test_bounded_repair_graph.py`: repaired union happy path;
base fallbacks (`no_new_evidence`, `failed`, `no_delta_claims`,
`insufficient_time`); admission recheck denial; crash replay at
`planner_delta` and at delta review; v9 jobs unchanged. Unit:
`tests/unit/test_bounded_repair.py`, `test_mode_planning.py` reservation split.

### Remaining validation

The concurrent-worker admission and mid-round cancellation scenarios now have
dedicated integration tests in `tests/integration/test_bounded_repair_graph.py`.
They passed against the disposable PostgreSQL 18 database migrated through
`0018` on 2026-10-17, alongside the repair replay/fallback tests and full backend
suite. A focused web test now covers repaired
and stopped status text, counts, and the polite live region. The broader report
canvas still needs browser-level long-report, mobile, and assistive-technology
checks. No live quality, latency, or cost claim is established by these tests.
