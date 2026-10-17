# Research modes: implementation and validation status

Updated 2026-10-17. Companion to the
[approved plan](./research-modes-and-comprehensive-reports-plan.md), not a
replacement for its acceptance gates. No hosted migration, paid benchmark,
deployment, push, PR, or merge is authorized by this document.

## Implemented locally

- Explicit `focused`/`balanced`/`deep` and server-owned
  `research-mode-policy-v1`; independent source/operation ceilings with
  tighten-only overrides. Deep identity survives smaller budgets and evergreen
  questions. Null remains legacy, with no historical mode backfill.
- Atomic admission/idempotency, immutable explicit brief/budget, mode inheritance
  on retry/follow-up, draft migration, passthrough-forwarding checks.
- Stable coverage dimensions/criteria and requirement routing in versioned plan
  artifacts. One server admission calculation for planning, editing, and UI/API
  limits; persisted allocations checked against the frozen budget.
- Observed DOI/content/publisher identity relationships with provenance, scoped
  foreign keys and forced RLS. Requested classes guide discovery, not observed
  classification. Unknown class/independence remains unknown.
- Immutable report v3 exposes only source-relationship edges whose endpoints
  are cited in that report. It publishes categorical observed confidence and a
  safe basis/identifier projection; internal hashes and metadata references
  are not exposed. Source independence remains `unknown`.
- The versioned criterion-review pass can nominate a potential disagreement
  only between at least two verified claims linked to every reviewed criterion
  in their shared dimension. Public records retain both sides, assessment
  basis/version, a deterministic non-factual reason, and unresolved
  `potential` status; they are never model-confirmed or auto-resolved.
- Immutable, tenant/run/plan-bound assessment manifests committed before paid
  writing. Write-once audited results and independent criterion assessments;
  final publication reuses the verified ledger without another writer call.
- Versioned report v3, strict cross-row references, honest requirement outcomes,
  claim-linked comparisons/provenance/conflicts, and V1/V2/V3/V4 readers.
- **Phase 4 evidence-verified narrative (graph `research-v9-evidence-narrative`,
  report v4, `narrative-composition-v1`).** After the writer and review gate,
  one bounded, strict-schema model call per run orders the verified findings
  into mode-specific blocks. Focused uses answer and trade-offs. Balanced adds
  per-dimension and implications blocks. Deep adds cross-source synthesis.
  Every sentence is either a reference to a verified finding or a new atomic
  explanatory claim citing 1–3 registered literal passages. New claims are
  restored to exact quotes and pass the unchanged exact-span and fully
  supportive semantic gate. Unsupported ones are persisted unpublished (no
  gap). The report renders exact claim text only, with no free connective
  prose. The proposal and its audits are part of the write-once assessment
  result, so publication and crash recovery replay receipts and never
  redispatch. Insufficient time, writer absence, malformed output or provider
  failure fall back to `not_composed` with a reason, and the verified ledger
  still publishes. v7 and v8 jobs keep report v2/v3. Python and Zod validators
  enforce mode roles, block and sentence limits, the answer-first rule,
  dimension references, citation equality with the finding, single
  placement, and count consistency. The web Checks panel shows the
  composition summary.
- Offline 20-question × 3-mode harness, authored synthetic regression receipts,
  schema/rubric/hash checks, and diagnostic counters separating provenance from
  criterion assessment. These are not live measurements or human gold labels.

## Deliberately unfinished

