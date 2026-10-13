# Database (PostgreSQL)

PostgreSQL is the durable relational state store. See
[state-management.md](./state-management.md) for the schemas these tables
back, [redis.md](./redis.md) for what is deliberately *not* here, and
[artifact-storage.md](./artifact-storage.md) for what large content is
excluded from these tables.

ORM models are in `services/research-api/src/research_api/db/models.py`; Alembic migrations are in
`services/research-api/src/research_api/db/migrations/`. Migration `0001` creates the application
core, enables and forces RLS, and grants access to the non-owner `research_app` role.

## Tables

| Table | Backs | Notes |
|---|---|---|
| `tenants` | Multi-tenancy root | Every other table is scoped to a `tenant_id` |
| `users` | Session/auth | Scoped to `tenant_id` |
| `research_runs` | `ResearchState` (durable projection) | `status`, `budget`, `usage`, timestamps |
| `research_plans` | Versioned plan snapshots | One or more per run (initial + delta) |
| `sub_questions` | `SubQuestion` | FK to `research_runs` |
| `sub_question_attempts` | Retry/attempt history | FK to `sub_questions` |
| `sources` | `Source` | `artifact_ref` points to object storage, not inline content |
| `evidence_claims` | `EvidenceClaim` | FK to `sub_questions`; `support` classification |
| `citations` | `Citation` | FK to `evidence_claims`, `sources` |
| `contradictions` | Contradiction ledger entries | Links two or more `evidence_claims` |
| `gaps` | `ResearchGap` | FK to `research_runs` |
| `usage_ledger` | Per-tenant/run cost and call accounting | Feeds budget enforcement |
| `budgets` | `Budget` per run (or per tenant tier default) | See [reflection.md](./reflection.md#hard-limits) |
| `node_executions` | Node-level execution records | `run_id`, `node_id`, `attempt`, `output_hash` uniqueness (idempotency) |
| `run_events` | Append-only `AgentEvent` log | See [events-and-sse.md](./events-and-sse.md) |
| `reports` | Versioned final report content | Compare-and-swap on publish |
| `evaluations` | Benchmark/eval run results | See [evaluation.md](./evaluation.md) |

## Tenant isolation

Every table above carries `tenant_id`. Isolation is enforced at **two**
layers, not one:
1. **Repository/query layer** — every query is written with an explicit
   `tenant_id` predicate; there is no "trusted" code path that queries
   without it.
2. **Database layer** — row-level security policies (or an equivalent
   mandatory-scoping mechanism) provide a second, defense-in-depth
   boundary in case an application-layer check is missed.

Tenant-scoped foreign keys are composite (`tenant_id`, referenced ID), so a row cannot point at a
run, user, plan, source, claim, or reservation owned by another tenant even through an admin path.

See [security.md](./security.md#tenant-isolation) for the full policy.

## What belongs in PostgreSQL vs. object storage

| Belongs in PostgreSQL | Belongs in object storage |
|---|---|
| Run status, budget, usage counters | Raw HTML/PDF page bodies |
| `SubQuestion`, `EvidenceClaim`, `Citation` records (compact) | Full provider JSON payloads |
| `Source` metadata (title, URL, hash, `artifact_ref`) | The content the `artifact_ref` points to |
| Event log rows | — |
| Final report **metadata** and current version pointer | Large report exports (if offered), if not stored as text in `reports` |

Rule of thumb from the blueprint: **avoid storing enormous page bodies in
hot tables.** If a value is only ever read by ID for audit/citation
verification and is large, it belongs in object storage with a reference
here — see [artifact-storage.md](./artifact-storage.md).

## Checkpointer storage

The LangGraph checkpointer persists thread-scoped execution snapshots to
PostgreSQL (a dedicated checkpoint table/schema, separate from the
projection tables above). Long-term user preferences and reusable
research memory use normal application tables or a LangGraph `store` —
**keep these two concepts separate**; do not let checkpoint state become a
dumping ground for durable user data, and do not let application tables
depend on checkpoint internals.

## Indexing considerations (proposed)

- `research_runs(tenant_id, status, created_at)` — run listing/filtering.
- `run_events(run_id, sequence)` — ordered event replay.
- `sources(content_hash)` — deduplication lookups.
- `evidence_claims(sub_question_id)`, `citations(evidence_claim_id)` —
  ledger traversal.
- `node_executions(run_id, node_id, attempt)` unique index — idempotency
  enforcement (see [reliability.md](./reliability.md#idempotency)).

These indexes and uniqueness constraints are present in migration `0001`; future migrations must
preserve tenant-first access paths and RLS policies.
