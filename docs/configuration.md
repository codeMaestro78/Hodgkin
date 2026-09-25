# Configuration

Every configurable value referenced by the architecture blueprint. Values
with a concrete name and default **in the blueprint itself** (primarily the
`Budget` contract) are listed as such. Everything else is a **proposed**
grouping/name pending confirmation against the actual repository — per
project rule, configuration names are never invented as if confirmed; mark
unconfirmed entries `PROPOSED`.

`TODO: verify repository path` for the actual config source
(proposed: `.env.example`, `services/research-api/config.py`,
`apps/web/.env.example`).

## Application

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `APP_ENV` | string | Yes | — | `development` \| `staging` \| `production` | enum | Low | All services | `PROPOSED` |
| `NEXT_PUBLIC_APP_URL` | string (URL) | Yes | — | Base URL of the Next.js app, used for report/share links | — | Low | Next.js app | `PROPOSED` |

## Database

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `DATABASE_URL` | string (connection string) | Yes | — | PostgreSQL connection string | — | **High** | Python service, migrations | `PROPOSED` |
| `DATABASE_POOL_SIZE` | int | No | — | Connection pool size | ≥ 1 | Low | Python service | `PROPOSED` |

## Redis

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `REDIS_URL` | string (connection string) | Yes | — | Redis connection string | — | **High** | Python service (coordination) | `PROPOSED` |

## LangGraph

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `LANGGRAPH_CHECKPOINTER` | string | No | Postgres-backed | Checkpointer backend selection | — | Low | LangGraph runtime | `PROPOSED` |
| `concurrency_limit` | int | No | — | Per-run worker concurrency cap used by `dispatch_workers` | ≥ 1 | Low | `planner`/`planner_delta` dispatch | `PROPOSED` (referenced in blueprint pseudocode as a state field, not a confirmed env var) |

## Models

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `LLM_PROVIDER` | string | Yes | — | Model provider for planner/distiller/verifier/reflector/writer calls | — | Low | Python service | `PROPOSED` |
| `LLM_MODEL_NAME` | string | Yes | — | Model identifier | — | Low | Python service | `PROPOSED` |

## Providers

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `SERPER_API_KEY` | string | Yes (if Serper enabled) | — | Auth for `google.serper.dev` | — | **High** | Serper adapter | `PROPOSED` |
| `TAVILY_API_KEY` | string | Yes (if Tavily enabled) | — | Auth for `api.tavily.com` | — | **High** | Tavily adapter | `PROPOSED` |
| `PARALLEL_API_KEY` | string | Yes (if Parallel enabled) | — | Auth for Parallel Task/Search APIs | — | **High** | Parallel adapter | `PROPOSED` |
| `TYPESAFE_AI_API_KEY` | string | Yes (if Jev enabled) | — | Auth for `api.typesafe.ai` | — | **High** | Provider router, verifier | `PROPOSED` |
| `BROWSERBASE_API_KEY` | string | Yes (if Browserbase enabled) | — | Auth for managed browser sessions | — | **High** | Browser adapter | `PROPOSED` |

## Budgets

These fields are the blueprint's own `BudgetSchema` — confirmed against
the source document, not invented. See
[reflection.md](./reflection.md#hard-limits) and
[state-management.md](./state-management.md#budget).

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by |
|---|---|---|---|---|---|---|---|
| `maxWallClockMs` | int | Yes | — | Max run duration | 1 – 1,800,000 (30 min) | Low | Reflection routing, node deadlines |
| `maxSearchCalls` | int | Yes | 20 (per blueprint narrative) | Max provider search calls per run | 1 – 50 | Low | `provider_router`, `research_worker` |
| `maxBrowserSessions` | int | Yes | 2 (per blueprint narrative) | Max browser sessions per run | 0 – 5 | Low | Browser adapters |
| `maxReflectionRounds` | int | Yes | 2 (per blueprint narrative) | Max delta-research rounds | 0 – 3 | Low | `route_after_reflection` |
| `maxInputTokens` | int | Yes | — | Max cumulative input tokens | > 0 | Low | Usage enforcement |
| `maxOutputTokens` | int | Yes | — | Max cumulative output tokens | > 0 | Low | Usage enforcement |
| `maxEstimatedCostUsd` | number | Yes | — | Max estimated cost | ≥ 0 | Low | Usage enforcement |
| `maxSubQuestions` (initial) | int | Yes | 8 (per blueprint narrative) | Max sub-questions from `planner` | — | Low | `planner` output validation |
| `maxSubQuestions` (delta) | int | Yes | 4 (per blueprint narrative) | Max sub-questions from `planner_delta` | — | Low | `planner_delta` output validation |
| `maxSourcesPerSubQuestion` | int | Yes | 6 (per blueprint narrative) | Max sources fetched per sub-question | — | Low | `research_worker` |

## Concurrency

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `WORKER_CONCURRENCY_LIMIT` | int | No | — | Per-run worker concurrency (env-level default for `concurrency_limit`) | ≥ 1 | Low | Dispatch | `PROPOSED` |
| `PROVIDER_GLOBAL_CONCURRENCY_<PROVIDER>` | int | No | — | Global concurrent-call cap per provider | ≥ 1 | Low | Provider semaphore | `PROPOSED` |

## Browser

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `BROWSER_ALLOWED_PROTOCOLS` | string list | No | `https` | Allowlisted protocols | — | Low | Browser adapter | `PROPOSED` |
| `BROWSER_BLOCK_PRIVATE_IPS` | bool | No | `true` | SSRF protection toggle — should not be disabled | — | **High** | Browser adapter | `PROPOSED` |
| `BROWSER_SESSION_TIMEOUT_MS` | int | No | — | Hard timeout per browser session | > 0 | Low | Browser adapter | `PROPOSED` |

## SSE

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `SSE_HEARTBEAT_INTERVAL_MS` | int | No | 15,000–30,000 (proposed) | Heartbeat comment interval | > 0 | Low | Events route | `PROPOSED` |

## Security

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `SESSION_SECRET` | string | Yes | — | Session cookie signing secret | — | **High** | Next.js BFF | `PROPOSED` |
| `INTERNAL_SERVICE_AUTH` | string | Yes | — | BFF ↔ Python service auth material | — | **High** | Both services | `PROPOSED` |

## Storage

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `OBJECT_STORAGE_BUCKET` | string | Yes | — | Bucket/container for raw artifacts | — | Low | `research_worker`, distiller | `PROPOSED` |
| `OBJECT_STORAGE_CREDENTIALS` | string/JSON | Yes | — | Storage backend credentials | — | **High** | Same | `PROPOSED` |
| `ARTIFACT_RETENTION_DAYS` | int | No | — | Default retention window | > 0 | Low | Retention job | `PROPOSED` |

## Observability

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `OTEL_EXPORTER_ENDPOINT` | string (URL) | No | — | Tracing/metrics exporter | — | Low | Both services | `PROPOSED` |

## Evaluation

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `EVAL_BENCHMARK_PATH` | string (path) | No | — | Location of the 60-question benchmark set | — | Low | Eval tooling | `PROPOSED` |
| `EVAL_SCHEDULE_CRON` | string | No | — | Schedule for provider-contract and benchmark runs | — | Low | CI | `PROPOSED` |

---

**Every row marked `PROPOSED` must be confirmed (name, default, and range)
against the real repository before being treated as authoritative** — see
[agent.md](./agent.md#14-agent-modification-rules). Only the Budgets
section is grounded directly in the architecture blueprint's own schema.
