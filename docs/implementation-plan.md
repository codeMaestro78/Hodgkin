# Multi-Agent Deep Research Assistant — Implementation Plan

> Research and repository inspection date: 2026-09-25. External versions, pricing, and limits below are point-in-time facts and must be rechecked by scheduled provider-contract tests.

## 1. Executive summary

This project builds a multi-tenant research operations console whose only lifecycle orchestrator is LangGraph and whose output is a citation-grounded report assembled from verified evidence. As of 2026-09-28, the repository baseline, schema 1.1 contract pipeline, tenant-safe PostgreSQL core, event outbox, artifact store, and Tavily Search/Extract ingestion boundary are implemented. The next slice connects these foundations to `intake`, `planner`, one `research_worker`, `distill_and_verify`, `writer`, `quality_gate`, and replayable SSE. It deliberately uses one provider family and no reflection, CrewAI, Parallel, or browser automation while preserving every invariant in [agent.md §2](./agent.md#2-architecture-invariants-non-negotiable).

The canonical contract will be authored in Zod 4, exported as Draft 2020-12 JSON Schema, generated into Pydantic v2 models, and protected by shared positive and negative fixtures. PostgreSQL application tables—not LangGraph checkpoints—will be business truth for runs, plans, evidence, budgets, and replay; checkpoints own only graph execution position and resumability. Provider calls will use transactional budget reservations so concurrent workers cannot overspend, and SSE reconciliation will use a projection watermark so reconnects cannot skip committed events. The three-month release is intentionally narrower than the full blueprint: Tavily, Serper, three parallel workers, one bounded reflection round, Jev routing, verified citations, replayable SSE, a 20-question evaluation, and one deployed demo. Parallel, browser automation, live CrewAI, the 60-question benchmark, and enterprise operations work remain post-launch roadmap items.

### 1.1 Three-month release boundary

**Must ship:** LangGraph parent graph; `planner`; three parallel `research_worker` executions; Tavily Search/Extract; Serper Search/News; artifact storage; context distillation; explicit exact-span and semantic verification; one bounded reflection round; PostgreSQL application state and usage reservations; LangGraph PostgreSQL checkpoints; transactional event outbox; watermark-based SSE replay; evidence/citation UI; Jev routing with deterministic fallback; a 20-question evaluation; and one production demo.

**Deferred until after launch:** Browserbase, authenticated browsing, public-page browser automation, Parallel Task/Task Group/FindAll, CrewAI in the live runtime, the 60-question benchmark, complex checkpoint pruning, full tenant-managed provider-key administration, Kubernetes, and a complete enterprise operations dashboard. CrewAI may exist as an isolated benchmark branch comparing a plain worker against a bounded role-based worker; it is not on the release critical path.

## 2. External Research Summary

| Area | Current facts that change or confirm the plan | Plan consequence |
|---|---|---|
| LangGraph | `StateGraph`, `Send`, `add_conditional_edges`, cycles, reducers, and checkpointers remain current. The retrieved package set was `langgraph` 1.2.12, `langgraph-checkpoint` 4.2.0, and `langgraph-checkpoint-postgres` 3.1.2. For new applications, current docs recommend typed-projection `stream_events`/`astream_events(..., version="v3")`; `astream(..., version="v2")` remains the lower-level stream-mode API. Neither is the durable public event log. ([Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming), [stream modes](https://docs.langchain.com/oss/python/langgraph/streaming), [Postgres saver](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/README.md)) | Keep the documented graph model; add an explicit `recursion_limit`, `AsyncPostgresSaver`, one-time checkpoint setup, strict MessagePack configuration, and an application-owned persisted `AgentEvent` outbox. Use v3 event streaming only as an internal observation source. |
| CrewAI | Current core types remain `Agent`, `Task`, `Crew`, and `Process`; role/goal/backstory and Pydantic task output are supported. Retrieved stable version was 1.15.22. Official LangChain guidance wraps a CrewAI kickoff as one LangGraph task. ([CrewAI agents](https://docs.crewai.com/v1.15.22/en/concepts/agents), [tasks](https://docs.crewai.com/v1.15.22/en/concepts/tasks), [LangGraph wrapper guidance](https://docs.langchain.com/langsmith/deploy-other-frameworks)) | Make CrewAI an optional post-MVP adapter with `allow_delegation=False`, `Process.sequential`, `memory=False`, `planning=False`, hard iteration/time bounds, native `akickoff()`, and exactly one routed provider tool. |
| Parallel | GA Search is `POST /v1/search`; Task is asynchronous under `/v1/tasks/runs`; Task Group batches known rows; FindAll discovers/evaluates entities and remains under `/v1beta/findall`. REST uses `x-api-key`, whereas MCP uses Bearer auth. Retrieved SDK package/version was `parallel-web` 1.3.3. ([Search](https://docs.parallel.ai/api-reference/search/search), [Task](https://docs.parallel.ai/api-reference/tasks/create-task-run), [Task Group](https://docs.parallel.ai/task-api/group-api), [FindAll](https://docs.parallel.ai/findall-api/findall-quickstart), [Task MCP](https://docs.parallel.ai/integrations/mcp/task-mcp)) | Use `AsyncParallel`; persist provider run IDs; poll status or consume provider events; fetch results only after terminal state. Keep Task Group and FindAll as separate routes. Parallel does not replace the dedicated browser adapter. |
| Tavily | Search, Extract, and asynchronous Research are separate surfaces. Basic Search now returns reranked chunks; Extract can query-rerank known URLs; Research requires create plus status polling or SSE. Retrieved packages were `tavily-python` 0.8.4 and `@tavily/core` 0.7.13. ([Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract), [Research](https://docs.tavily.com/documentation/api-reference/endpoint/research), [pricing](https://docs.tavily.com/documentation/api-credits)) | Use basic Search plus query-guided Extract for the first slice; do not request generated answers or full bodies by default. Treat Research as a higher-cost escalation and ledger returned usage. Post-filter domains even when restrictive provider filters are set. |
| Serper | Search and News remain `POST https://google.serper.dev/search` and `/news`, authenticated with `X-API-KEY`. Serper is live Google SERP retrieval, not a separate index; no first-party versioned SDK or provider idempotency guarantee was found. Published rate varies by paid plan and the 1–2 second latency claim is not an SLO. ([Serper](https://serper.dev/), [Haystack adapter](https://github.com/deepset-ai/haystack-core-integrations/blob/main/integrations/serperdev/src/haystack_integrations/components/websearch/serperdev/websearch.py)) | Implement a small tolerant HTTP adapter. Treat snippets as discovery only, parse displayed dates as untrusted labels, configure limits per plan, and assume an ambiguous-timeout retry may be billed again. |
| Type-Safe AI and runtime validation | Jev and `POST /v1/systemone` are current; Jev exposes `Choice`, ordered `Score`, and `Noul`. Python `typesafe-sdk` 0.7.1 is confirmed by both PyPI and the official changelog; JS `@typesafe-ai/sdk` was 0.6.0 at retrieval. Zod 4 can export JSON Schema; Pydantic v2 consumes/emits Draft 2020-12; `datamodel-code-generator` can generate Pydantic v2. ([TypeSafe API](https://docs.typesafe.ai/api), [PyPI](https://pypi.org/project/typesafe-sdk/), [Python changelog](https://docs.typesafe.ai/sdk/python/changelog), [primitives](https://docs.typesafe.ai/primitives), [Zod JSON Schema](https://zod.dev/json-schema), [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)) | Use Jev only for batched semantic judgments, with deterministic policy last. Use Zod-first JSON Schema generation **and** cross-runtime fixtures; choose exact pins only after a compatibility spike. |

## 3. Open decisions

Recommended defaults allow work to begin, but each item remains an explicit decision until its first owning PR records it.

### 3.1 Repository layout and toolchain

The scaffold has confirmed the following layout. Rows for graph, coordination, and optional adapters describe their reserved future locations.

| Concern | All documented unresolved path candidates | Recommended default |
|---|---|---|
| Frontend and research UI | `apps/web/`, `frontend/`, `apps/web/app/(research)/` | `apps/web/` and `apps/web/app/(research)/` |
| BFF routes | `apps/web/app/api/research/**/route.ts` | Keep this App Router layout; run SSE routes on Node, not Edge |
| Python service and entrypoint | `services/research-api/`, `python -m app.main` | `services/research-api/src/research_api/`; FastAPI/ASGI entrypoint decided in PR 1 |
| Graph and nodes | `services/research-api/graph/`, `graph/build_graph.py`, `graph/nodes/` | `services/research-api/src/research_api/graph/{builder.py,nodes/}` |
| Provider adapters | `services/research-api/providers/{serper,tavily,parallel,playwright,browserbase}.py` | `services/research-api/src/research_api/providers/`; one adapter per module |
| Optional CrewAI adapter | `services/research-api/providers/crew/` | `services/research-api/src/research_api/workers/crewai_adapter.py`; CrewAI is a worker implementation, not a provider, and remains an experimental branch |
| Zod contracts | `packages/contracts/` | `packages/contracts/src/`; Zod 4 is the authoring source |
| Pydantic models | `services/research-api/schemas/` | generated into `.../schemas/generated/`; hand-written semantic validators live beside, not inside, generated files |
| Database/migrations/models | `services/research-api/db/{migrations,models}/` | SQLAlchemy 2 + Alembic under `.../db/`; record this choice before generating migrations |
| Redis coordination | `services/research-api/coordination/` | `.../coordination/`; optional until multi-instance coordination is needed |
| Event log/outbox | `services/research-api/events/` | `.../events/` with outbox repository and publisher |
| Tests | `services/research-api/tests/`, `apps/web/tests/`, `packages/contracts/tests/` | Keep all three, plus top-level provider-contract/eval workflows |
| Configuration | `.env.example`, `services/research-api/config.py`, `apps/web/.env.example` | root non-secret examples plus typed settings in each service |
| Deployment | `infra/`, Dockerfiles, compose path | `infra/` plus root `compose.yaml`; no Kubernetes in MVP |

Confirmed toolchain: pnpm 10.18.3 workspaces with Node 24.15.0; Python 3.12 with `uv`; Ruff, mypy, pytest, and Vitest. Exact dependency versions and lockfiles are committed. Playwright remains a later-phase dependency.

### 3.2 Contracts, persistence, and platform

| Open item from `PROPOSED`/`PLANNED` markers | Recommended default |
|---|---|
| Zod/Pydantic synchronization | Zod 4 → checked-in Draft 2020-12 JSON Schema → generated Pydantic v2, plus shared valid/invalid fixtures and normalized-schema comparison |
| Database tables and indexes | Start with the full table list in [database.md §Tables](./database.md#tables-proposed-derived-from-the-blueprints-persistence-list); implement only tables needed by each phase, always with `tenant_id` and RLS |
| LangGraph interrupt call sites | Only before explicitly authorized authenticated/side-effecting browser actions; never inside CrewAI tools |
| Object-store backend and key scheme | LocalStack S3 for development; S3-compatible interface in production; opaque content-hash-derived keys |
| Artifact retention | Default 30 days for raw artifacts, but completed-report evidence remains until report retention expires; make both tenant-configurable before production |
| Service-to-service authentication | Short-lived signed internal JWT with audience and tenant/user delegation claims; mTLS can be added by the deployment platform |
| Session/auth provider | Choose during frontend scaffold; HTTP-only same-origin cookie is required by native `EventSource` |
| Secret manager | Deployment-platform managed secret store; never `.env` in production |
| SSE heartbeat | 20 seconds, configurable; verify against the selected hosting proxy |
| Target infrastructure/SSE hosting | Containerized long-running Python service and an SSE-capable Node deployment; do not assume generic serverless duration support |
| Health checks | Separate liveness from readiness; readiness checks Postgres and object storage, while Redis degradation must not corrupt correctness |
| Dashboard/tracing stack | OpenTelemetry first; select collector/backend only after deployment target is chosen |
| CI provider and schedules | Every PR: static/unit/schema/node/reducer/graph/integration/SSE/security; scheduled, initially non-blocking: live provider contracts and 20-question eval; 60-question benchmark is post-launch |
| Checkpoint retention | Define after recovery tests; do not delete Postgres checkpoint ancestors blindly because safe pruning remains unresolved upstream ([issue](https://github.com/langchain-ai/langgraph/issues/8531)) |

#### 3.2.1 Authoritative ownership model

| Data | Authoritative system | Derived/cached representations |
|---|---|---|
| Graph execution position, interrupt, and resumability | LangGraph PostgreSQL checkpoint | `node_executions` audit rows |
| Run status and user-facing projection | Application PostgreSQL tables | LangGraph state fields and frontend reducer |
| Plans and plan history | Application PostgreSQL `research_plans` with immutable `planVersion` | Compact active plan IDs in `ResearchState` |
| Sources, claims, citations, contradictions, and gaps | Application PostgreSQL tables | Compact IDs in `ResearchState`; UI projection |
| Raw/normalized documents | Object storage addressed by `evidenceArtifactHash` | `Source.artifactRef` and verified offsets |
| Budgets, reservations, and usage | Application PostgreSQL usage/reservation ledger | Read-only budget snapshot in graph state |
| Events and replay | PostgreSQL `run_events`/transactional outbox with unique `(run_id,event_sequence)` | Redis live notification and frontend state |
| Locks, rate limits, and semaphores | Redis, with safe expiry | Never authoritative for spend or run state |
| User interface state | Reconstructed from a watermarked durable projection plus ordered events | Browser memory only |

The LangGraph checkpoint is not the business database. Application-row writes and checkpoint writes may not share one database transaction or commit boundary. Execution is therefore **at least once with idempotent effects**, not exactly once: every node must safely replay, application writes use stable idempotency keys/unique constraints, and recovery reconciles the checkpoint with authoritative application rows before new external work is dispatched.

#### 3.2.2 Atomic budget reservation

Checking a counter before a provider call is insufficient under parallel fan-out. Add a `provider_call_reservations` ledger with stable `reservationId`, request fingerprint, provider operation, reserved search-call units, reserved estimated cost, timestamps, attempt, and state:

```text
available -> reserved -> consumed
                      -> released
                      -> uncertain
```

Before an external provider/model call, the adapter service must atomically lock the run-usage row (`SELECT ... FOR UPDATE`) or use an equivalent conditional `UPDATE`; verify remaining hard limits; insert the reservation; increment reserved usage; and commit. Only then may it call the provider. A definite pre-dispatch failure releases the reservation; a successful response consumes it; an ambiguous timeout becomes `uncertain` until reconciled and continues to count against the budget. Redis semaphores cap concurrency but never authorize spend. Retries reuse the completed result or the same reservation/fingerprint when safe; they do not create an unaccounted second call.

#### 3.2.3 Race-free SSE reconciliation

`GET /api/research/runs/:runId` must return `{ run, snapshotSequence }` from one consistent database snapshot. The client then opens `GET /api/research/runs/:runId/events?after=<snapshotSequence>`; the server first replays every committed event with a greater sequence and then tails live notifications. The client deduplicates by `eventId`, applies only contiguous `eventSequence` values, refetches the projection on a gap, and reconnects from its last applied sequence. `Last-Event-ID` may encode the same sequence for native `EventSource`, but the numeric sequence—not timestamp or arrival order—is authoritative.

#### 3.2.4 Canonical contract corrections

PR 2 must make these decisions concrete rather than leaving alternatives:

- `ResearchRunProjectionSchema` keeps the existing lifecycle enum and adds `cancellationRequestedAt: datetime | null`, `cancelledAt: datetime | null`, `reportId: uuid | null`, and `snapshotSequence: nonnegative integer`.
- `CitationVerificationSchema.exactSpan` records `verified`, `evidenceArtifactHash`, and nullable character offsets. `semanticSupport` records `supports | partially_supports | contradicts | unrelated`, confidence, `verifierModel`, and `verifierVersion`; the outer object records `verifiedAt`.
- `EvidenceClaimSchema` adds immutable generation provenance: `model`, `modelVersion`, `promptVersion`, and distiller/verifier version identifiers. A claim may be writer-eligible only when exact-span verification passes and semantic verdict is `supports` (or an explicitly allowed caveated partial-support policy).
- `ResearchPlanSchema` adds monotonically increasing `planVersion`; delta plans append a new version and never mutate the original plan silently.
- `ProviderCallSchema` records request and response schema versions, request fingerprint, provider operation, reservation ID, provider request/run ID when available, and terminal outcome including `uncertain`.
- `AgentEventSchema` adds `eventSequence`, backed by unique `(run_id,event_sequence)` and unique `eventId` constraints.
- `ResearchStateSchema` stays compact: it carries stable IDs, counters, active `planVersion`, and bounded routing/reflection decisions—not complete `Source`, `EvidenceClaim`, raw page, or provider response collections.

### 3.3 Configuration catalog

All non-budget configuration rows in [configuration.md](./configuration.md) are proposed. PR 1 must confirm names, types, defaults, and ranges for: `APP_ENV`, `NEXT_PUBLIC_APP_URL`, `DATABASE_URL`, `DATABASE_POOL_SIZE`, `REDIS_URL`, `LANGGRAPH_CHECKPOINTER`, `WORKER_CONCURRENCY_LIMIT`, every `PROVIDER_GLOBAL_CONCURRENCY_<PROVIDER>`, `LLM_PROVIDER`, `LLM_MODEL_NAME`, `SERPER_API_KEY`, `TAVILY_API_KEY`, `PARALLEL_API_KEY`, the corrected `TYPESAFE_API_KEY` name with a documented compatibility alias if needed, `BROWSERBASE_API_KEY`, `BROWSER_ALLOWED_PROTOCOLS`, `BROWSER_BLOCK_PRIVATE_IPS`, `BROWSER_SESSION_TIMEOUT_MS`, `SSE_HEARTBEAT_INTERVAL_MS`, `SESSION_SECRET`, `INTERNAL_SERVICE_AUTH`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_CREDENTIALS`, `ARTIFACT_RETENTION_DAYS`, `OTEL_EXPORTER_ENDPOINT`, `EVAL_BENCHMARK_PATH`, and `EVAL_SCHEDULE_CRON`.

Budget fields from `BudgetSchema` remain canonical, but defaults still need product approval for `maxWallClockMs`, `maxInputTokens`, `maxOutputTokens`, and `maxEstimatedCostUsd`. Preserve the schema ceilings and full-blueprint limits in [reflection.md §Hard limits](./reflection.md#hard-limits), but set narrower provisional MVP defaults: `maxSearchCalls=12`, `maxBrowserSessions=0`, `maxReflectionRounds=1`, three concurrent workers, initial/delta sub-question caps 8/4, and `maxSourcesPerSubQuestion=6`. Any change to those release defaults requires a documented architecture decision and benchmark comparison. Store `concurrencyLimit` outside `BudgetSchema` as a run execution setting and add it to the canonical state/dispatch contract.

### 3.4 Provider and product choices

| Decision | Recommended default |
|---|---|
| First provider | Tavily basic Search + query-guided Extract; `include_answer=false`, `include_raw_content=false`, strict hostname post-filter |
| First LLM provider/model | One structured-output-capable provider, injected behind an application interface; decide by evaluation rather than hard-coding the architecture |
| Jev | Enable only after deterministic routing baseline; validate `typesafe-sdk==0.7.1` in a compatibility spike before pinning; fall back deterministically on timeout/low certainty |
| Serper | Add in phase 3 for fast discovery/news; treat all fields as tolerant/optional and snippets as non-evidence |
| Parallel | Post-launch; Search, Task, Task Group, and FindAll remain distinct adapter operations |
| Browser | Post-launch; first support only unauthenticated public pages in a separate sandboxed worker. Authenticated browsing and Browserbase are deferred further |
| CrewAI | Excluded from the live MVP; evaluate one bounded worker against the plain LangGraph worker only in an experimental branch |

## 4. Documentation Gaps and Reconciliation

The repository dimension is greenfield. There are no implementation claims that can be “Confirmed” or “Contradicted by repo”; the documentation itself is present, but every described service/component is **Not yet built**. Before this plan was added, the live checkout contained 29 Markdown source documents under `docs/`: the 28-file documentation set plus `Multi_Agent_Deep_Research_Technical_Blueprint.md`. It also contains duplicate root `README.md` and `agent.md`. With this plan, `docs/` now contains 30 Markdown files. These counts were rechecked in the current workspace and are not inferred from the attachment review.

| Bucket | Doc claim | Reality | Resolution and doc to update |
|---|---|---|---|
| Not yet built | All application paths, manifests, commands, tests, CI, migrations, and IaC are described as proposed | Repository contains only docs plus duplicate root `README.md`/`agent.md`; no manifests or source exist | Adopt §3.1 in scaffold PR; update [agent.md](./agent.md), [development.md](./development.md), [testing.md](./testing.md), and [deployment.md](./deployment.md) |
| Internal contradiction | `ResearchStateSchema` is camelCase, while LangGraph pseudocode reads snake_case keys and also reads `concurrency_limit` and `reflection_decision`, which the schema lacks | The graph cannot type-check against the canonical contract as written | Use canonical camelCase JSON contracts and a deliberate Python alias policy; add `concurrencyLimit` and either a transient typed graph channel for `ReflectionDecision` or a documented persisted field. Update [state-management.md](./state-management.md) and [langgraph.md](./langgraph.md) |
| Internal contradiction | Cancel response uses status `"cancelling"` | `RunStatusSchema` has no `cancelling` member | Keep lifecycle status unchanged until a safe boundary; add nullable `cancellationRequestedAt` and `cancelledAt`, then transition to `cancelled`. Update [state-management.md](./state-management.md), [api.md](./api.md), and lifecycle diagrams |
| Internal contradiction | `run.completed.reportUrl` is `z.string().url()` | API example emits relative `/api/research/.../report` | Persist and emit `reportId: uuid`; derive URLs at the API/UI boundary so route changes do not migrate data. Update [state-management.md](./state-management.md), [api.md](./api.md), and [events-and-sse.md](./events-and-sse.md) |
| Internal contradiction | A citation has one `verificationMethod`, while the constitution says exact-span **and** semantic checks must pass | One enum value cannot record two distinct checks | Add `CitationVerificationSchema` with explicit `exactSpan` artifact hash/offset result, `semanticSupport` verdict/confidence/model/version, and `verifiedAt`. Update [state-management.md](./state-management.md), [citation-verification.md](./citation-verification.md), and [agent.md](./agent.md) |
| Internal ambiguity | `distill_and_verify` follows each worker, then routes directly to `reflector` | The sketch does not show a true all-workers fan-in barrier and could reflect once per branch | Add typed branch result/reducer channels and an explicit fan-in/join node or documented LangGraph barrier pattern. Update [langgraph.md](./langgraph.md) |
| Internal contradiction | [agent.md §8](./agent.md#8-provider-rules) says “two `Noul` questions” | The routing table lists three: news, multi-hop, and browser-rendering | Change “two” to “three” |
| Internal gap | `WorkerResult` is prose-only and not among canonical schemas | Every node boundary must be Zod/Pydantic validated | Add `WorkerResultSchema`, `ReflectionDecisionSchema`, request/response schemas, and provider-normalization schemas to [state-management.md](./state-management.md) |
| Contradicted by external reality | Tavily table omits Extract; advanced is described as the token-dense route | Extract is current; basic Search also returns reranked chunks; Research is async create/poll/SSE | Add `/extract`, Research status, depth/cost semantics, strict-date/domain caveats, and package pin to [provider-routing.md](./provider-routing.md) |
| Contradicted by external reality | Parallel REST paths are left implicit; Task Group/FindAll are grouped | Search is GA `/v1/search`; Task/Group are `/v1/tasks/...`; FindAll remains `/v1beta` and is a different workflow | Split operations/auth/paths in [provider-routing.md](./provider-routing.md); pin `parallel-web` and contract-test |
| Contradicted by external reality | Request fingerprints guarantee “no duplicate billed calls on retry” | No Serper provider idempotency was found; ambiguous retries can bill twice | Reword as application dedupe/cache only and record uncertain outcomes for reconciliation. Update [provider-routing.md](./provider-routing.md) and [reliability.md](./reliability.md) |
| External clarification | Serper is described as “real-time Google SERP indexing” | Serper says it queries Google live; it does not own the index or publish a freshness SLA | Say “live Google SERP retrieval”; make QPS plan-aware. Update [provider-routing.md](./provider-routing.md) |
| External clarification | CrewAI bounded-worker idea is correct but settings are unspecified | Defaults include `max_iter=20`, retries, and potentially no time limit; delegation adds tools | Document explicit bounded adapter settings in [research-workers.md](./research-workers.md) and [agents.md](./agents.md) |
| External clarification | LangGraph streaming/checkpointing is described generically | Current async production pattern uses `AsyncPostgresSaver`; new applications are directed to v3 event streaming/typed projections; v2 stream modes remain lower level; checkpoint pruning has limitations | Add compatibility-tested pins, setup/security/retention, v3 internal observation, and `recursion_limit` to [langgraph.md](./langgraph.md), [database.md](./database.md), and [deployment.md](./deployment.md). ([event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)) |
| External clarification | “Low-confidence Jev output” is generic | `Choice`/`Score` have confidence; `Noul` has only a yes probability | Document calibrated probability bands for Noul and ordered Score criteria in [provider-routing.md](./provider-routing.md) |
| External clarification | Zod/Pydantic may be generated **or** contract-tested | Generation alone and tests alone each leave drift risks | Require generation **and** shared-fixture/schema-comparison tests in [state-management.md](./state-management.md) and [testing.md](./testing.md) |
| Confirmed externally | The Next.js BFF example awaits `params` and returns a Web `Response` stream | Current Route Handlers still use Web Request/Response APIs, support streaming, and expose dynamic `params` as a promise | Keep the route shape; pin the actual Next.js version during scaffold and test SSE on the deployment adapter. Update the unverified version in [frontend.md](./frontend.md). ([Next.js Route Handlers](https://nextjs.org/docs/app/api-reference/file-conventions/route)) |
| External security gap | Browser downloads are “blocked by default” | Playwright browser contexts currently default `acceptDownloads` to `true`; contexts isolate cookies/cache, but request interception can miss Service Worker traffic unless Service Workers are blocked | Set `acceptDownloads=false`, `serviceWorkers="block"`, intercept every request, re-resolve DNS/IP at navigation time, and close each context. Update [prompt-injection.md](./prompt-injection.md) and [security.md](./security.md). ([Playwright Browser](https://playwright.dev/docs/api/class-browser), [network routing](https://playwright.dev/docs/network), [context isolation](https://playwright.dev/docs/browser-contexts)) |
| External security gap | Database RLS is described as a second tenant boundary | PostgreSQL table owners and `BYPASSRLS` roles normally bypass policies; enabling RLS with no policy is default-deny only for normal access | Run the application as a non-owner/no-`BYPASSRLS` role, apply `FORCE ROW LEVEL SECURITY` where appropriate, and test owner/admin paths separately. Update [database.md](./database.md) and [security.md](./security.md). ([PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)) |
| Confirmed externally | Redis is delivery/coordination, never the only event log | Redis Pub/Sub is at-most-once and permanently loses messages missed during disconnect | Keep PostgreSQL outbox/replay authoritative; Redis may only wake live publishers/subscribers. Update [redis.md](./redis.md) with the explicit delivery guarantee. ([Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/)) |
| External clarification | Browserbase is a hosted browser fallback with isolated per-run sessions | Current SDK creates a session and connects Playwright over CDP; session metadata can carry a run ID, but recording/metadata create additional retained tenant data | Tag every session with tenant-safe opaque run metadata, audit creation/closure, and decide replay retention before enabling authenticated browsing. Update [security.md](./security.md) and [artifact-storage.md](./artifact-storage.md). ([Browserbase retrieval](https://docs.browserbase.com/use-cases/web-data-retrieval), [session metadata](https://docs.browserbase.com/platform/browser/core-features/session-metadata)) |

## 5. Build sequence

### Phase 0 — Resolve contracts and scaffold the repository

**Goal:** Create a reproducible monorepo and make every cross-language/runtime contract executable before graph behavior is added.

**Implements:** [state-management.md](./state-management.md), [configuration.md](./configuration.md), [development.md](./development.md), [security.md](./security.md), [testing.md](./testing.md), and repository-navigation rules in [agent.md §3](./agent.md#3-repository-navigation).

**Deliverables:** `RunStatusSchema`, `ProviderSchema`, `BudgetSchema`, `SourceSchema`, `CitationSchema`, `CitationVerificationSchema`, `EvidenceClaimSchema`, `SubQuestionSchema`, `ResearchGapSchema`, `ResearchStateSchema`, `AgentEventSchema`, `ReflectionDecisionSchema`, `WorkerResultSchema`, `ResearchPlanSchema`, `ProviderCallSchema`, and `ResearchRunProjectionSchema`; generated Pydantic v2 mirrors; shared fixtures; monorepo manifests/lockfiles; typed settings; local PostgreSQL/Redis/LocalStack S3; CI.

**Dependencies:** None.

**Exit criteria:** Cross-runtime fixtures accept/reject identically; generated files have no diff; every contract has `schemaVersion`; tenant identifiers cannot be omitted from durable write DTOs; secrets are absent from committed files; scaffold build, lint, type-check, and tests pass (per [agent.md §15](./agent.md#15-definition-of-done)).

### Phase 1 — Thin evidence-safe vertical slice

**Goal:** Deliver one end-to-end run with one worker and Tavily Search/Extract, including minimal evidence verification, durable events, and basic UI.

**Implements:** [research-workflow.md](./research-workflow.md), [agents.md](./agents.md), [evidence-system.md](./evidence-system.md), [citation-verification.md](./citation-verification.md), [api.md](./api.md), [events-and-sse.md](./events-and-sse.md), [frontend.md](./frontend.md), and [artifact-storage.md](./artifact-storage.md).

**Deliverables:** `intake`, `planner` (one `SubQuestion` in slice mode), `provider_router` (deterministic Tavily only), `research_worker`, `distill_and_verify`, `writer`, and `quality_gate`; Tavily adapter; artifact repository; minimal `research_runs`, `research_plans`, `sub_questions`, `sources`, `evidence_claims`, `citations`, `provider_calls`, `provider_call_reservations`, `usage_ledger`, `node_executions`, `run_events`, and `reports`; `POST /api/research/runs`, watermarked run projection, ordered events, and report endpoints; `QuestionComposer`, `RunStatus`, `StreamingMarkdown`, `InlineCitation`, and minimal `LiveEventConsole`.

**Dependencies:** Phase 0.

**Exit criteria:** A real local run produces a report only from eligible verified claims; exact spans resolve against the recorded `evidenceArtifactHash`; invalid claim IDs fail `quality_gate`; events are committed before publication and replay from `snapshotSequence`; cross-tenant reads fail; provider/LLM failures are typed; every external call holds a committed budget reservation and ends `consumed`, `released`, or `uncertain`.

### Phase 2 — Durable graph execution and replay

**Goal:** Make the slice resumable, idempotent, and correct across crashes and reconnects.

**Implements:** [langgraph.md](./langgraph.md), [database.md](./database.md), [events-and-sse.md](./events-and-sse.md), [reliability.md](./reliability.md), and [observability.md](./observability.md).

**Deliverables:** compiled `StateGraph`; `AsyncPostgresSaver`; explicit `thread_id=runId`; `recursion_limit`; v3 `stream_events`/`astream_events` internal observer; idempotent node writes; checkpoint/application-row reconciliation; transactional outbox/publisher; unique monotonic run-local sequence; watermarked SSE handoff; orthogonal cancellation request timestamps; checkpoint recovery.

**Dependencies:** Phase 1 contracts and persistence.

**Exit criteria:** Injected worker-process death resumes with at-least-once execution but zero duplicate effects for known completed requests; every replay path is idempotent; a forced projection/SSE handoff race yields a complete ordered reducer state under at-least-once delivery and dedupe; cancellation is idempotent and auditable; checkpoint/projection drift is detected and reconciled; no raw state or private channel is streamed to the browser.

### Phase 3 — Parallel fan-out and MVP provider routing

**Goal:** Expand to exactly three concurrent MVP workers using true graph fan-out/fan-in and deterministic Serper/Tavily routing.

**Implements:** [langgraph.md §Send](./langgraph.md#send--fan-out-fan-in), [provider-routing.md](./provider-routing.md), [research-workers.md](./research-workers.md), [reliability.md](./reliability.md), and reducers in [state-management.md](./state-management.md#reducers).

**Deliverables:** `dispatch_workers`; stable-ID reducers; explicit join before `distill_and_verify`/`reflector`; Serper Search/News adapter; versioned provider request/response ledger; atomic reservation transitions; per-run and per-provider semaphores; circuit breakers; source canonicalization/deduplication; provider routing telemetry.

**Dependencies:** Durable checkpoint/replay from Phase 2.

**Exit criteria:** Reducers pass duplicate/out-of-order/conflict/partial tests; one worker failure does not cancel siblings; no route calls every provider; Serper snippets never become `Citation` evidence; concurrent reservation tests prove the 12-call/cost limits cannot be oversubscribed; partial results become visible gaps.

### Phase 4 — Bounded reflection, contradictions, and complete evidence UI

**Goal:** Add `reflector` and `planner_delta` without permitting unbounded work, while exposing uncertainty and disagreement.

**Implements:** [reflection.md](./reflection.md), [evidence-system.md](./evidence-system.md), [citation-verification.md](./citation-verification.md), [ui-ux.md](./ui-ux.md), and relevant [agents.md](./agents.md) contracts.

**Deliverables:** `ReflectionDecisionSchema`; `reflector`; `route_after_reflection`; `planner_delta`; contradiction and gap tables; `EvidenceLedger`, `SourceExplorer`, `GapAndConflictPanel`, and `EvidencePopover`; report incompleteness rendering.

**Dependencies:** Phase 3 fan-in and provider telemetry.

**Exit criteria:** Every continuation is rejected at any exhausted hard limit; repeated normalized queries are blocked; the MVP maximum of one reflection round and four delta questions is enforced in code; each delta creates a new `planVersion`; conflicting evidence is preserved and rendered; incomplete research is acknowledged in the report.

### Phase 5 — Jev differentiation, evaluation, and production demo

**Goal:** Add one measured differentiator, prove the release targets, and deploy the bounded MVP.

**Implements:** [provider-routing.md](./provider-routing.md), [evaluation.md](./evaluation.md), [observability.md](./observability.md), [security.md](./security.md), [testing.md](./testing.md), and [deployment.md](./deployment.md).

**Deliverables:** Jev batched routing with deterministic fallback; deterministic-versus-Jev routing ablation; 20-question evaluation dataset/dashboard; load, crash, reconnect, cancellation, reservation, and tenant-isolation tests; essential OpenTelemetry; polished core `ResearchWorkspace`; deployment/rollback/runbook; production demo.

**Dependencies:** Stable evidence pipeline, reservation ledger, replay, fan-out, and one-round reflection.

**Exit criteria:** Jev failure/uncertainty falls back deterministically; every provisional quality/latency/recovery target in §9.1 is measured without silent threshold changes; cross-tenant and prompt-injection suites pass; SSE load/reconnect is proven on the actual deployment; rollback is rehearsed; the public demo completes the 20-question release gate.

### Phase 6 — Post-launch roadmap

**Goal:** Add advanced capabilities individually, only when benchmark evidence justifies their complexity and cost.

**Implements:** [frontend.md](./frontend.md), [ui-ux.md](./ui-ux.md), [observability.md](./observability.md), [security.md](./security.md), [testing.md](./testing.md), [evaluation.md](./evaluation.md), and [deployment.md](./deployment.md).

**Deliverables:** Separate roadmap increments for Parallel Search/Task, Task Group, FindAll, sandboxed unauthenticated public-page browser automation, Browserbase/authenticated browsing, experimental CrewAI worker ablation, 60-question benchmark, tenant-managed provider credentials, checkpoint retention automation, and expanded operations UI.

**Dependencies:** A successful Phase 5 launch plus an approved architecture decision and benchmark hypothesis for each increment.

**Exit criteria:** Each increment independently satisfies the full Definition of Done and improves a predeclared benchmark or product requirement; no bundle of optional frameworks is accepted merely to claim breadth.

### 5.1 Twelve-week execution map

| Weeks | Release deliverable |
|---|---|
| 1–2 | Monorepo, corrected/generated contracts, PostgreSQL ownership model, RLS/auth boundary, basic UI shell |
| 3–4 | Tavily research slice, artifact storage, claims, explicit citation verification, report and basic SSE |
| 5 | LangGraph checkpoints, at-least-once/idempotent nodes, outbox, watermark replay, orthogonal cancellation |
| 6–7 | Three parallel workers, stable-ID reducers, explicit fan-in, Serper routing, atomic budget reservations |
| 8 | One bounded reflection round, immutable `planVersion`, gaps and contradictions |
| 9 | Jev routing with deterministic fallback and routing ablation |
| 10 | Twenty-question evaluation and citation/latency metrics |
| 11 | Load, crash, replay-race, budget-race, cancellation, and tenant-isolation testing |
| 12 | Core UI polish, production deployment, rollback drill, documentation, and launch demo/video |

## 6. Task breakdown per phase

Each checkbox is intended to be one reviewable PR/change.

### Phase 0 tasks

- [ ] Scaffold pnpm/Python workspaces, lockfiles, local containers, and CI; touches development and test commands only.
- [ ] Resolve cancellation timestamps, `reportId`, `CitationVerificationSchema`, `WorkerResultSchema`, compact dispatch/reflection fields, `planVersion`, provenance, and event sequence; bump `schemaVersion` and update all fixtures.
- [ ] Implement Zod 4 → JSON Schema → Pydantic generation with a clean-diff CI gate; touches every schema.
- [ ] Add shared valid/invalid fixtures plus normalized emitted-schema comparison; touches Zod/Pydantic contract tests.
- [ ] Add typed settings and `.env.example` files with secret-redaction tests; touches configuration contracts.
- [ ] Create tenant/user/run/plan/event migrations with application-owned projections, non-owner/no-`BYPASSRLS` role, forced RLS where appropriate, and repository scoping tests.

### Phase 1 tasks

- [x] Implement artifact interface, content hashing, canonical URL normalization, and S3-compatible adapter; touches `SourceSchema.artifactRef/contentHash` and unit/integration tests.
- [ ] Implement Tavily Search normalization using basic chunks, no generated answer, and explicit usage capture; touches provider fixtures and `SourceSchema`.
- [ ] Implement query-guided Tavily Extract with partial-result handling and hostname post-filter; touches provider fixtures and failure tests.
- [ ] Implement `intake`, MVP defaults, usage ledger, and atomic budget reservation service; touches `BudgetSchema`, `ProviderCallSchema`, reservation state transitions, and concurrent oversubscription tests.
- [ ] Implement structured `planner` with one retry on invalid output; touches `SubQuestionSchema` and node tests.
- [ ] Implement `provider_router` and one `research_worker` returning `WorkerResultSchema`; touches route/worker node tests.
- [ ] Implement source normalizer, candidate distiller with model/prompt provenance, exact-span verifier bound to `evidenceArtifactHash`, and versioned semantic support check; touches `SourceSchema`, `EvidenceClaimSchema`, `CitationSchema`, and `CitationVerificationSchema`.
- [ ] Implement `writer` using verified claim IDs only and deterministic citation rendering; touches report contract and writer tests.
- [ ] Implement `quality_gate` and compare-and-swap report publication; touches citation/report failure tests.
- [ ] Add transactional run events, unique `(run_id,event_sequence)`, and BFF create/watermarked-projection/events/report routes; touches `AgentEventSchema` and SSE tests.
- [ ] Build the minimal composer/status/report/citation UI and contiguous-sequence reconnect reducer; touches API/event consumer tests.

### Phase 2 tasks

- [ ] Build and compile `StateGraph` with `AsyncPostgresSaver`, one-time setup migration, strict serialization allowlist, and `recursion_limit`; touches graph tests.
- [ ] Add `(run_id,node_id,attempt,output_hash)` persistence and idempotent node wrapper; touches failure/replay tests.
- [ ] Add a v3 event-stream observer that projects only validated domain events into the outbox; never expose raw runtime streams.
- [ ] Add outbox publisher, monotonic sequence, heartbeat, `snapshotSequence`, and `after`/`Last-Event-ID` mapping; touches event/SSE race tests.
- [ ] Implement watermarked frontend reconciliation, contiguous gap detection, dedupe/upsert, projection refetch, and reconnect; touches reducer tests.
- [ ] Implement `cancellationRequestedAt`/`cancelledAt` and safe-boundary transition; touches API, state, graph, crash recovery, and idempotent cancellation tests.
- [ ] Add crash/restart and checkpoint/application-row reconciliation harness; defer automated checkpoint pruning until post-launch.

### Phase 3 tasks

- [ ] Implement stable-ID reducers for `subQuestions`, `sourceIds`, `evidenceClaimIds`, and `gaps`; touches reducer property tests.
- [ ] Implement `Send`-based `dispatch_workers` and an explicit all-branches join; touches graph routing/fan-in tests.
- [ ] Add Redis-backed per-run/provider semaphores with Postgres-authoritative atomic reservations; touches oversubscription, load, uncertain-timeout, and Redis-degradation tests.
- [ ] Implement Serper Search/News tolerant adapters and discovery-only normalization; touches provider contracts and citation-negative tests.
- [ ] Implement deterministic routing table, fallback policy, and plan-aware limits; touches router/node/graph tests.
- [ ] Add versioned provider request/response ledger with reservation ID and `pending/succeeded/failed/uncertain`; touches duplicate-cost, replay, and timeout tests.
- [ ] Add adapter circuit breakers and typed escalation; touches failure injection.

### Phase 4 tasks

- [ ] Implement contradiction grouping and `ResearchGapSchema` persistence; touches ledger tests.
- [ ] Implement structured `reflector` and calibrated coverage/marginal-gain evaluation; touches `ReflectionDecisionSchema`.
- [ ] Implement `route_after_reflection` with every deterministic hard stop checked first; touches graph boundary tests.
- [ ] Implement one-round `planner_delta`, immutable `planVersion`, and duplicate-query rejection; touches `ResearchPlanSchema`, `SubQuestionSchema`, and graph tests.
- [ ] Add gap/conflict/source/evidence UI components and citation comparisons; touches event/projection UI tests.
- [ ] Add incomplete-report contract and quality-gate checks; touches report tests.

### Phase 5 tasks

- [ ] Add batched Jev judgments and deterministic composition/fallback; touches routing eval and TypeSafe fixture tests.
- [ ] Run deterministic-versus-Jev routing ablation and publish accuracy, latency, and cost results.
- [ ] Build the 20-question evaluation dataset/dashboard and lock provisional release targets before the first full run.
- [ ] Complete core `ResearchWorkspace`, budgets, cancellation, evidence/gap UI, responsive modes, and accessibility tests.
- [ ] Instrument nodes/providers/outbox with essential OpenTelemetry and tenant-safe redaction.
- [ ] Run load, crash, reconnect-race, reservation-race, failure-injection, and tenant-isolation suites.
- [ ] Produce deployment/rollback/runbook artifacts, execute a staging recovery drill, and publish the demo.

### Phase 6 tasks

- [ ] Evaluate and, if justified, add Parallel Search/Task; keep Task Group and FindAll as separate later decisions.
- [ ] Build a separate-container or microVM browser worker for unauthenticated public pages with egress proxy/allowlist, metadata/loopback/RFC1918/link-local IPv4/IPv6 blocks, read-only filesystem, resource deadlines, and no application/provider secrets.
- [ ] Consider Browserbase/authenticated browsing only after public-page sandbox evidence and a new threat-model review.
- [ ] Implement `workers/crewai_adapter.py` only on an experimental branch and publish its accuracy/latency/token-cost ablation.
- [ ] Expand to the 60-question benchmark only after the 20-question release set is stable.
- [ ] Add tenant-managed provider credentials, checkpoint pruning automation, and enterprise dashboards only from demonstrated product need.

## 7. Cross-cutting concerns to weave in throughout

| Concern | Required implementation behavior | First enforced and continuously tested |
|---|---|---|
| Tenant isolation | Every durable row has `tenant_id`; every repository query requires tenant scope; RLS is defense in depth; provider keys are encrypted per tenant (per [security.md §Tenant isolation](./security.md#tenant-isolation)) | Phase 0 migrations/repositories; every later API and persistence PR |
| Prompt injection | External content is labeled data and active content stripped. Any future browser runs in a separate secret-free container/microVM with controlled egress, metadata/private/link-local IPv4/IPv6 blocks, read-only filesystem, and resource deadlines (per [prompt-injection.md](./prompt-injection.md)) | Phase 1 normalization prompts; browser is post-launch; adversarial fixtures throughout |
| Budget enforcement | Code atomically reserves calls/cost in PostgreSQL before dispatch; reservations become consumed/released/uncertain; Redis only limits concurrency; model/Jev never grants permission (per [reflection.md §Hard limits](./reflection.md#hard-limits)) | Phase 1 ledger and every external call; Phase 3 parallel-race tests |
| Idempotency | At-least-once execution with idempotent effects: run keys, reservations/fingerprints, node uniqueness, event sequences, cancellation timestamps, and report CAS (per [reliability.md §Idempotency](./reliability.md#idempotency)) | Phase 1 create/report; Phase 2 checkpoint reconciliation/outbox; Phase 3 provider ledger |
| Event stability | Persist before publish, unique run sequence, watermarked projection handoff, contiguous gap detection, never repurpose a `type`, dedupe/upsert by stable IDs (per [events-and-sse.md](./events-and-sse.md)) | Phase 1 event contract and every later event-producing PR |
| Evidence boundary | Raw HTML/provider JSON remains in object storage; only IDs and compact verified projections enter state; writer receives supported/mixed-with-caveat claims only (per [evidence-system.md](./evidence-system.md)) | Phase 1 and checked by state-size/citation-negative tests thereafter |

## 8. Risk register

| Risk | Control | Built/tested in |
|---|---|---|
| Citation hallucination | Required evidence span, deterministic exact-span/source checks, semantic support, writer claim-ID isolation, quality-gate re-resolution (per [citation-verification.md](./citation-verification.md)) | Phase 1; benchmark gates phases 4/6 |
| Unbounded reflection/delegation | Hard counters, query fingerprints, marginal-gain threshold, `recursion_limit`, parent-only dispatch, CrewAI delegation disabled | Phases 0/2/4/5 |
| State/context blowup | Object-store artifacts, capped IDs, compact ledgers, local worker context, state-size telemetry | Phases 0/1; load tests phase 6 |
| Concurrent provider cost overrun | Transactional call/cost reservation under row lock or conditional update; committed reservation before dispatch; consumed/released/uncertain terminal states; Redis not authoritative | Phase 1 ledger; Phase 3 oversubscription tests |
| Provider retry duplicates billing | Request fingerprints, completed-result reuse, uncertain state for ambiguous timeouts, at-least-once/idempotent-effects design; no false provider-idempotency claim | Phases 1/3/5 |
| Third-party API drift | Compatibility spike before pins, tolerant normalization, recorded fixtures, scheduled initially non-blocking live contracts, changelog review before upgrades | From Phase 0 CI; each adapter phase |
| Fan-in races/overwrite | Graph-native fan-out, commutative/idempotent stable-ID reducers, explicit join, conflict logging | Phase 3 reducer/property tests |
| Projection/SSE handoff race | Consistent `snapshotSequence`, replay `after` watermark, unique run sequence, gap detection/refetch, event-ID dedupe | Phases 1/2 forced-race SSE tests |
| Checkpoint/business-row divergence | Explicit ownership, at-least-once nodes, idempotent application effects, reconciliation before redispatch; never treat checkpoint as business truth | Phase 2 crash/replay tests |
| Tenant data leakage | Mandatory repository tenant parameter, RLS, tenant-scoped object keys/events/checkpoints, cross-tenant negative tests | Phase 0 onward |
| Web prompt injection/SSRF | Data-only prompt boundary; browser deferred; future separate secret-free sandbox with controlled egress, full IP-family blocks, read-only filesystem, and deadlines | Phase 1 fixtures; post-launch browser security gate |
| Checkpoint growth/unsafe pruning | Manual monitored retention for MVP; automated pruning deferred until resume/recovery proof | Phase 2 monitoring; post-launch automation |
| Schema drift across TS/Python | Zod-first generation, checked-in schema, Pydantic generation, shared fixtures, normalized-schema diff | Phase 0 and every contract PR |
| CrewAI/LangGraph lifecycle conflict | Experimental-branch one-node adapter, no Flow/hierarchical manager, no delegation/memory/planning, parent-owned retry/interrupt/checkpoint | Post-launch ablation only |

## 9. Test and evaluation gates

| Boundary | First runnable layers from [testing.md](./testing.md) | Must pass before proceeding |
|---|---|---|
| Phase 0 → 1 | Unit, schema, security foundation | Generation clean-diff; shared fixtures; settings redaction; tenant repository/RLS negatives |
| Phase 1 → 2 | Node, adapter-fixture, integration, basic SSE, prompt-injection and budget-race fixtures | Complete verified report path; artifact-hash binding; unknown citation rejection; raw-artifact exclusion; durable-before-publish proof; no concurrent reservation overspend |
| Phase 2 → 3 | Graph, checkpoint/recovery, forced handoff-race SSE replay, cancellation failure injection | At-least-once replay with no duplicate effects; checkpoint/business-row reconciliation; contiguous projection + replay; idempotent auditable cancel |
| Phase 3 → 4 | Reducer property tests, fan-out graph tests, provider fallback/circuit tests, coordination and reservation load tests | Duplicate/out-of-order/partial/conflict cases; sibling isolation; exactly three workers; 12-search/cost limits never oversubscribed |
| Phase 4 → 5 | Reflection/incomplete/contradiction node and graph tests; minimum evaluation harness | Hard termination under adversarial “continue”; gaps/conflicts rendered; initial 20-question set runnable |
| Phase 5 release | Jev routing evaluation, 20-question benchmark, full integration/load/security/failure suite, scheduled provider contracts | Deterministic fallback; every §9.1 target measured; deployment replay/rollback drill passes; provider drift is reported but initially does not randomly block PRs |
| Post-launch increments | Capability-specific contract/security/ablation tests | Each increment improves a predeclared metric and passes the existing release suite; browser and CrewAI have additional dedicated gates |

The 20-question subset first becomes meaningful at the end of Phase 4, after verified evidence, multi-worker routing, contradictions, and incomplete outcomes exist. It is the three-month release gate. The 60-question benchmark is post-launch; all ablations must use identical questions, seeds where supported, budgets, and metric code.

### 9.1 Provisional release targets

These targets are locked before implementation results are available. They may change only through a dated architecture decision that explains the evidence and tradeoff; they must never move silently after a benchmark run.

| Metric | Initial target |
|---|---:|
| Citation URL validity | 100% |
| Exact evidence-span validity against `evidenceArtifactHash` | ≥ 99% |
| Claim citation correctness | ≥ 95% |
| Unsupported factual-claim rate | ≤ 2% |
| Required-section completeness | ≥ 90% |
| Contradiction detection recall | ≥ 80% |
| Successful crash recovery in controlled tests | 100% |
| SSE replay correctness, including forced handoff race | 100% |
| Duplicate provider effects after replay for known completed requests | 0 |
| P95 standard-report latency | ≤ 120 seconds |
| Maximum MVP reflection rounds | 1 |
| Maximum MVP searches per run | 12 |

## 10. First 5 concrete next actions

1. [x] **PR 1 — Monorepo and verified developer baseline:** `apps/web`, `services/research-api`, `packages/contracts`, `infra`, lockfiles, local PostgreSQL/Redis/LocalStack S3, CI, and confirmed paths.
2. [x] **PR 2 — Canonical contract correction:** orthogonal cancellation timestamps, `reportId`, explicit citation verification, worker/plan contracts, compact state, event sequences, provenance, and schema version 1.1.
3. [x] **PR 3 — Cross-language contract pipeline:** Zod 4 to Draft 2020-12 JSON Schema to generated Pydantic v2, plus shared valid/invalid fixtures and drift checks.
4. [x] **PR 4 — Tenant-safe authoritative core:** tenant/run tables, atomic reservations, provider ledger, node executions, ordered outbox, non-owner forced RLS, repositories, and real concurrency/isolation tests.
5. [x] **PR 5 — First evidence ingestion slice:** content-addressed S3 storage and Tavily basic Search/query-guided Extract with committed reservations, versioned schemas, usage/raw-response artifacts, strict hostname filtering, and mocked/live contract coverage.

---

## Appendix A — External Research Dossier

### A.1 LangGraph

**Capability summary:** `StateGraph` remains a schema-driven state machine; back-edges implement cycles, `add_conditional_edges` routes dynamically, `Send` provides map/reduce fan-out, and reducers reconcile parallel updates. Explicit application hard stops remain necessary even with the runtime recursion limit.

**Current API/SDK reference:** Retrieved versions: `langgraph==1.2.12`, `langgraph-checkpoint==4.2.0`, `langgraph-checkpoint-postgres==3.1.2`; optional Redis saver `langgraph-checkpoint-redis==0.5.2`. Python is 3.10+. Use `StateGraph`, `START`, `END`, `Send`, and `AsyncPostgresSaver`. Current guidance recommends `stream_events`/`astream_events(..., version="v3")` for new typed-projection consumers; `astream(..., version="v2")` remains available for low-level stream modes.

**Concrete pattern/snippet:** Compile one graph with an application-lifetime `AsyncPostgresSaver`; set `configurable.thread_id=runId`; return `Send("research_worker", branchInput)` from dispatch; put reducers on fan-in fields; observe the v3 event stream internally and translate only approved domain progress into validated, persisted `AgentEvent`s before SSE publication.

**Known limitations, gotchas, deprecations:** Postgres saver setup is a migration, not a per-request operation; strict MessagePack allowlisting is required; safe checkpoint pruning remains an open issue; Redis saver has RedisJSON/RediSearch requirements; v3 event streaming is newer and must be compatibility-tested against the selected pins; graph streams can expose private channels if relayed carelessly; `MessageGraph` is deprecated.

**Divergence from what docs assumes:** Core graph APIs are confirmed. Add compatibility-tested pins, saver setup/security, checkpoint retention, `recursion_limit`, v3 event-stream observation, and the internal-stream-versus-public-event distinction.

**Sources:** [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [map/reduce](https://docs.langchain.com/oss/python/langgraph/use-graph-api), [persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming), [stream modes](https://docs.langchain.com/oss/python/langgraph/streaming), [Postgres saver](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/README.md), [Redis saver](https://github.com/redis-developer/langgraph-redis), [releases](https://github.com/langchain-ai/langgraph/releases), [pruning issue](https://github.com/langchain-ai/langgraph/issues/8531).

### A.2 CrewAI

**Capability summary:** Role/goal/backstory agents, structured tasks, sequential/hierarchical processes, delegation, and Pydantic output remain current. The integration boundary is a callable wrapper; CrewAI is not a LangGraph `Runnable` or parent orchestrator.

**Current API/SDK reference:** Retrieved `crewai==1.15.22`, Python `>=3.10,<3.14`; imports remain `Agent`, `Task`, `Crew`, `Process`; native async execution is `akickoff()`.

**Concrete pattern/snippet:** Construct one agent and one `Task(output_pydantic=WorkerResultModel)`, run a `Crew(process=Process.sequential, memory=False, planning=False)` with `allow_delegation=False`, bounded iteration/time/retry settings, then validate `output.pydantic` as canonical `WorkerResult` in the LangGraph node.

**Known limitations, gotchas, deprecations:** Defaults are too loose for this architecture; context-window summarization can damage evidence fidelity; LangGraph interrupts inside CrewAI tools are not reliable; structured output varies by model/provider; code-execution options are deprecated/removed.

**Divergence from what docs assumes:** The one-node constraint is correct. Document explicit async/bound settings and clarify that “multiple tools” never means multiple search-provider adapters.

**Sources:** [Agents](https://docs.crewai.com/v1.15.22/en/concepts/agents), [Tasks](https://docs.crewai.com/v1.15.22/en/concepts/tasks), [Crews](https://docs.crewai.com/v1.15.22/en/concepts/crews), [Processes](https://docs.crewai.com/v1.15.22/en/concepts/processes), [Collaboration](https://docs.crewai.com/v1.15.22/en/concepts/collaboration), [release](https://github.com/crewAIInc/crewAI/releases/tag/1.15.22), [official wrapper example](https://docs.langchain.com/langsmith/deploy-other-frameworks), [interrupt issue](https://github.com/crewAIInc/crewAI/issues/2098).

### A.3 Parallel Web Infrastructure

**Capability summary:** Search provides synchronous ranked sources/excerpts; Task provides asynchronous search/crawl/inference/synthesis with schemas and citations; Task Group batches known inputs; FindAll discovers and evaluates entities; browser interaction requires an external browser MCP/integration.

**Current API/SDK reference:** Search `POST /v1/search`; Task create/status/result under `/v1/tasks/runs`; Task Group under `/v1/tasks/groups`; FindAll under `/v1beta/findall`; Task MCP `https://task-mcp.parallel.ai/mcp`; REST uses `x-api-key`, MCP uses Bearer. Retrieved `parallel-web==1.3.3` for Python/npm.

**Concrete pattern/snippet:** `AsyncParallel.task_run.create(...)` → persist run ID → `task_run.retrieve(...)` until terminal or consume provider SSE/webhook → `task_run.result(...)`; validate structured object output and project only application evidence IDs into graph state.

**Known limitations, gotchas, deprecations:** `/v1beta/search` is legacy; FindAll remains beta; Task result can block beyond default client timeouts; individual Task SSE is not durable/resumable; SDK minor releases may affect typing; browser interaction adds a separate credential and attack surface.

Default published creation quotas retrieved during research were 600 Search requests/minute, 2,000 Task/Task Group runs/minute, 300 FindAll runs/hour, and 600 Entity Search requests/minute; status/result GETs do not consume those creation quotas. Treat these as configuration and re-read them during live contract tests, not as constants.

**Divergence from what docs assumes:** MCP endpoint is confirmed. Split Task Group/FindAll, document REST paths/auth, keep a dedicated browser route, and do not block a worker thread on long Task result retrieval.

**Sources:** [Search reference](https://docs.parallel.ai/api-reference/search/search), [migration](https://docs.parallel.ai/search/search-migration-guide), [Task](https://docs.parallel.ai/task-api/task-quickstart), [Task SSE](https://docs.parallel.ai/task-api/task-sse), [Task Group](https://docs.parallel.ai/task-api/group-api), [FindAll](https://docs.parallel.ai/findall-api/findall-quickstart), [Task MCP](https://docs.parallel.ai/integrations/mcp/task-mcp), [Browser Use](https://docs.parallel.ai/integrations/browseruse), [rate limits](https://docs.parallel.ai/getting-started/rate-limits), [SDK release](https://github.com/parallel-web/parallel-sdk-python/releases/tag/v1.3.3).

### A.4 Tavily API

**Capability summary:** Search returns query-aligned LLM-ready chunks, Extract retrieves/reranks cleaned known-URL content, and Research performs asynchronous deep synthesis. Domain/date controls have different strictness across products.

**Current API/SDK reference:** `POST /search`, `POST /extract`, `POST /research`, and `GET /research/{request_id}` with Bearer auth. Retrieved `tavily-python==0.8.4` and `@tavily/core==0.7.13`. Search depths are basic/advanced/fast/ultra-fast; Research models are mini/pro/auto.

**Concrete pattern/snippet:** `AsyncTavilyClient.search(search_depth="basic", chunks_per_source=3, include_answer=False, include_raw_content=False, include_usage=True)`; post-filter hosts; then `extract(urls, query=subQuestion, chunks_per_source=3, format="markdown")`; inspect `failed_results` and usage.

**Known limitations, gotchas, deprecations:** `raw_content` is cleaned text/Markdown, not original HTML; HTTP 200 may include per-URL failures; Research cost is dynamic and higher; `auto_parameters` may raise cost; strict date filtering needs `filter_by_published_date`; domain filtering should be post-validated; the SDK does not guarantee automatic Retry-After handling.

At retrieval time, the published pricing page explicitly listed Search at 1 credit for `basic` and 2 for `advanced`; it did not separately state the cost of the `fast` and `ultra-fast` modes shown by the Search API reference, so those modes require a billing-contract check before enablement. Basic Extract cost 1 credit per five successful URLs and advanced Extract 2; Research ranged from 4–110 credits for mini and 15–250 for pro. The published default limits were 100 RPM for development keys, 1,000 RPM for production keys, and 20 RPM for Research creation. Honor `Retry-After` and keep these values outside routing code.

**Divergence from what docs assumes:** Add Extract and Research polling/SSE; basic Search is now a reranked-chunk path; clarify hard versus preferred domains, strict freshness, partial success, usage, package name, and Research cost.

**Sources:** [Search](https://docs.tavily.com/documentation/api-reference/endpoint/search), [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract), [Research create](https://docs.tavily.com/documentation/api-reference/endpoint/research), [Research status](https://docs.tavily.com/documentation/api-reference/endpoint/research-get), [pricing](https://docs.tavily.com/documentation/api-credits), [limits](https://docs.tavily.com/documentation/rate-limits), [changelog](https://docs.tavily.com/changelog), [Python package](https://pypi.org/project/tavily-python/).

### A.5 Serper API

**Capability summary:** Serper provides live Google Search and News SERP responses with structured snippets and result features. It is URL discovery/freshness input, not citable source content.

**Current API/SDK reference:** `POST https://google.serper.dev/search` and `/news`; `X-API-KEY`; JSON body with `q` and common optional `gl`, `hl`, `num`, `page`, `autocorrect`. No first-party versioned SDK or complete public machine-readable contract was found.

**Concrete pattern/snippet:** Use an async HTTP client with a short deadline and tolerant response models; normalize `organic[]`/`news[]` into candidate URL metadata; keep snippets/date labels as discovery metadata; fetch the underlying page before evidence extraction.

**Known limitations, gotchas, deprecations:** Optional SERP sections vary; published latency is not an SLO; QPS varies by paid plan; no formal freshness/completeness SLA, error catalog, idempotency key, or documented ambiguous-timeout billing protection was found.

At retrieval time, paid top-ups were $50/50,000 credits at 50 QPS, $375/500,000 at 100 QPS, $1,250/2.5 million at 200 QPS, and $3,750/12.5 million at 300 QPS; signup advertised 2,500 free queries. Paid credits were documented as valid for six months. Treat all pricing as volatile and refresh it outside normal PR CI.

**Divergence from what docs assumes:** Endpoints and snippet warning are confirmed. Replace “indexing” with “retrieval,” make concurrency plan-aware, and remove the claim that a local fingerprint guarantees no duplicate billed retry.

**Sources:** [Serper](https://serper.dev/), [playground](https://serper.dev/playground), [Search endpoint](https://google.serper.dev/search), [News endpoint](https://google.serper.dev/news), [Haystack integration](https://docs.haystack.deepset.ai/docs/serperdevwebsearch), [adapter source](https://github.com/deepset-ai/haystack-core-integrations/blob/main/integrations/serperdev/src/haystack_integrations/components/websearch/serperdev/websearch.py).

### A.6 Type-Safe AI and Runtime Validation

**Capability summary:** Constrained generation and runtime validation are separate controls. Jev provides native semantic judgments, not arbitrary application-schema generation. Cross-language correctness requires one generated contract plus runtime tests in both languages.

**Current API/SDK reference:** TypeSafe `POST https://api.typesafe.ai/v1/systemone`, Bearer auth, `{state, model, questions}`; Python `typesafe-sdk==0.7.1` is confirmed by the official PyPI files and changelog, and the retrieved JS `@typesafe-ai/sdk` was 0.6.0. `Choice`, `Score`, and `Noul` remain current. OpenAI’s current TS pattern is `responses.parse()` with `zodTextFormat`; LangChain JS supports `withStructuredOutput`.

**Concrete pattern/snippet:** Author JSON-representable contracts in Zod 4; call `z.toJSONSchema(..., {target:"draft-2020-12"})`; generate `pydantic_v2.BaseModel`; fail CI on generated diff; run shared valid/invalid fixtures in both runtimes. Batch the three Noul questions with provider Choice and ordered complexity Score, then apply budget/permission/fallback policy in code.

**Known limitations, gotchas, deprecations:** Strict model output accepts a JSON Schema subset; refusals/incomplete results need explicit handling; Zod runtime-only constructs cannot be exported safely; Pydantic validation/serialization schemas differ; Noul has probability but no confidence; TypeSafe body debug logs may contain sensitive state; Python 0.7.0 and 0.6.0 introduced breaking serialization/Score changes.

**Divergence from what docs assumes:** Jev endpoint and primitive use are confirmed. Tighten “low confidence” semantics, specify ordered Score criteria, require generation plus tests, and pin Python/JS SDKs independently.

**Sources:** [TypeSafe index](https://docs.typesafe.ai/llms.txt), [API](https://docs.typesafe.ai/api), [primitives](https://docs.typesafe.ai/primitives), [confidence](https://docs.typesafe.ai/confidence), [Python package 0.7.1](https://pypi.org/project/typesafe-sdk/), [Python SDK changelog](https://docs.typesafe.ai/sdk/python/changelog), [JS SDK](https://docs.typesafe.ai/sdk/javascript), [OpenAI structured outputs](https://github.com/openai/openai-node/blob/main/docs/structured-outputs.md), [Zod JSON Schema](https://zod.dev/json-schema), [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/), [data model generator](https://github.com/koxudaxi/datamodel-code-generator).

### A.7 Supplemental platform verification

**Capability summary:** Current Next.js Route Handlers support streamed Web `Response`s and promise-based dynamic params. Playwright browser contexts isolate cookies/cache, but downloads are accepted by default and network interception requires Service Workers to be blocked for complete visibility. Browserbase exposes per-session creation/CDP connection and queryable session metadata. PostgreSQL RLS remains appropriate but privileged/table-owner bypass must be designed out. Redis Pub/Sub remains at-most-once delivery and cannot provide application replay.

**Current API/SDK reference:** Pin actual Next.js, Playwright, and Browserbase packages only in the scaffold lockfiles; the documentation-only repository has no version constraints to reconcile. PostgreSQL 18 is the current documentation branch retrieved, but deployment should select a supported managed version rather than infer it from documentation URLs.

**Concrete pattern/snippet:** Keep the documented async Next route params; set Playwright `acceptDownloads=false` and `serviceWorkers="block"`; create one browser context/session per run and close it explicitly; run the application database connection under a non-owner/no-`BYPASSRLS` role; publish Redis notifications only after committing the Postgres outbox row.

**Known limitations, gotchas, deprecations:** A browser context is state isolation, not a complete network sandbox; URL allowlisting must cover redirects and DNS rebinding. Browserbase session metadata/replays are retained provider data that need tenant/audit/retention policy. PostgreSQL owners normally bypass RLS. Redis Pub/Sub cannot replay a missed message.

**Divergence from what docs assumes:** The Next.js route example remains current. The claimed default download block is false for Playwright and must be configured. The RLS policy needs an explicit non-owner execution role/`FORCE ROW LEVEL SECURITY`. The Postgres-outbox-over-Redis design is externally validated.

**Sources:** [Next.js Route Handlers](https://nextjs.org/docs/app/api-reference/file-conventions/route), [Playwright browser contexts](https://playwright.dev/docs/browser-contexts), [Playwright Browser API](https://playwright.dev/docs/api/class-browser), [Playwright network interception](https://playwright.dev/docs/network), [Browserbase retrieval](https://docs.browserbase.com/use-cases/web-data-retrieval), [Browserbase session metadata](https://docs.browserbase.com/platform/browser/core-features/session-metadata), [PostgreSQL RLS](https://www.postgresql.org/docs/current/ddl-rowsecurity.html), [Redis Pub/Sub](https://redis.io/docs/latest/develop/pubsub/).
