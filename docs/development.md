# Development

How engineers work on this repository locally. **No commands below have
been verified against a real repository** — this is a `PROPOSED` starting
point derived from the declared stack (Next.js 15, TypeScript, Python,
LangGraph, PostgreSQL, Redis, Tailwind CSS) in
[architecture.md](./architecture.md). Confirm every command against the
actual `package.json` / `pyproject.toml` / lockfiles / Makefile before
relying on it, and update this file once confirmed (see
[agent.md](./agent.md#14-agent-modification-rules)).

## Prerequisites (proposed)

- Node.js (version per `apps/web/package.json` engines field — `TODO: verify repository path`)
- Python (version per `pyproject.toml`/`requirements.txt` — `TODO: verify repository path`)
- Docker (for local PostgreSQL/Redis)
- Provider API keys for Serper, Tavily, Parallel, TypeSafe AI Jev,
  Browserbase (or a subset, if local dev stubs are supported)

## Installation (proposed)

```bash
# Frontend
cd apps/web && npm install   # TODO: verify repository path and package manager (npm/pnpm/yarn)

# Backend
cd services/research-api && pip install -r requirements.txt --break-system-packages
# TODO: verify repository path and whether this project uses poetry/uv instead
```

## Environment setup

Copy the example environment file(s) and fill in provider keys and
connection strings per [configuration.md](./configuration.md):

```bash
cp .env.example .env   # TODO: verify repository path — may be per-service
```

## Local infrastructure (proposed)

```bash
docker compose up -d postgres redis   # TODO: verify repository path / compose file existence
```

## Database setup (proposed)

```bash
cd services/research-api
alembic upgrade head   # TODO: verify — migration tool not confirmed (alembic assumed for a Python/Postgres service)
```

## Redis setup

No setup beyond the local container above — Redis is used purely as
ephemeral coordination (see [redis.md](./redis.md)); nothing needs
seeding.

## Running the frontend (proposed)

```bash
cd apps/web && npm run dev   # TODO: verify repository path and script name
```

## Running the backend / LangGraph runtime (proposed)

```bash
cd services/research-api && python -m app.main   # TODO: verify repository path and entrypoint
```

## Running tests (proposed)

```bash
# Frontend
cd apps/web && npm test        # TODO: verify script name

# Backend
cd services/research-api && pytest   # TODO: verify test runner
```

See [testing.md](./testing.md) for the full test-layer breakdown.

## Linting, formatting, type checking (proposed)

```bash
cd apps/web && npm run lint && npm run typecheck   # TODO: verify script names
cd services/research-api && ruff check . && mypy .  # TODO: verify tool choice
```

## Debugging

Start from the durable run projection and event log, not ad-hoc print
statements — see [observability.md](./observability.md#end-to-end-traceability)
and the symptom-based table in
[agent.md](./agent.md#17-debugging-guide).

## Common problems (proposed placeholders)

`PROPOSED` — this section should be filled in from real onboarding
friction once the repository exists. Likely candidates based on the
architecture:

- **SSE stream not updating locally**: confirm the dev server isn't
  buffering the response (see [events-and-sse.md](./events-and-sse.md#transport)
  — `X-Accel-Buffering: no` and equivalent dev-proxy settings).
- **Provider calls failing locally**: confirm API keys are set per
  [configuration.md](./configuration.md#providers); consider whether the
  project offers recorded-fixture stubs for offline development.
- **Checkpoint restore errors after a schema change**: confirm
  `schemaVersion` was bumped and migrations applied — see
  [state-management.md](./state-management.md) and
  [database.md](./database.md#checkpointer-storage).

---

**Do not treat any command in this file as verified.** Replace `TODO:
verify repository path` markers with confirmed commands as soon as the
actual repository is available for inspection, per
[agent.md](./agent.md#3-repository-navigation).
