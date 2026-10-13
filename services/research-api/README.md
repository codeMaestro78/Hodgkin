# Research API

The Python service owns tenant-safe application persistence, provider-call reservations,
artifact storage, provider adapters, and—starting in the next milestone—the LangGraph runtime.

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn research_api.main:app --reload
uv run pytest
```

Generate Pydantic mirrors from the checked-in Zod JSON Schema documents with
`./scripts/generate-pydantic.sh` from this directory.
