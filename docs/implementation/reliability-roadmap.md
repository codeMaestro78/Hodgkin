# Evidence reliability delivery

## Investigation and order

Next.js 16 / React 19 uses a verified Supabase SSR BFF. FastAPI, SQLAlchemy,
Alembic and PostgreSQL own tenant-scoped persistence. LangGraph currently runs
in an API-process background task; Tavily ingestion reserves calls before I/O.
The graph is intake → planner → concurrent collection → verifier → synthesizer.
Exact-span and semantic checks currently cover selected draft findings, not all
report prose. Existing Source, EvidenceClaim, Citation, ResearchGap,
SubQuestionAttempt, NodeExecution and Report models should be extended/reused.

1. Reliability: migration 0005 adds discovery provenance, report-scoped claims,
   gap details and parent-report links. Conservative URL normalization preserves
   content-bearing queries. Duplicate content is labelled correlated evidence,
   not counted as independent corroboration. Extract report assertions, verify
   exact passages and semantic support, retain rejected assertions for audit;
   publish only the evidence-gated findings. Expose unknown source metadata.
2. Visibility: persist real node and worker attempts and safe task events. Extend
   snapshots and existing SSE refreshes; offer graph plus accessible list.
3. Reports: filter claims, inspect quoted evidence, expose unresolved gaps,
   create a fresh idempotent linked follow-up with inherited depth budget.
   Preserve original reports. Markdown export and browser print/PDF retain links.
4. Validate: deterministic provider mocks, local disposable PostgreSQL/RLS,
   contract generation, frontend build and isolated browser fixture.

## Boundaries

Migration 0005 was applied to the configured Supabase database after explicit
user approval; the revision and forced tenant RLS on the affected tables were
verified. It was also exercised on local PostgreSQL. API-process work is not durable crash
recovery. Model extraction/review is not exhaustive factual certification, nor
does identical-content grouping establish independent publishers. Source
redirect/canonical metadata is used only when supplied by the provider; this
work does not add an arbitrary URL fetcher. No simulated graph activity.

Projects, bookmark collections, scheduled jobs, teams, public sharing and broad
cross-project memory remain later milestones; they must not outrun validated
core execution. Report revisions are immutable completed runs linked to the
exact parent report, not transient SSE updates.

## Implemented boundaries and operation

The published report is deliberately reconstructed from fully supported audited
assertions. Unchecked prose and contradicted assertions are not published as facts;
they remain inspectable. This does not yet preserve rich comparative tables from
the draft. A report with no supported assertions explicitly says so.

Collection has one bounded coverage-repair round. Automatic claim-gap replanning,
durable worker/checkpoint recovery, per-task retry, report diffs, decision-priority
comparisons, projects/bookmarks and configurable saved templates remain incomplete.
Redirect aliasing is not inferred when the provider supplies no verified mapping.

Model calls reserve a conservative token bound and a fixed $0.10 policy estimate
before dispatch, then reconcile tokens when usage is supplied. This is a safety
reservation, not verified provider pricing or a billing guarantee. Search/extract
budgets and Focused/Balanced/Deep source ceilings remain separate.

Run locally with `corepack pnpm dev` and, from `services/research-api`,
`uv run uvicorn research_api.main:app --reload` (check the service README for
environment prerequisites). Validate with `corepack pnpm test`,
`corepack pnpm typecheck`, `corepack pnpm --filter @research/web build`, and
`RUN_AUTH_SCHEMA_TESTS=1 uv run pytest tests/unit tests/integration -o addopts='' -q`
against disposable local PostgreSQL, never the hosted database.

## Validation recorded on 2026-10-13

- 121 backend unit/integration tests passed, including fresh auth-schema migration
  through 0005, local tenant isolation, exact-version follow-ups and idempotency.
- 24 frontend and 5 shared-contract tests passed; workspace typechecking passed.
- 34 generated JSON Schema documents validated; Python mirrors are regenerated.
- 44 isolated browser-fixture checks passed (29 workspace + 15 reliability),
  including independent scrolling, mobile/reduced-motion behavior, report version
  selection, source context, task-state SSE refresh and follow-up retry identity.
- Next.js production build and changed-module Ruff checks passed.

Provider/model boundaries in these tests are deterministic mocks. This is not a
signed-in live-provider end-to-end certification or durable restart recovery test.
