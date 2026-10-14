# Research API

The Python service owns tenant-safe application persistence, provider-call reservations,
artifact storage, provider adapters, and the durable LangGraph research runtime.

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn research_api.main:app --reload --reload-dir src/research_api
uv run pytest
```

Generate Pydantic mirrors from the checked-in Zod JSON Schema documents with
`./scripts/generate-pydantic.sh` from this directory.

## Durable runtime deployment requirement

Apply Alembic migration **0007** with the migration-owner credentials before
starting this version. `/health/ready` returns 503 when durable tables are missing.
Runtime `DATABASE_URL` must use the non-owner, non-BYPASSRLS service role.
The API lifespan drains PostgreSQL jobs (default two workers/process); disabling
`DISPATCHER_ENABLED` leaves submissions queued. Do not deploy this worker into an
ephemeral request-only process. See [implementation and recovery runbook](../../docs/implementation/durable-runtime.md).
