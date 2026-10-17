# Phase 2 G: truthful source identity and observed relationships

Status: after explicit lead GO following the Phase 1 gate, **0014 is applied only
to localhost:55432/research** and the source PostgreSQL tests pass. The ingestion
hook is implemented for explicit modes only. No hosted writes, provider calls, or global backfill were
performed. This slice implements the source identity
portion of [the phased plan](research-modes-and-comprehensive-reports-plan.md#phase-2--persisted-coverage-plan-and-truthful-source-metadata).
It does not complete coverage plans, report v2, or the Phase 2 exit gate.

This file is a chronological implementation/validation log; its early receipts
describe the state at that point (including the local 0014-only checkpoint).
For the current consolidated checkout, local-only migration status, and remaining
report-level provenance/conflict work, see the
[implementation status](./research-modes-implementation-status.md) and the
[current plan audit](./research-modes-and-comprehensive-reports-plan.md#2-current-state-audit-verified-2026-10-17).

## Main integration contract

```python
async def persist_source_relationships(
    session: AsyncSession, tenant_id: UUID, run_id: UUID, *,
    observed_identities: Mapping[UUID, SourceIdentity] | None = None,
) -> int: ...

inserted_rows = await persist_source_relationships(
    session, tenant_id, run_id, observed_identities=new_extraction_identities,
)
```

It returns newly inserted relationship rows, not source or
independent-work counts. Use the caller's tenant-scoped ingestion transaction after
flushing sources. There is no commit, budget change, provider call, or gate change.
The convenience function reads at most 21 current-run sources and rejects runs
with more than 20 instead of silently truncating. For explicit batch control use
`SourceRelationshipRepository(session, tenant_id).link_sources(*, run_id,
source_ids, observed_identities=None)`. Empty batches return zero; missing,
duplicate, cross-run and cross-tenant IDs reject the batch before writes.

**No new Source fields are required.** `source_identities` stores nullable
`work_id` and `publisher`, plus nonnull JSONB `metadata_basis`, keyed by
`(tenant_id, run_id, source_id)` with a composite Source FK. Only explicitly
supplied new-extraction observations create identity records, with first-writer
`ON CONFLICT DO NOTHING`. Ordinary linking does not backfill identity rows.
Legacy Source rows, classes and publisher values remain untouched.

No independence column is needed. Importing `db.source_relationships` appends
`UniqueConstraint("tenant_id", "run_id", "id", name="uq_sources_tenant_run_id")`
once and registers both new models, matching the isolated assessment model's
pattern. Alembic env.py now imports it. Ingestion imports the repository/function,
registering the application models without circular
imports or edits to shared models.py. Fresh bootstrap now restricts 0001 to its
historical table allowlist, leaving new tables to their owning revisions. 0014
also tolerates previously precreated tables via checkfirst. Downgrade intentionally
preserves provenance; application rollback retains the additive schema.

Use the pure mapper before Source persistence:

```python
identity = map_source_identity(
    canonical_url=observed_canonical_url,
    observed_urls=observed_discovery_or_redirect_urls,
    publisher=verified_publisher_or_none,
    publisher_basis={
        "basis": "structured_metadata",  # or adapter_metadata
        "evidence_ref": "artifact-ref#publisher-field",
    },  # omit when metadata has not been verified
)
```

Pass `{new_source.id: identity}` as `observed_identities` after source flush.
The repository persists identity fields in `source_identities`, never in Source.
`metadata_basis.work` contains `basis=observed_doi_url` and actual resolver `urls`;
`metadata_basis.publisher` contains `basis`, `evidence_ref`, and `value`. These
inputs are a trust boundary: adapters must supply metadata they actually observed
and validated, never model/planner suggestions or a host-derived owner. This
module does not fetch or verify external publisher evidence itself. The repository
rederives work identity from observed canonical/discovery URLs and stored identity
basis rather than trusting work_id alone. It rereads first-writer identity records
before linking so a replay cannot replace their publisher/DOI basis.
Keep observed URL inputs within the existing admission/discovery bounds. DOI URLs
found as arbitrary references in a page body are not the page's own work identity.

## Truth and persistence rules

- Only observed HTTP(S) doi.org/dx.doi.org resolver paths establish normalized
  `doi:10.…` work IDs. Conflicting DOIs leave work identity unresolved. No DOI is
  inferred from a title, hostname, bare string or desired source class.
- Source class stays `unknown` here, including academic hosts and DOI pages.
  Main may separately retain classes established by trustworthy adapter evidence.
- `same_content` requires equal stored SHA-256 hex content hashes; `same_work`
  requires equal observed DOI identity; `same_publisher` requires equal publisher
  names with verified metadata evidence on both endpoints. Exact publisher
  equality is conservative; aliases and corporate ownership are not inferred.
- Confidence is the categorical `observed`, with versioned JSON basis per row.
  It describes an observed match, not a probability, authority or independence.
  Distinct hashes, hosts or works do not assert independence. Syndication,
  citations, datasets and owner relationships remain unassessed.
- Sort UUID endpoints for symmetric identity; no self-links. Composite primary
  key `(tenant_id, run_id, from_source_id, to_source_id, kind)` enforces uniqueness.
  One batched PostgreSQL relationship `ON CONFLICT DO NOTHING` insert makes replay idempotent
  and retains the first basis. At most 190 pairs / 570 relationship rows per call.
- Both composite foreign keys include tenant, run and source. They cascade on
  source deletion. The PK indexes the from endpoint and tenant/run reads; a
  separate tenant/run/to index covers reverse endpoint deletion and lookup.
- Force tenant RLS with USING and WITH CHECK. Revoke PUBLIC/anon/authenticated;
  grant only SELECT, INSERT, DELETE to research_app. No UPDATE permission: replay
  cannot rewrite provenance. No new weaker publication or corroboration gates.

## Validation and release handoff

Run scoped Ruff/mypy and the two test files from `services/research-api` using the
existing virtual environment. Offline tests cover DOI evidence, ambiguity,
unknown semantics, bounded pairs, scoped repository SQL, conflict keys and held
migration security statements. No schema is created during these checks.

The lead authorized local migration application after reporting the Phase 1 gate
passed. The ingestion call now targets the existing local revision 0014 schema.
Set `PHASE2_G_POSTGRES_GO=1` for the integration test file. Those tests require
loopback PostgreSQL with 0014 already present; they never migrate or create schema
and roll back all fixture data. They exercise actual conflict replay, tenant
visibility, denied writes and composite endpoint constraints. Hosted application and deployment require
separate explicit authorization.

Preparation receipt (2026-10-17): scoped Ruff checks and formatting, strict mypy
on the four new implementation modules, and `git diff --check` passed. The two
scoped test files produced **28 passed, 4 skipped**. The four skipped PostgreSQL
cases remain gated by `PHASE2_G_POSTGRES_GO`; no migration or database operation
was run during this preparation. The shared Source model, ingestion, source
repository, and separate untracked pricing document were not edited by this slice.

Local GO receipt (2026-10-17):

- Confirmed explicit localhost:55432/research was at 0013, with no source identity,
  source relationship, or assessment tables before application.
- Cloned its schema (no research data) into disposable local database
  `source_relationship_test_26781176e79d`; applied only 0013 → 0014 and ran both
  scoped test files with `PHASE2_G_POSTGRES_GO=1`: **32 passed**. Fixture tenant
  count after rollback was zero. Removed the disposable database afterward.
- After the disposable checks passed, applied `alembic upgrade 0014` with explicit
  loopback admin/runtime URLs and bounded lock/statement timeouts, then reran the
  same suite against localhost:55432/research: **32 passed**.
- Verified revision is exactly 0014, both new tables have enabled/forced tenant
  RLS, and the 0015 assessment table is absent. Existing Source count remained
  11,804; both new tables have zero rows after fixture rollback. No backfill ran.
- Actual PostgreSQL checks exercised conflict replay, first-writer identity
  preservation, unchanged Source fields, restricted role grants, hidden tenant
  reads, rejected tenant writes, and cross-run/cross-tenant endpoint FK failures.
- No hosted changes, provider calls, push, or 0015 application. At this receipt's
  stage main owned the pending ingestion hook and separate assessment rollout.

Ingestion hook receipt (2026-10-17):

- `_persist_sources` uses the already locked ResearchRun row to gate on
  `mode is not None`. Null-mode legacy runs issue no relationship SQL; existing
  legacy transaction/statement-count tests pass unchanged.
- Only successfully inserted new source rows enter `observed_identities`. Mapping
  uses actual canonical, extraction, and discovery URLs. No page-body DOI,
  hostname, title, planner class, or unverified publisher is promoted into identity.
  The current Tavily boundary supplies no verified publisher metadata, so publisher
  remains unknown. Reused/cached Source rows receive no identity backfill.
- After source/event savepoints, `persist_source_relationships` runs once per
  nonempty explicit-mode metadata batch inside the existing outer tenant
  transaction and run lock. A relationship failure rolls back source, event,
  identity and relationship writes for that batch. Separately settled paid provider
  receipts/accounting stay consumed and are not refunded or redispatched.
- Combined source identity, relationship and ingestion persistence suites:
  **75 passed**, including focused/balanced/deep versus legacy, DOI observations,
  idempotent replay, no identity backfill, actual extraction success/failure and
  atomic rollback with preserved provider settlement. Ruff and strict scoped mypy
  passed. Rechecked localhost:55432/research remains at 0014 with both source tables'
  RLS enabled and forced. No additional migration or hosted operation was run.
- Builder remains owned by main. The separate pricing document was untouched.

Bootstrap isolation fix receipt (2026-10-17):

- Restricted 0001 create/drop scope to `tenants` plus its declared `TENANT_TABLES`.
  Future model registrations no longer cause early creation of tables whose RLS,
  grants or immutable-write triggers belong to a later revision. A dependency
  guard rejects core-model foreign keys to tables outside this scope before DDL.
  Runtime table grants use the same explicit allowlist, not all public tables.
- New unit and disposable PostgreSQL regressions cover committed fresh targets
  0001, 0014 and 0015, even with both future model families imported by env.py.
  Assessments are absent before 0015; afterward tenant isolation and assessment
  insertion/manifest/result guards reject unauthorized writes. Tests also cover
  source relationship/identity tenant writes and an unrelated pre-existing table
  that must not inherit runtime grants.
- Fresh 0001 → 0015 completed. Bootstrap, source identity/relationship and
  assessment suites: **54 passed**; scoped Ruff, formatting and mypy passed.
- An additional ingestion-inclusive run had **97 passed, 7 teardown errors**:
  the current 0013 immutable-budget DELETE guard rejects the ingestion fixture's
  cleanup of explicit-mode budgets. No test body failed. The 0013 migration and
  cleanup fixture were left unchanged for main to coordinate.
- Only 0001 changed among migrations. No env.py registration edits, shared local
  application-database migration, hosted changes or push. Disposable databases
  created for these checks were removed; no research data was copied into them.
