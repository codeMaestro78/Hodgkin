# Configuration

Implemented settings are defined in `.env.example` and
`services/research-api/src/research_api/config.py`. Rows for later phases remain `PROPOSED`.

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
| `TYPESAFE_API_KEY` | string | Yes (if Jev enabled) | — | Auth for `api.typesafe.ai` | — | **High** | Provider router, verifier | `PROPOSED` |
| `BROWSERBASE_API_KEY` | string | Yes (if Browserbase enabled) | — | Auth for managed browser sessions | — | **High** | Browser adapter | `PROPOSED` |

## Budgets

These fields are the blueprint's own `BudgetSchema` — confirmed against
the source document, not invented. See
[reflection.md](./reflection.md#hard-limits) and
[state-management.md](./state-management.md#budget).

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by |
|---|---|---|---|---|---|---|---|
| `maxWallClockMs` | int | Yes | — | Max run duration | 1 – 1,800,000 (30 min) | Low | Reflection routing, node deadlines |
| `maxSearchCalls` | int | Yes | 12 (MVP) | Max provider search calls per run | 1 – 50 | Low | `provider_router`, `research_worker` |
| `maxBrowserSessions` | int | Yes | 0 (MVP) | Max browser sessions per run | 0 – 5 | Low | Browser adapters |
| `maxReflectionRounds` | int | Yes | 1 (MVP) | Max delta-research rounds | 0 – 3 | Low | `route_after_reflection` |
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
| `NEXT_PUBLIC_APP_URL` | URL | Yes | `http://localhost:3000` locally | Canonical callback/CSRF origin | HTTPS in production | Low | Next.js | `CONFIRMED` |
| `NEXT_PUBLIC_SUPABASE_URL` | URL | Yes | — | Supabase Auth project URL | — | Public | Next.js | `CONFIRMED` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | string | Yes | — | Publishable key, never service role | — | Public | Next.js | `CONFIRMED` |
| `SUPABASE_URL` | URL | Yes | — | Same Auth project URL | — | Public | Python API | `CONFIRMED` |
| `SUPABASE_PUBLISHABLE_KEY` | string | Yes | — | Same publishable key | — | Public | Python API | `CONFIRMED` |
| `INTERNAL_SERVICE_AUTH` | string | Yes | — | BFF ↔ Python shared secret plus user bearer verification | — | **High** | Both services | `CONFIRMED` |

## Storage

| Name | Type | Required | Default | Description | Range | Sensitivity | Used by | Status |
|---|---|---|---|---|---|---|---|---|
| `OBJECT_STORAGE_ENDPOINT` | URL | Yes | `http://localhost:54566` | S3-compatible endpoint | — | Low | Artifact store | `CONFIRMED` |
| `OBJECT_STORAGE_BUCKET` | string | Yes | `research-artifacts` | Bucket/container for raw artifacts | — | Low | `research_worker`, distiller | `CONFIRMED` |
| `OBJECT_STORAGE_ACCESS_KEY` | string | Yes | `test` locally | S3 access key | — | **High** | Artifact store | `CONFIRMED` |
| `OBJECT_STORAGE_SECRET_KEY` | string | Yes | `test` locally | S3 secret key | — | **High** | Artifact store | `CONFIRMED` |
| `ARTIFACT_RETENTION_DAYS` | int | No | 30 | Default retention window | > 0 | Low | Retention job | `CONFIRMED` |

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
