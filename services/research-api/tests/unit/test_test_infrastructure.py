"""Test configuration must respect CI ports without admitting hosted targets."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("bad_target", [None, "database", "storage", "override"])
def test_fixture_targets_are_local_and_ci_ports_are_preserved(bad_target):
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+psycopg://fixture:fixture@localhost:5432/research",
        "TEST_DATABASE_ADMIN_URL": "postgresql+psycopg://fixture:fixture@localhost:5432/research",
        "OBJECT_STORAGE_ENDPOINT": "http://localhost:4566",
    }
    if bad_target == "database":
        env["DATABASE_URL"] = "postgresql+psycopg://fixture:secret@cloud.example/research"
    elif bad_target == "storage":
        env["OBJECT_STORAGE_ENDPOINT"] = "https://cloud.example"
    elif bad_target == "override":
        env["DATABASE_URL"] += "?host=cloud.example"
    fixture = Path(__file__).resolve().parents[1] / "conftest.py"
    program = (
        "import runpy,os,json; from urllib.parse import urlsplit; "
        f"runpy.run_path({str(fixture)!r}); "
        "print(json.dumps([urlsplit(os.environ[k]).port for k in "
        "['DATABASE_URL','DATABASE_ADMIN_URL','OBJECT_STORAGE_ENDPOINT']]))"
    )
    result = subprocess.run(  # noqa: S603 -- fixed interpreter/script and fixture-only environment.
        [sys.executable, "-c", program],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if bad_target:
        assert result.returncode != 0 and "loopback" in result.stderr
        assert "secret" not in result.stderr
    else:
        assert result.returncode == 0
        assert json.loads(result.stdout) == [5432, 5432, 4566]