1. **Phase 4 limits:** narrative quality, readability and added latency/cost are not live-measured. Depth remains bounded by verified evidence, the 40-finding report cap and remaining active time; no length is promised.
2. **Phase 5 bounded gap repair:** implemented locally and default-off for newly created jobs. v13 graph versions preserve criterion-budget behavior without automatic repair; `BOUNDED_GAP_REPAIR_ENABLED=true` pins new jobs to v14 repair-capable graphs. Previously pinned repair-capable v10–v12 jobs retain their semantics. See [bounded-gap-repair-design.md](./bounded-gap-repair-design.md#implemented-design-v1-2026-10-17). At most one round, Balanced/Deep only, no approval-required runs; the base report is the fallback. Repair itself needs no new tables. Concurrent-admission, mid-repair cancellation, replay, and fallback integration tests passed on a disposable PostgreSQL 18 database migrated through `0018` on 2026-10-17; the report UI now has a dedicated stopped/repaired accessible rendering test. Broader browser/mobile/accessibility checks and live latency, cost, and quality measurement remain open.
3. **Phase 6 quality release:** one authorized live 20 × 3 pilot has run (receipt below). It measures operational latency, provider operations, model spend, source and finding counts, and narrative composition outcomes only. No blinded human review has been performed, and draft labels are not human gold. Adjudication and preregistered margins are still required before any mode-quality claim. Deep superiority, contradiction recall and independence improvements remain unproven. `evaluate_modes.py aggregate --require-release` reports the gate as blocked (exit 2).
4. `answered` remains unavailable; none of these steps certify literature-wide completeness.
5. Publication-time retrieval accounting is stored separately from the report document, frozen by the existing published-report trigger, included in report integrity hashing, returned with the selected report version, and rendered in report Markdown. Legacy reports keep a null snapshot. Migration `0018` has been tested only in a disposable PostgreSQL 18 container; it has not been applied to a shared local or hosted database.

## Persistence and rollout

Additive migrations: `0013` explicit modes/budgets/immutability, `0014` source
identity/relationships, `0015` assessment manifests/results, `0016` report-v3
CHECK compatibility, `0017` report-v4 CHECK compatibility, `0018`
publication-time retrieval-accounting snapshots, and `0019` forward
brief/budget snapshot guards for installations that already applied the older
`0013`. `0016`–`0019` remain checkout-only. The shared local app database was
last reported at `0015`; the current app requires at least `0018` for report
snapshots, and `0019` is required before relying on the strengthened guards.
Disposable loopback migration and report-publication validation through `0018`
passed; the same disposable database then upgraded to `0019`. No assumption is
made about the configured Supabase revision or backups.

Fresh bootstrap `0001` now creates/grants only its historical table set; later
tables must not be accidentally precreated through current ORM metadata before
their own RLS/triggers. Disposable tests cover committed intermediate revisions
through `0018`, including V3/V4 report acceptance, snapshot constraints and
immutability. Existing
installations already passed `0001`; editing that file
does not retroactively repair an arbitrary external intermediate schema.

Application rollback retains additive schema and published documents. These
migrations intentionally refuse destructive downgrade. Assessment erasure needs
a separately authorized privileged, FK-ordered cleanup; runtime cannot delete
write-once evidence provenance. Retention/privacy operations are not newly
implemented here.

## Reproducible gates (local infrastructure only)

From `services/research-api`:

```sh
uv run pytest -m 'not live_provider'
uv run ruff check .
uv run ruff format --check .
uv run mypy src/research_api
```

Opt-in disposable checks: `RUN_BOOTSTRAP_SCHEMA_TESTS=1` creates isolated
loopback databases for migration targets including `0016`, `0017`, and `0018`;
`MODE_ASSESSMENT_TEST_DATABASE_URL` continues to target a generated
`mode_assessment_test_*` loopback database at revision `0015`. Use fixture-local
credentials, never the hosted database. Tests enforce destination checks.
`RUN_AUTH_SCHEMA_TESTS=1` enables the existing local auth-schema migration gate.

From the repository root:

```sh
corepack pnpm --filter @research/contracts test
corepack pnpm --filter @research/contracts check:generated
corepack pnpm --filter @research/contracts typecheck
corepack pnpm --filter @research/web test
corepack pnpm --filter @research/web lint
corepack pnpm --filter @research/web typecheck
corepack pnpm --filter @research/web build
git diff --check
```

Targeted suites include `test_explicit_modes.py`, `test_mode_assessment_graph.py`,
`test_mode_assessment_persistence.py`, `test_bootstrap_security.py`,
`test_source_relationships.py`, `test_v2_consumers.py`, `test_coverage.py`,
`test_criterion_review.py`, `test_report_document_v2.py`,
`test_report_document_v3.py`, `test_report_document_v4.py`,
`test_narrative_composer.py`, `test_mode_composer.py`,
`test_bounded_repair_graph.py`, and `unit/test_bounded_repair.py`. Graph tests replace SDK/provider I/O; they test real
accounting/replay/persistence, not live network latency. Final receipts must be
recorded after the last source edit, not inferred from an earlier passing run.

### Phase 5 local receipt (2026-10-17)

After the report-snapshot source edits: backend unit suite passed; Ruff and mypy
passed; web tests **203 passed** and typecheck passed. On the isolated PostgreSQL
18 container, migration/bootstrap validation passed for targets through `0018`,
and the report publication/API readback test passed (6 parameterized cases).
`git diff --check` passed. No live provider calls, shared-database migration, or
Supabase change occurred.

### Phase 6 live pilot receipt (2026-10-17)

The user authorized the full 20 × 3 workload with a $3.00 model-spend cap. Command:
`scripts/live_mode_evaluation.py --max-model-usd 3.00`, run on a disposable loopback
database at `0017` that was dropped afterwards, with local S3. Snapshot:

- model `gpt-4o-mini`, providers OpenAI and Tavily;
- graph `research-v9-evidence-narrative`, policy `research-mode-policy-v1`;
- source tree sha256 `46a2bacb…`.

Raw receipts and observations were kept outside the repository.

| Mode | Runs | p50 / p95 end-to-end | Median sources | Median verified findings | Tavily ops | Model spend | Narrative composed |
|---|---|---|---|---|---|---|---|
| Focused | 20/20 completed | 24.3 s / 30.7 s | 6 | 10 | 118 | $0.054 | 13/20 |
| Balanced | 20/20 completed | 33.8 s / 41.1 s | 11 | 18.5 | 160 | $0.083 | 19/20 |
| Deep | 20/20 completed | 41.2 s / 50.0 s | 18 | 19.5 | 234 | $0.106 | 18/20 |

Totals: 60/60 V4 reports published, 0 runner errors, $0.243 settled model spend and
512 Tavily operations. Every uncomposed narrative fell back to the verified ledger with
reason `no_supported_sentences`.

Observations from this pilot:

- Deep used at most 12 of its 20 provider operations and found about one more median
  finding than Balanced. Deep's extra budget is not being spent. Investigate planning
  and fan-out before making any depth claims.
- Focused composed a narrative in only 13/20 runs.
- The `core_dimension_coverage` value of 0 means "not measured": live dimension
  states stay `unknown` until human adjudication.
- Finding counts are not quality. Precision, citation correctness and usefulness are
  not established.

### Phase 4 local verification receipt (2026-10-17)

- Full backend suite (`-m 'not live_provider'`) on a generated disposable
  loopback database at `0017`: **1,250 passed, 16 skipped**, including 26
  graph tests in `test_mode_assessment_graph.py`. These cover narrative
  publication, unsupported new claims kept unpublished, crash replay after the
  narrative receipt, composition failure, invalid and empty proposals,
  insufficient time, and v8 compatibility.
- `RUN_BOOTSTRAP_SCHEMA_TESTS=1 test_bootstrap_security.py`: **5 passed**,
  including the `0017` target (v4 insert, tenant read, immutability).
- Contracts: **147 passed**, 59 generated JSON Schemas verified, typecheck
  passed. Web: **198 passed**, lint, typecheck and production build passed.
- Ruff check, format check (**217 files**), mypy (**85 source files**), and
  `git diff --check` passed.
- Browser fixtures: answer, automation, frontend-regressions, onboarding,
  orchestration, reliability, report-content, responsiveness, share and
  workspace pass. `check.js`, `failure-check.js`, `phase1-check.js` and
  `synthesis-check.js` fail on expectations unrelated to reports (for example
  client-side Focused budget overrides that the committed server-owned mode
  policy removed). They need a separate fixture update.
- No hosted database, deployment, paid provider, push, PR or merge was used.

### Phase 5 final regression receipt (2026-10-17)

- Full backend suite (`-m 'not live_provider'`) passed on a generated,
  disposable loopback PostgreSQL 18 database migrated through `0018`:
  **1,338 passed, 11 skipped, 1 deselected**. This includes bounded-repair
  concurrent admission, cancellation during repair, receipt replay, and the
  publication-time retrieval-accounting snapshot.
- The historical v8 test now pins `RuntimeJob.graph_version`, matching the
  immutable runtime contract. The Tavily ingestion assertion checks its
  persisted retrieval counts while leaving upstream exclusion counts unknown.
- Ruff and formatting checks passed for the adjusted integration tests;
  `alembic heads` reports `0018 (head)` and `git diff --check` passed.
- The exact temporary PostgreSQL container was removed after validation. No
  shared local database or Supabase project was changed. This run used no live
  model/provider calls.

### Final checkout review receipt (2026-10-17)

- Full backend suite against a fresh disposable PostgreSQL database at revision
  `0019`: **1,358 passed, 11 skipped, 1 deselected**. Bootstrap tests included
  the forward upgrade from stale `0018` mode guards and verified the migrated
  trigger rejects a real explicit-brief mutation.
- New graph-version gate: explicit-mode submissions default to v13
  (criterion-budget behavior, repair off); `BOUNDED_GAP_REPAIR_ENABLED=true`
  pins new submissions to v14. Existing pinned v10–v12 jobs keep their
  original semantics. Routing tests cover all Tavily/Serper/OpenAlex
  combinations; repair and assessment integration suites pass with repair
  explicitly opted in where appropriate.
- Ruff, repository-wide format check (**241 files**), and mypy (**93 source
  files**) passed. Web: **206 tests passed**, typecheck passed. Contracts:
  **148 tests passed**, 63 generated schemas verified, and typecheck passed.
- The Playwright composer regression passed for focus recheck, no remount,
  reload persistence, and account-switch isolation. Its console log showed only
  the fixture's missing favicon 404 and React DevTools informational messages.
- All database tests used named disposable loopback databases. No shared local
  application schema, Supabase project, paid provider, deployment, PR, or GitHub
  push was changed by this validation.

### Phase 3 local verification receipt (2026-10-17)

- Full backend suite on a generated disposable loopback database at revision
  `0016`: **1,192 passed, 16 skipped**. The skips are opt-in/live-provider
  checks; no provider calls were made.
- Targeted disposable migration/bootstrap check at `0016`: **1 passed**. It
  inserted a v3 report, read it through the tenant-scoped runtime role, and
  confirmed published-report mutation remains rejected.
- Contracts: **128 passed**, 58 generated JSON Schemas verified, TypeScript
  typecheck passed.
- Web: **195 passed**, typecheck and lint passed.
- Ruff check, repository-wide Ruff format check (**204 files**), mypy
  (**82 source files**), and `git diff --check` passed.
- The shared local application database remained at revision `0015`; the
  disposable test database was separate. No hosted database, deployment, paid
  provider, push, PR, or merge was used for these checks.

## Key files

- Policy/admission: `mode_policy.py`, `mode_planning.py`, `api.py`, `runtime_api.py`,
  `repositories/runs.py`, `research_limits.py`.
- Graph/replay: `graph/builder.py`, `jobs.py`, `model_budget.py`,
  `repositories/assessments.py`, `db/assessments.py`.
- Source provenance: `source_identity.py`, `repositories/source_relationships.py`,
  `db/source_relationships.py`, `ingestion.py`.
- Reports: `report_document.py`, `report_document_v2.py`, `report_document_v3.py`,
  `report_document_v4.py`, `narrative_composer.py`, `mode_composer.py`,
  `criterion_review.py`, `coverage.py`, `packages/contracts/src/report.ts`.
- Readers: `apps/web/lib/report-document.ts`,
  `apps/web/app/components/report-coverage.tsx`, comparison/share/export APIs,
  `scripts/benchmark_focused.py`.
- Evaluation: `services/research-api/scripts/evaluate_modes.py` (offline schema and
  aggregate) and `services/research-api/scripts/live_mode_evaluation.py` (live runner;
  see [evaluation.md](../evaluation.md)).

Paths without a prefix refer to `services/research-api/src/research_api/` unless
otherwise indicated. Existing untracked pricing/billing documentation is separate
user work and is not modified or staged by this implementation.
