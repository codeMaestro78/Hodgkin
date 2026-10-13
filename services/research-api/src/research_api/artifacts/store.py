from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from typing import Protocol

import boto3


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_ref: str
    content_hash: str
    size_bytes: int
    media_type: str


class ArtifactStore(Protocol):
    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        content: bytes,
        media_type: str,
    ) -> ArtifactRecord: ...

    async def get_for_verification(self, *, artifact_ref: str) -> bytes: ...


def artifact_identity(
    *, tenant_id: uuid.UUID, run_id: uuid.UUID, content: bytes, media_type: str
) -> ArtifactRecord:
    digest = hashlib.sha256(content).hexdigest()
    key = f"tenants/{tenant_id}/runs/{run_id}/sha256/{digest}"
    return ArtifactRecord(
        artifact_ref=key,
        content_hash=digest,
        size_bytes=len(content),
        media_type=media_type,
    )


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        content: bytes,
        media_type: str,
    ) -> ArtifactRecord:
        record = artifact_identity(
            tenant_id=tenant_id, run_id=run_id, content=content, media_type=media_type
        )
        self._objects.setdefault(record.artifact_ref, content)
        return record

    async def get_for_verification(self, *, artifact_ref: str) -> bytes:
        return self._objects[artifact_ref]


class S3ArtifactStore:
    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    async def put(
        self,
        *,
        tenant_id: uuid.UUID,
        run_id: uuid.UUID,
        content: bytes,
        media_type: str,
    ) -> ArtifactRecord:
        record = artifact_identity(
            tenant_id=tenant_id, run_id=run_id, content=content, media_type=media_type
        )
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=record.artifact_ref,
            Body=content,
            ContentType=media_type,
            Metadata={"sha256": record.content_hash},
        )
        return record

    async def get_for_verification(self, *, artifact_ref: str) -> bytes:
        response = await asyncio.to_thread(
            self._client.get_object, Bucket=self._bucket, Key=artifact_ref
        )
        return await asyncio.to_thread(response["Body"].read)
