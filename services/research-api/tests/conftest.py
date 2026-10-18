"""Keep automated tests on local Docker infrastructure, never configured cloud services."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

os.environ["APP_ENV"] = "test"
_defaults = {
    "DATABASE_URL": "postgresql+psycopg://research_app:research_app@localhost:55432/research",
    "TEST_DATABASE_ADMIN_URL": (
        "postgresql+psycopg://research_owner:research_owner@localhost:55432/research"
    ),
    "OBJECT_STORAGE_ENDPOINT": "http://localhost:54566",
    "TEST_REDIS_URL": "redis://localhost:56379/0",
}
for name, default in _defaults.items():
    value = os.environ.get(name, default)
    # Respect CI ports, but never silently accept the service's cloud configuration.
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, strict_parsing=True)
    socket_values = query.get("host", [])
    socket_path = socket_values[0] if len(socket_values) == 1 else ""
    local_socket = (
        set(query) == {"host"}
        and Path(socket_path).is_absolute()
        # A disposable PostgreSQL socket may be mounted here inside bwrap only.
        and Path(socket_path).resolve().is_relative_to(Path("/tmp"))  # noqa: S108
    )
    local_host = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and not parsed.query
    if not (local_host or local_socket) or parsed.fragment:
        raise RuntimeError(f"{name} must point to loopback test infrastructure")
    os.environ[name] = value
os.environ["DATABASE_ADMIN_URL"] = os.environ["TEST_DATABASE_ADMIN_URL"]
