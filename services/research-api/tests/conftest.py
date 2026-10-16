"""Keep automated tests on local Docker infrastructure, never configured cloud services."""

import os
from urllib.parse import urlsplit

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
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must point to loopback test infrastructure")
    os.environ[name] = value
os.environ["DATABASE_ADMIN_URL"] = os.environ["TEST_DATABASE_ADMIN_URL"]
