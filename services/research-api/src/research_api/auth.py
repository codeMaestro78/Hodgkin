from __future__ import annotations

import asyncio
import secrets
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from research_api.config import Settings
from research_api.db.models import User
from research_api.db.session import tenant_session
from research_api.telemetry import operation_event

_identity_client: httpx.AsyncClient | None = None
# A dead identity endpoint should not occupy a workspace request for ten seconds.
# Every request still validates against Supabase; no successful identities are cached.
IDENTITY_TIMEOUT = httpx.Timeout(5.0, connect=3.0, pool=1.0)
IDENTITY_DEADLINE_SECONDS = 6.0


@asynccontextmanager
async def identity_transport() -> AsyncIterator[None]:
    """Reuse connections, never cache identities or authorization decisions."""
    global _identity_client
    async with httpx.AsyncClient(timeout=IDENTITY_TIMEOUT, follow_redirects=False) as client:
        _identity_client = client
        try:
            yield
        finally:
            _identity_client = None


@dataclass(frozen=True, slots=True)
class Caller:
    tenant_id: uuid.UUID
    user_id: uuid.UUID


async def verified_subject(settings: Settings, authorization: str | None) -> uuid.UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="sign in to access research")
    token = authorization[7:].strip()
    if not token or len(token) > 16384:
        raise HTTPException(status_code=401, detail="invalid session")
    if not settings.SUPABASE_URL or not settings.SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured")
    try:
        started = monotonic()
        client = _identity_client
        owned = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=IDENTITY_TIMEOUT, follow_redirects=False)
        try:
            async with asyncio.timeout(IDENTITY_DEADLINE_SECONDS):
                response = await client.get(
                    f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user",
                    headers={
                        "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                        "Authorization": f"Bearer {token}",
                    },
                    timeout=IDENTITY_TIMEOUT,
                )
            operation_event(
                "auth.verify",
                started=started,
                statusCode=response.status_code,
                outcome="succeeded" if response.status_code == 200 else "rejected",
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            operation_event("auth.verify", started=started, outcome="failed", error=exc)
            raise
        finally:
            if owned:
                await client.aclose()
        if response.status_code in (401, 403):
            raise HTTPException(status_code=401, detail="session expired or invalid")
        if response.status_code != 200:
            raise HTTPException(status_code=503, detail="identity service unavailable")
        user = response.json()
        if user.get("is_anonymous") or user.get("role") != "authenticated":
            raise HTTPException(status_code=401, detail="a registered account is required")
        if not user.get("email_confirmed_at"):
            raise HTTPException(status_code=403, detail="confirm your email before researching")
        return uuid.UUID(user["id"])
    except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail="identity service unavailable") from exc


async def authenticated_caller(
    settings: Settings,
    internal_service_auth: str | None,
    development_tenant_id: str | None = None,
    development_user_id: str | None = None,
    authorization: str | None = None,
) -> Caller:
    # Legacy identity headers are deliberately ignored, including in development.
    expected = (
        settings.INTERNAL_SERVICE_AUTH.get_secret_value()
        if settings.INTERNAL_SERVICE_AUTH
        else None
    )
    if (
        not expected
        or not internal_service_auth
        or not secrets.compare_digest(expected, internal_service_auth)
    ):
        raise HTTPException(status_code=401, detail="invalid service credentials")
    subject = await verified_subject(settings, authorization)
    # Personal workspace IDs are provisioned by the DB trigger, never metadata/headers.
    async with tenant_session(str(subject)) as session:
        user = await session.scalar(
            select(User).where(
                User.id == subject,
                User.tenant_id == subject,
                User.external_subject == f"supabase:{subject}",
            )
        )
        if user is None:
            raise HTTPException(status_code=403, detail="account workspace is not provisioned")
    return Caller(tenant_id=subject, user_id=subject)
