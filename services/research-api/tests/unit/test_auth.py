import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from research_api import auth
from research_api.config import Settings


def settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="production",
        INTERNAL_SERVICE_AUTH=SecretStr("fixture-service"),
        SUPABASE_URL="https://identity.example.test",
        SUPABASE_PUBLISHABLE_KEY="fixture-public",
    )


@pytest.mark.parametrize("service", [None, "wrong"])
async def test_rejects_missing_or_wrong_internal_secret(service: str | None) -> None:
    with pytest.raises(HTTPException) as error:
        await auth.authenticated_caller(settings(), service, authorization="Bearer fixture")
    assert error.value.status_code == 401


async def test_development_headers_never_replace_session() -> None:
    config = settings().model_copy(update={"APP_ENV": "development"})
    with pytest.raises(HTTPException) as error:
        await auth.authenticated_caller(
            config, "fixture-service", str(uuid.uuid4()), str(uuid.uuid4())
        )
    assert error.value.status_code == 401


def mock_identity(
    monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, object]
) -> AsyncMock:
    response = httpx.Response(status, json=body)
    get = AsyncMock(return_value=response)
    client = AsyncMock()
    client.get = get
    client.__aenter__.return_value = client
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: client)
    return get


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (401, {}, 401),
        (403, {}, 401),
        (500, {}, 503),
        (200, {"role": "authenticated", "is_anonymous": True}, 401),
        (200, {"role": "authenticated", "id": str(uuid.uuid4())}, 403),
        (200, {"role": "authenticated", "email_confirmed_at": "2026-01-01", "id": "bad-id"}, 503),
    ],
)
async def test_identity_failures_fail_closed(
    monkeypatch: pytest.MonkeyPatch, status: int, body: dict[str, object], expected: int
) -> None:
    mock_identity(monkeypatch, status, body)
    with pytest.raises(HTTPException) as error:
        await auth.verified_subject(settings(), "Bearer fixture")
    assert error.value.status_code == expected


async def test_uses_verified_subject_not_metadata_or_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = uuid.uuid4()
    get = mock_identity(
        monkeypatch,
        200,
        {
            "id": str(subject),
            "role": "authenticated",
            "email_confirmed_at": "2026-01-01",
            "user_metadata": {"tenant_id": str(uuid.uuid4())},
        },
    )
    session = AsyncMock()
    session.scalar.return_value = object()
    contexts: list[str] = []

    @asynccontextmanager
    async def tenant_session(tenant: str):
        contexts.append(tenant)
        yield session

    monkeypatch.setattr(auth, "tenant_session", tenant_session)
    caller = await auth.authenticated_caller(
        settings(),
        "fixture-service",
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        authorization="Bearer fixture",
    )
    assert caller.user_id == caller.tenant_id == subject
    assert contexts == [str(subject)]
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer fixture"


async def test_unprovisioned_user_cannot_create_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    subject = uuid.uuid4()
    mock_identity(
        monkeypatch,
        200,
        {"id": str(subject), "role": "authenticated", "email_confirmed_at": "2026-01-01"},
    )
    session = AsyncMock()
    session.scalar.return_value = None

    @asynccontextmanager
    async def tenant_session(tenant: str):
        yield session

    monkeypatch.setattr(auth, "tenant_session", tenant_session)
    with pytest.raises(HTTPException) as error:
        await auth.authenticated_caller(
            settings(), "fixture-service", authorization="Bearer fixture"
        )
    assert error.value.status_code == 403
