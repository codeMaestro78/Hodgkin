from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO

import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from research_api.artifacts.store import ArtifactRecord, InMemoryArtifactStore
from research_api.auth import Caller
from research_api.scholarly.import_api import ImportResponse, _verified_put
from research_api.scholarly.pdf_extract import (
    MAX_PDF_BYTES,
    PageText,
    PDFExtractionError,
    PDFQuoteMismatch,
    PDFSourceMismatch,
    assemble_pages,
    extract_pdf_text,
    verify_quote_anchor,
    verify_stored_pdf_quote,
)


def test_page_offsets_bind_quote_to_its_page() -> None:
    text, anchors = assemble_pages((PageText(1, "Alpha finding."), PageText(3, "Beta finding.")))
    assert text == "Alpha finding.\n\nBeta finding."
    assert [item["page_number"] for item in anchors] == [1, 3]
    assert verify_quote_anchor(
        text, anchors, page_number=3, start=16, end=29, quote="Beta finding."
    )
    assert not verify_quote_anchor(
        text, anchors, page_number=1, start=16, end=29, quote="Beta finding."
    )
    assert not verify_quote_anchor(
        text, anchors, page_number=3, start=12, end=18, quote=text[12:18]
    )
    assert not verify_quote_anchor(
        text, anchors, page_number=3, start=16, end=29, quote="BETA finding."
    )


def test_public_import_response_excludes_storage_path_and_full_text() -> None:
    response = ImportResponse(
        review_id=uuid.uuid4(),
        record_id="r1",
        doi=None,
        title="Paper",
        evidence_status="page_text_locator",
        source_artifact_id=uuid.uuid4(),
        page_numbers=[1],
    ).model_dump(by_alias=True)
    assert response["pageNumbers"] == [1]
    assert "artifactRef" not in response
    assert "parsedText" not in response


def test_pdf_rejects_non_pdf_and_oversize() -> None:
    with pytest.raises(PDFExtractionError, match="not a PDF"):
        extract_pdf_text(b"hello")
    with pytest.raises(PDFExtractionError, match="10 MiB"):
        extract_pdf_text(b"%PDF-" + b"x" * MAX_PDF_BYTES)


def _sample_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    resources = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Resources")] = resources
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 250 Td (Observed result) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extractor_returns_one_based_page_text() -> None:
    pages = extract_pdf_text(_sample_pdf())
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Observed result" in pages[0].text


@pytest.mark.asyncio
async def test_stored_quote_checks_owner_hash_page_and_exact_text() -> None:
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    review_id = uuid.uuid4()
    store = InMemoryArtifactStore()
    raw = _sample_pdf()
    stored = await store.put(
        tenant_id=caller.tenant_id,
        run_id=review_id,
        content=raw,
        media_type="application/pdf",
    )
    parsed, anchors = assemble_pages(extract_pdf_text(raw))

    @dataclass
    class Artifact:
        tenant_id: uuid.UUID
        owner_user_id: uuid.UUID
        review_id: uuid.UUID
        artifact_ref: str
        content_hash: str
        parsed_text: str
        page_anchors: list[dict[str, object]]

    artifact = Artifact(
        caller.tenant_id,
        caller.user_id,
        review_id,
        stored.artifact_ref,
        stored.content_hash,
        parsed,
        anchors,
    )
    valid = await verify_stored_pdf_quote(
        store,
        caller=caller,
        review_id=review_id,
        artifact=artifact,
        page_anchor="page:1",
        quote="Observed result",
    )
    assert parsed[valid.start : valid.end] == "Observed result"
    with pytest.raises(PDFQuoteMismatch):
        await verify_stored_pdf_quote(
            store,
            caller=caller,
            review_id=review_id,
            artifact=artifact,
            page_anchor="page:2",
            quote="Observed result",
        )
    artifact.parsed_text = "client fabricated text"
    with pytest.raises(PDFSourceMismatch):
        await verify_stored_pdf_quote(
            store,
            caller=caller,
            review_id=review_id,
            artifact=artifact,
            page_anchor="page:1",
            quote="client fabricated text",
        )
    artifact.parsed_text = parsed
    artifact.owner_user_id = uuid.uuid4()
    with pytest.raises(PDFSourceMismatch):
        await verify_stored_pdf_quote(
            store,
            caller=caller,
            review_id=review_id,
            artifact=artifact,
            page_anchor="page:1",
            quote="Observed result",
        )


@pytest.mark.asyncio
async def test_store_readback_is_verified() -> None:
    caller = Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4())
    review_id = uuid.uuid4()
    data = b"%PDF-test"
    record = await _verified_put(
        InMemoryArtifactStore(),
        caller=caller,
        review_id=review_id,
        content=data,
        media_type="application/pdf",
    )
    assert record.content_hash
    assert f"/runs/{review_id}/" in record.artifact_ref


@pytest.mark.asyncio
async def test_store_cannot_substitute_another_artifact() -> None:
    class WrongStore(InMemoryArtifactStore):
        async def put(self, **kwargs: object) -> ArtifactRecord:
            return ArtifactRecord(
                artifact_ref="tenants/elsewhere/runs/elsewhere/sha256/bad",
                content_hash="bad",
                size_bytes=3,
                media_type="application/pdf",
            )

    with pytest.raises(HTTPException) as error:
        await _verified_put(
            WrongStore(),
            caller=Caller(tenant_id=uuid.uuid4(), user_id=uuid.uuid4()),
            review_id=uuid.uuid4(),
            content=b"abc",
            media_type="application/pdf",
        )
    assert error.value.status_code == 503
