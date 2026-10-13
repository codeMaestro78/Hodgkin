from __future__ import annotations

import os
import uuid

import pytest

from research_api.artifacts.store import S3ArtifactStore

pytestmark = pytest.mark.integration


async def test_s3_round_trip_uses_tenant_scoped_content_address() -> None:
    store = S3ArtifactStore(
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT", "http://localhost:54566"),
        bucket=os.getenv("OBJECT_STORAGE_BUCKET", "research-artifacts"),
        access_key="test",
        secret_key="test",  # noqa: S106 - LocalStack's documented local credential
        region="us-east-1",
    )
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    content = b"normalized evidence"

    record = await store.put(
        tenant_id=tenant_id,
        run_id=run_id,
        content=content,
        media_type="text/plain",
    )

    assert record.artifact_ref.startswith(f"tenants/{tenant_id}/runs/{run_id}/sha256/")
    assert await store.get_for_verification(artifact_ref=record.artifact_ref) == content
