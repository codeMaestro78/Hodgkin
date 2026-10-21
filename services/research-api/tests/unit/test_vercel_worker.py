import pytest

from research_api.config import Settings
from research_api.main import _should_start_embedded_dispatcher
from research_api.worker import run_worker


def test_embedded_dispatcher_is_disabled_on_vercel(monkeypatch):
    settings = Settings(APP_ENV="development", DISPATCHER_ENABLED=True)
    monkeypatch.setenv("VERCEL", "1")

    assert not _should_start_embedded_dispatcher(settings)


def test_embedded_dispatcher_remains_enabled_for_local_runtime(monkeypatch):
    settings = Settings(APP_ENV="development", DISPATCHER_ENABLED=True)
    monkeypatch.delenv("VERCEL", raising=False)

    assert _should_start_embedded_dispatcher(settings)


def test_embedded_dispatcher_respects_existing_runtime_gates(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)

    assert not _should_start_embedded_dispatcher(
        Settings(APP_ENV="test", DISPATCHER_ENABLED=True)
    )
    assert not _should_start_embedded_dispatcher(
        Settings(APP_ENV="development", DISPATCHER_ENABLED=False)
    )


@pytest.mark.asyncio
async def test_daemon_worker_refuses_test_environment(monkeypatch):
    monkeypatch.setattr(
        "research_api.worker.get_settings",
        lambda: Settings(APP_ENV="test"),
    )

    with pytest.raises(RuntimeError, match="APP_ENV=test"):
        await run_worker()
