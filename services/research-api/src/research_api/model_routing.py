"""Validated, persistable model routes for the small set of research roles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select

type ModelProvider = Literal["openai", "openrouter"]
type ModelRole = Literal["planner", "writer", "claim_review"]
MODEL_ROLES: tuple[ModelRole, ...] = ("planner", "writer", "claim_review")


@dataclass(frozen=True, slots=True)
class ModelRoute:
    provider: ModelProvider
    model: str

    def __post_init__(self) -> None:
        if self.provider not in {"openai", "openrouter"}:
            raise ValueError("unsupported model provider")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200:
            raise ValueError("model name must be non-empty and at most 200 chars")

    def as_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


def normalize_routing(value: object) -> dict[ModelRole, ModelRoute]:
    if not isinstance(value, dict):
        raise ValueError("saved model routing must be an object")
    routes: dict[ModelRole, ModelRoute] = {}
    for role in MODEL_ROLES:
        raw = value.get(role)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"saved {role} model route must be an object")
        if set(raw) != {"provider", "model"}:
            raise ValueError(f"saved {role} model route has unexpected fields")
        provider = raw.get("provider")
        if not isinstance(provider, str) or provider not in {"openai", "openrouter"}:
            raise ValueError("unsupported model provider in saved routing")
        model = raw.get("model")
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("saved model name must be a non-empty string of at most 200 chars")
        routes[role] = ModelRoute(provider=provider, model=model.strip())  # type: ignore[arg-type]
    unknown = set(value) - set(MODEL_ROLES)
    if unknown:
        raise ValueError("saved model routing contains an unknown role")
    return routes


async def pin_run_model_routing(
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    configured: dict[str, dict[str, str]],
    legacy: dict[str, dict[str, str]],
) -> dict[ModelRole, ModelRoute]:
    """Snapshot once under the tenant-scoped run lock; preserve existing pins."""
    from research_api.db.models import ResearchRun
    from research_api.db.session import tenant_session

    async with tenant_session(str(tenant_id)) as session:
        run = await session.scalar(
            select(ResearchRun)
            .where(ResearchRun.tenant_id == tenant_id, ResearchRun.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise LookupError("research run missing while pinning model routing")
        saved = normalize_routing(run.model_routing or {})
        if not saved:
            # Pre-migration runs used the legacy single-model setting. Do not
            # silently route their in-flight/replayed work to a newly promoted model.
            saved = normalize_routing(legacy)
            run.model_routing = {role: route.as_dict() for role, route in saved.items()}
        elif set(saved) != set(MODEL_ROLES):
            defaults = normalize_routing(configured)
            saved = {role: saved.get(role, defaults[role]) for role in MODEL_ROLES}
            run.model_routing = {role: route.as_dict() for role, route in saved.items()}
        return saved
