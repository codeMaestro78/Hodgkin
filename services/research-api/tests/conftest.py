"""Keep automated tests on local Docker infrastructure, never configured cloud services."""

import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = (
    "postgresql+psycopg://research_app:research_app@localhost:55432/research"
)
os.environ["DATABASE_ADMIN_URL"] = (
    "postgresql+psycopg://research_owner:research_owner@localhost:55432/research"
)
os.environ["OBJECT_STORAGE_ENDPOINT"] = "http://localhost:54566"
