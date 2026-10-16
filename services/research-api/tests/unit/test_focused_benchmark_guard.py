"""Safety gates only: never start providers or connect to any database."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_api import config

SCRIPT = Path(__file__).parents[2] / "scripts" / "benchmark_focused.py"


@pytest.mark.parametrize("arguments", [[], ["--confirm-paid", "--runs", "3", "--offset", "2"]])
def test_cli_rejects_missing_approval_or_out_of_range_workload(arguments):
    result = subprocess.run(  # noqa: S603 - fixed local script, no shell or external input.
        [sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "benchmark.started" not in result.stderr


@pytest.mark.parametrize(
    "database",
    [
        "postgresql+psycopg://fixture@cloud.example.test/db",
        "postgresql+psycopg://fixture@localhost/db?host=cloud.example.test",
    ],
)
async def test_benchmark_rejects_remote_and_overridden_local_destinations(monkeypatch, database):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("focused_benchmark_guard", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("TEST_DATABASE_ADMIN_URL", "postgresql://fixture@localhost/db")
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            APP_ENV="test",
            DATABASE_URL=database,
            OBJECT_STORAGE_ENDPOINT="http://localhost:54566",
            REDIS_URL="redis://localhost:56379/0",
        ),
    )
    with pytest.raises(ValueError, match="loopback"):
        await module.benchmark(1)
