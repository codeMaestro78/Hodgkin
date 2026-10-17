# Development

These commands are verified against the Phase 0/1 repository scaffold. The current implemented
boundary is shared contracts, tenant-safe persistence, artifact storage, the first research UI,
and the intake → planner → Tavily LangGraph slice. Verification, report writing, and SSE are later
phases.

## Prerequisites

- Node.js 24.15.0 (`.nvmrc`)
- pnpm 10.18.3 (pinned in the root `package.json`)
- Python 3.12 (`.python-version`)
- uv 0.11.1 or compatible
- Docker with Compose

`OPENAI_API_KEY` (with `LLM_MODEL_NAME=gpt-4o-mini`) and `TAVILY_API_KEY` are required for the
real intake → planner → Tavily collection path. Optional per-role `LLM_<ROLE>_PROVIDER` and
`LLM_<ROLE>_MODEL_NAME` settings can route planner, writer, and claim-review calls separately;
OpenRouter routes require `OPENROUTER_API_KEY`. Each new research run persists its route snapshot.
The coverage reflector is deterministic and does not call a model. Unit and integration tests do
not make billed external calls.

## Install

```bash
corepack enable
pnpm install --frozen-lockfile
cd services/research-api
uv sync --frozen --all-groups
```

Copy `.env.example` to `.env` when local overrides or a live Tavily key are needed.

## Start infrastructure and migrate

```bash
docker compose up -d postgres redis object-storage
cd services/research-api
DATABASE_ADMIN_URL=postgresql+psycopg://research_owner:research_owner@localhost:55432/research \
  uv run alembic upgrade head
```

The Compose defaults use host ports `55432`, `56379`, and `54566` to avoid common developer-machine
collisions. Override them with `POSTGRES_PORT`, `REDIS_PORT`, and `OBJECT_STORAGE_PORT`. PostgreSQL
and the S3-compatible LocalStack service are durable local dependencies; Redis is coordination-only.

## Run applications

```bash
# Next.js shell
pnpm --filter @research/web dev

# FastAPI service
cd services/research-api
uv run uvicorn research_api.main:app --reload --reload-dir src/research_api
```

## Generate contracts

```bash
pnpm contracts:generate
cd services/research-api
./scripts/generate-pydantic.sh
```

Zod is the source of truth. Commit the generated Draft 2020-12 JSON Schemas and Pydantic models;
CI fails if regeneration produces a diff.

## Verify

```bash
pnpm typecheck
pnpm test
pnpm build

cd services/research-api
uv run ruff check .
uv run mypy src
uv run pytest
```

The Python suite expects local infrastructure for tests marked `integration`. Scheduled tests marked
`live_provider` require `TAVILY_API_KEY`; without it they skip safely.

Start debugging from the durable run projection, reservation/provider ledgers, and ordered event
outbox. See [observability.md](./observability.md) and [agent.md](./agent.md#17-debugging-guide).

### Diagnosing runtime network latency

`auth.verify` retains a fresh Supabase `/auth/v1/user` check for every request. Its
connection deadline is 3 seconds, pool wait is 1 second, read timeout is 5 seconds,
and the overall request deadline is 6 seconds. Failures return 503; invalid sessions
remain 401. There is no identity acceptance cache or automatic auth retry.

At INFO level, slow connection acquisition emits `db.connection.acquire` (over one
second). It includes pool wait, connection establishment and pre-ping, so it is not
a measurement of queue wait alone. `db.statement.slow` includes only an allowlisted
`commandCategory` and `executemany`, never SQL text or parameters. DEBUG transaction
records include `acquireMs` and `setupMs`; setup includes acquisition, tenant context
and any execution lease check. Compare these to statement timings before changing
pool settings or queries.

Redis wakeups are optional hints. Failed publication enters a 30-second cooldown;
listener reconnects back off from 1 to 30 seconds. Local wakeups and PostgreSQL replay
continue during outages. Dropped hints can incur the normal polling delay. Check that
the active environment's Redis hostname resolves from the API's execution environment
when `event_wakeups.redis_unavailable` appears; the cooldown does not repair DNS.
