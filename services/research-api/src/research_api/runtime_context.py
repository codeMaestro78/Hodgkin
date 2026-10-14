"""Lease identity propagates to graph children, never browser-supplied headers."""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class JobFence:
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    owner_id: uuid.UUID
    generation: int


current_job: ContextVar[JobFence | None] = ContextVar("current_job", default=None)


class LeaseLostError(RuntimeError):
    """A stale process must stop without changing the current owner's run."""
