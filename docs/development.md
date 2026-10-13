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
real intake → planner → Tavily collection path. Unit and integration tests do not
make billed external calls.

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
uv run uvicorn research_api.main:app --reload
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
