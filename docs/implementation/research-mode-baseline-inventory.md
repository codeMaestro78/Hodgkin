# Research-mode baseline inventory

Task A, Phase 0 documentation baseline, inspected 2026-10-17 at commit
`260a1715628aff0e54ac35b00214f1536c2659a2`. This is a repository snapshot,
not a deployment attestation or completed cross-mode benchmark.
The [implementation plan](./research-modes-and-comprehensive-reports-plan.md)
defines later gates; benchmark fixtures/results belong to Agent B.

## Current behavior versus proposed contract

| Area | Observed implementation | Proposed; not enabled here |
|---|---|---|
| Mode | `reports.py::report_policy(calls)` infers Focused at ≤6, Balanced at ≤12, Deep above 12. Request has no explicit mode; `run_graph` derives quick-explainer routing from the question. | Persist explicit mode/policy. Null/absent mode means legacy; no historical backfill. Deep stays Deep with a small budget or evergreen question. |
| Budgets | `Budget`/`UsageLedger` persist provider calls and reservations. Search and extraction consume operations. `source_limit` derives source ceiling from calls; allocation caps each question at six sources. | Independent operation/source limits within existing ceilings. |
| Reflection | Planner requests source classes and success criteria. Deterministic reflection repairs the first failed subquestion at most once. | Persist dimension/requirement coverage and evidence-driven bounded repair. |
| Quality | Preserved-source check precedes synthesis; exact-span and semantic gates control findings. `report_document.py` emits `partial` or `insufficient_evidence`; `answered` is rejected for `evidence-links-v1`. | Preserve both gates and keep `answered` unavailable. Links do not prove requirement satisfaction. |
| Runtime | One LangGraph engine, durable jobs/checkpoints, persisted subquestions and internal parallel collection. | Extend the same engine. |

Evidence: `services/research-api/src/research_api/` files `reports.py`,
`research_limits.py`, `report_document.py`, `db/models.py`, `repositories/runs.py`,
and `graph/builder.py`; contracts in `packages/contracts/src/{research.ts,report.ts}`.
The [reflection page](../reflection.md) details the predicate and repair routing.

## Graph compatibility

`services/research-api/src/research_api/jobs.py` defines
`GRAPH_VERSION = "research-v4"` and
`SERPER_GRAPH_VERSION = "research-v5-serper"`. Both `enqueue` and `schedule_due`
pin new jobs according to `SERPER_DISCOVERY_ENABLED` at creation.

| Stored graph version | `jobs.claim` compatibility | Fresh graph discovery |
|---|---|---|
| v3 with immutable `report_requirements == []` | Accepted subject to lifecycle/recovery checks | Tavily |
| v3 with any other requirements, including `[""]` | Fails: `graph_version_incompatible` | No dispatch |
| `research-v4` | Accepted subject to lifecycle/recovery checks | Tavily |
| `research-v5-serper` | Accepted subject to lifecycle/recovery checks | Serper |
| v2 or unknown | Fails: `graph_version_incompatible` | No dispatch |

Here v3 means `research-v3`, v2 means `research-v2`.
`graph/builder.py::run_graph` contains a literal `research-v5-serper` comparison.
An existing job's version selects discovery despite later flag changes; without
a job version the flag is used. Saved checkpoints resume without replacing
their input. Never rewrite stored graph versions to reconcile prose.

Terminal runs are not reclaimed. Cancellation precedes version/recovery failure.
Otherwise, five prior attempts exhaust recovery even with a compatible version.

Historical v3/v4 descriptions and dated test receipts in
[mode-specific reports](./mode-specific-research-reports.md),
[quality foundations](./phase1-quality-foundations.md), and
[durable runtime](./durable-runtime.md) remain untouched. This inventory describes
the inspected checkout; those rollout notes do not establish deployed state.

## Migration chain

Files: `services/research-api/src/research_api/db/migrations/versions/`.
Local `alembic heads` and `alembic history` confirmed one linear repository chain:

