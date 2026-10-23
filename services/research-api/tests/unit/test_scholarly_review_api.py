import importlib.util
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from research_api.auth import Caller
from research_api.main import app
from research_api.scholarly import review_api


def test_review_routes_require_authentication():
    client = TestClient(app)
    assert client.get("/research/reviews").status_code == 401
    assert client.post("/research/reviews", json={"title": "x", "question": "y"}).status_code == 401


def test_public_artifact_creation_and_forged_text_are_rejected():
    post_paths = {route.path for route in app.routes if "POST" in getattr(route, "methods", set())}
    assert not any(path.endswith("/artifacts") and "/records/" in path for path in post_paths)
    with pytest.raises(ValueError):
        review_api.EvidenceBody.model_validate({
            "artifactId": str(uuid.uuid4()), "sourceId": "source", "claim": "claim",
            "quote": "forged", "pageNumber": 1, "start": 0, "end": 6,
            "artifactRef": "tenants/forged", "parsedText": "forged",
        })


def test_migration_protects_every_table(monkeypatch):
    path = (
        Path(__file__).parents[2]
        / "src/research_api/db/migrations/versions/0036_scholarly_reviews.py"
    )
    spec = importlib.util.spec_from_file_location("scholarly_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []

    class Operations:
        def execute(self, statement):
            statements.append(str(statement))

        def get_bind(self):
            return object()

    monkeypatch.setattr(migration, "op", Operations())
    monkeypatch.setattr("sqlalchemy.schema.Table.create", lambda *_args, **_kwargs: None)
    migration.upgrade()
    sql = "\n".join(statements)
    assert migration.down_revision == "0035"
    for model in migration.MODELS:
        table = model.__tablename__
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in sql
        assert f"ON public.{table}" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "GRANT SELECT, INSERT" in sql


@pytest.mark.asyncio
async def test_locked_review_is_scoped_to_tenant_and_owner():
    class Session:
        query = None

        async def scalar(self, query):
            self.query = query
            return None

    session = Session()
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    with pytest.raises(HTTPException) as error:
        await review_api.require_review(session, caller, uuid.uuid4(), lock=True)
    assert error.value.status_code == 404
    sql = str(session.query.compile(dialect=postgresql.dialect()))
    assert "scholarly_reviews.tenant_id" in sql
    assert "scholarly_reviews.owner_user_id" in sql
    assert "FOR UPDATE" in sql


def test_search_execution_rejects_invalid_receipt():
    with pytest.raises(ValueError):
        review_api.SearchExecution(
            search_id="s", query="q", executed_at=datetime.now(UTC),
            database="pubmed", result_record_ids=("r1", "r1"),
        )


@pytest.mark.asyncio
async def test_retrieval_requires_a_stored_artifact(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    async def fake_review(*_args, **_kwargs):
        return None

    async def fake_record(*_args):
        return SimpleNamespace(record_id="r1")

    class Result:
        calls = 0

        async def scalar(self, _query):
            self.calls += 1
            return SimpleNamespace(outcome="include") if self.calls == 2 else None

    @asynccontextmanager
    async def query_session(_caller):
        yield Result()

    monkeypatch.setattr(review_api, "owner_session", query_session)
    monkeypatch.setattr(review_api, "require_review", fake_review)
    monkeypatch.setattr(review_api, "require_record", fake_record)
    with pytest.raises(HTTPException) as error:
        await review_api.add_retrieval(
            uuid.uuid4(), "r1",
            review_api.ReceiptBody(status="retrieved", source_id="missing"), caller,
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_evidence_rechecks_stored_pdf_before_insert(monkeypatch):
    from research_api.scholarly import import_api

    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    artifact_id = uuid.uuid4()

    class Session:
        calls = 0

        async def scalar(self, _query):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(outcome="include", source_id=str(artifact_id))
            if self.calls == 2:
                return SimpleNamespace(status="retrieved", source_id=str(artifact_id))
            return SimpleNamespace(id=artifact_id, parsed_text="forged quote")

        def add(self, _row):
            raise AssertionError("unverified evidence must not be persisted")

    @asynccontextmanager
    async def fake_session(_caller):
        yield Session()

    async def fake_review(*_args, **_kwargs):
        return None

    async def fake_record(*_args):
        return SimpleNamespace(record_id="r1")

    async def reject_forged_page(_review, _artifact, _request, _caller):
        raise HTTPException(409, "stored PDF cannot be verified")

    monkeypatch.setattr(review_api, "owner_session", fake_session)
    monkeypatch.setattr(review_api, "require_review", fake_review)
    monkeypatch.setattr(review_api, "require_record", fake_record)
    monkeypatch.setattr(import_api, "verify_anchor", reject_forged_page)
    with pytest.raises(HTTPException) as error:
        await review_api.add_evidence(
            uuid.uuid4(), "r1", review_api.EvidenceBody(
                artifact_id=artifact_id, source_id=str(artifact_id), claim="finding",
                quote="forged quote", page_number=1, start=0, end=12,
            ), caller,
        )
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_evidence_requires_included_full_text(monkeypatch):
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())

    class Session:
        async def scalar(self, _query):
            return None

    @asynccontextmanager
    async def fake_session(_caller):
        yield Session()

    async def fake_review(*_args, **_kwargs):
        return None

    async def fake_record(*_args):
        return SimpleNamespace(record_id="r1")

    monkeypatch.setattr(review_api, "owner_session", fake_session)
    monkeypatch.setattr(review_api, "require_review", fake_review)
    monkeypatch.setattr(review_api, "require_record", fake_record)
    with pytest.raises(HTTPException) as error:
        await review_api.add_evidence(
            uuid.uuid4(), "r1",
            review_api.EvidenceBody(
                artifact_id=uuid.uuid4(), source_id="missing", claim="finding", quote="quote",
                page_number=1, start=0, end=5,
            ), caller,
        )
    assert error.value.status_code == 409
