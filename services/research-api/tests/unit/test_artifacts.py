import uuid

import pytest

from research_api.artifacts.normalization import canonicalize_url, normalize_text
from research_api.artifacts.store import InMemoryArtifactStore


def test_canonicalize_url_removes_fragment_tracking_and_default_port() -> None:
    value = "HTTPS://Example.COM:443/a//b?utm_source=x&b=2&a=1#fragment"
    assert canonicalize_url(value) == "https://example.com/a//b?b=2&a=1"


def test_canonicalize_url_rejects_non_http_protocols() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("file:///etc/passwd")


@pytest.mark.asyncio
async def test_artifacts_are_content_addressed_and_tenant_scoped() -> None:
    store = InMemoryArtifactStore()
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    first = await store.put(
        tenant_id=tenant_id,
        run_id=run_id,
        content=normalize_text("evidence\r\n").encode(),
        media_type="text/plain",
    )
    second = await store.put(
        tenant_id=tenant_id,
        run_id=run_id,
        content=b"evidence",
        media_type="text/plain",
    )
    assert first == second
    assert str(tenant_id) in first.artifact_ref
    assert await store.get_for_verification(artifact_ref=first.artifact_ref) == b"evidence"