```text
base → 0001 authoritative core → 0002 run idempotency
     → 0003 accounts → 0004 auth function grants
     → 0005 evidence reliability → 0006 extraction admission
     → 0007 durable runtime → 0008 structured reports
     → 0009 library → 0010 published shares/exports
     → 0011 model routing → 0012 report legacy insert compatibility (head)
```

`0012` restores older published-report insert compatibility, preserves published
update rejection, and deliberately disallows downgrade. It adds no explicit mode
or independent source budget. The lead reports local DB revision `0012`; Task A
did not query a database. Repo head does not prove hosted revision. No migration
was applied.

## Source metadata

`db/models.py::Source` persists canonical URL, title, nullable publisher and
publication date, provider, class, retrieval time, content hash, artifact
reference, quality score, discovery paths, and content signature. Identity is
unique on `(tenant_id, run_id, canonical_url, content_hash)`.

`ingestion.py` canonicalizes discovery URLs, preserves original discovery paths,
passes available publication dates, and inserts newly extracted sources with
`source_class="unknown"`. Cached reuse carries the cached class.
`repositories/sources.py::upsert` initializes publisher to `None`, accepts rather
than infers a class, and merges paths on existing sources. Planner `source_classes`
are requested strategy, not verified classification.

`Source` has no explicit ownership, DOI/work, syndication/dataset lineage
relationships, or independence confidence/basis fields. URL deduplication and
content signatures do not certify independence. Classification/independence
assessment remains proposed work; unknown remains an honest value.

## Test inventory and commands

Paths below are relative to `services/research-api/`.

| Existing tests | Coverage |
|---|---|
| `tests/integration/test_phase1_replay.py` | v3 empty-brief/v4 admission and exclusive leases; incompatible v3/v2/unknown fail once without upgrade; cancellation precedence; recovery cap; terminal immutability; default v4 enqueue. |
| `tests/integration/test_durable_runtime.py` | Incompatible jobs fail without dispatch; lease/checkpoint recovery, deadlines, repair approval, cancellation precedence. |
| `tests/integration/test_discovery_receipts.py` | Tavily/Serper fixture replay and quotas; tenant isolation; graph/checkpoint route pinning; v4/v5 enqueue and claim despite flag changes. |
| `tests/unit/test_citation_verification.py` | Literal artifact spans and rejection of paraphrased/missing quotes; supplementary evidence-gate coverage. |

The full v3/v4 lease-admission parameter matrix does not include v5; discovery
tests cover v5 enqueue/claim/provider pinning. Coverage is not exhaustive.

From `services/research-api/`, with the existing Python 3.12 environment:

```sh
.venv/bin/alembic heads
.venv/bin/alembic history
.venv/bin/pytest --collect-only tests/integration/test_phase1_replay.py tests/integration/test_durable_runtime.py tests/integration/test_discovery_receipts.py
.venv/bin/pytest tests/integration/test_phase1_replay.py tests/integration/test_durable_runtime.py tests/integration/test_discovery_receipts.py
```

Task A ran the first three commands: `0012` head, linear history, **56 tests
collected**. The lead separately reports **56 integration tests passed in 13.56s**,
**33 contract tests passed**, and local DB revision `0012`. These are attributed
lead receipts, not additional Task A executions. Integration execution requires
provisioned local infrastructure; `tests/conftest.py` enforces loopback endpoints.
No hosted infrastructure or live-provider execution is part of this gate.

For later contract work, the plan specifies root commands
`pnpm --filter @research/contracts generate`,
`pnpm --filter @research/contracts check:generated`, then
`services/research-api/scripts/generate-pydantic.sh CreateResearchRunRequestSchema`.
Generation writes files and was not run in this documentation-only task.

## Gate handoff

Task A owns only this inventory and `docs/reflection.md`; application behavior,
stored versions, historical reports, budgets, and evidence gates are unchanged.
Nothing is staged or committed. Unrelated untracked
`pricing-entitlements-billing.md` is outside scope.

Confidence is high for inspected repository behavior and migration history.
Hosted state remains unverified and outside scope. Benchmark fixtures/rubric,
receipt hashes, and per-mode quality/latency/cost summaries remain Agent B's
artifacts; test receipts alone do not complete that gate. The lead owns phase
acceptance and gate commits before code mutation.
