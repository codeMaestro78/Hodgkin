from fastapi import FastAPI

from research_api.api import router as research_router
from research_api.config import get_settings

app = FastAPI(title="Research API", version="0.1.0")
app.state.background_tasks = set()
app.include_router(research_router)


@app.get("/health", tags=["health"])
@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "research-api"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "environment": settings.APP_ENV}
