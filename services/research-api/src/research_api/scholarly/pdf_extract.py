"""Bounded PDF text extraction. Page text is a locator, never claim verification."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import Protocol

from botocore.exceptions import BotoCoreError, ClientError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from research_api.artifacts.store import ArtifactStore, S3ArtifactStore
from research_api.auth import Caller
from research_api.config import get_settings

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_PAGE_CHARS = 100_000
MAX_TOTAL_CHARS = 1_000_000


def review_artifact_store() -> ArtifactStore:
    settings = get_settings()
    return S3ArtifactStore(
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        bucket=settings.OBJECT_STORAGE_BUCKET,
        access_key=settings.OBJECT_STORAGE_ACCESS_KEY.get_secret_value(),
        secret_key=settings.OBJECT_STORAGE_SECRET_KEY.get_secret_value(),
        region=settings.OBJECT_STORAGE_REGION,
    )


class PDFExtractionError(ValueError):
    pass


class PDFSourceUnavailable(RuntimeError):
    pass


class PDFSourceMismatch(ValueError):
    pass


class PDFQuoteMismatch(ValueError):
    pass


class ArtifactForVerification(Protocol):
    tenant_id: uuid.UUID
    owner_user_id: uuid.UUID
    review_id: uuid.UUID
    artifact_ref: str
    content_hash: str
    parsed_text: str
    page_anchors: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int  # One based, matching a PDF viewer.
    text: str  # Exact text returned by the extractor; no fabricated quotations.


@dataclass(frozen=True, slots=True)
class VerifiedPageQuote:
    page_anchor: str
    start: int
    end: int
    quote: str


def assemble_pages(pages: tuple[PageText, ...]) -> tuple[str, list[dict[str, int | str]]]:
    parts: list[str] = []
    anchors: list[dict[str, int | str]] = []
    offset = 0
    for page in pages:
        if parts:
            parts.append("\n\n")
            offset += 2
        start = offset
        parts.append(page.text)
        offset += len(page.text)
        anchors.append(
            {
                "anchor": f"page:{page.page_number}",
                "page_number": page.page_number,
                "start": start,
                "end": offset,
            }
        )
    return "".join(parts), anchors


def verify_quote_anchor(
    parsed_text: str,
    page_anchors: Sequence[Mapping[str, object]],
    *,
    page_number: int,
    start: int,
    end: int,
    quote: str,
) -> bool:
    """Check an exact span inside one page; no semantic support is inferred."""
    if start >= end or parsed_text[start:end] != quote:
        return False
    for anchor in page_anchors:
        lower, upper = anchor.get("start"), anchor.get("end")
        if (
            anchor.get("page_number") == page_number
            and isinstance(lower, int)
            and not isinstance(lower, bool)
            and isinstance(upper, int)
            and not isinstance(upper, bool)
            and lower <= start
            and end <= upper
        ):
            return True
    return False


async def verify_stored_pdf_quote(
    store: ArtifactStore,
    *,
    caller: Caller,
    review_id: uuid.UUID,
    artifact: ArtifactForVerification,
    page_anchor: str,
    quote: str,
    start: int | None = None,
    end: int | None = None,
) -> VerifiedPageQuote:
    """Verify ownership, source bytes, extracted text, and quote location.

    The caller must also load the artifact through its owner-scoped DB query.
    This establishes a text locator, not that the quote supports a claim.
    """
    actual_text, actual_anchors = await verified_stored_pdf_text(
        store, caller=caller, review_id=review_id, artifact=artifact
    )
    page = next((item for item in actual_anchors if item["anchor"] == page_anchor), None)
    if page is None or not quote:
        raise PDFQuoteMismatch("quote has no inspected page anchor")
    lower, upper = int(page["start"]), int(page["end"])
    if start is None and end is None:
        relative = actual_text[lower:upper].find(quote)
        if relative < 0:
            raise PDFQuoteMismatch("quote does not occur verbatim on the selected page")
        start, end = lower + relative, lower + relative + len(quote)
    if (
        start is None
        or end is None
        or not verify_quote_anchor(
            actual_text,
            actual_anchors,
            page_number=int(page["page_number"]),
            start=start,
            end=end,
            quote=quote,
        )
    ):
        raise PDFQuoteMismatch("quote is not an exact span on the selected page")
    return VerifiedPageQuote(page_anchor=page_anchor, start=start, end=end, quote=quote)


async def verified_stored_pdf_text(
    store: ArtifactStore,
    *,
    caller: Caller,
    review_id: uuid.UUID,
    artifact: ArtifactForVerification,
) -> tuple[str, list[dict[str, int | str]]]:
    """Read an owned PDF and verify saved extraction against the stored bytes."""
    if (
        artifact.tenant_id != caller.tenant_id
        or artifact.owner_user_id != caller.user_id
        or artifact.review_id != review_id
    ):
        raise PDFSourceMismatch("artifact is outside the caller's review")
    expected_ref = f"tenants/{caller.tenant_id}/runs/{review_id}/sha256/{artifact.content_hash}"
    if artifact.artifact_ref != expected_ref:
        raise PDFSourceMismatch("artifact identity is invalid")
    try:
        raw = await store.get_for_verification(artifact_ref=expected_ref)
    except (KeyError, OSError, BotoCoreError, ClientError) as exc:
        raise PDFSourceUnavailable("stored PDF could not be read") from exc
    if len(raw) > MAX_PDF_BYTES or hashlib.sha256(raw).hexdigest() != artifact.content_hash:
        raise PDFSourceMismatch("stored PDF failed hash or size verification")
    try:
        pages = await asyncio.to_thread(extract_pdf_text, raw)
    except PDFExtractionError as exc:
        raise PDFSourceMismatch("stored PDF cannot be inspected") from exc
    actual_text, actual_anchors = assemble_pages(pages)
    if actual_text != artifact.parsed_text or actual_anchors != artifact.page_anchors:
        raise PDFSourceMismatch("saved page text differs from the stored PDF")
    return actual_text, actual_anchors


def extract_pdf_text(content: bytes) -> tuple[PageText, ...]:
    if not content or len(content) > MAX_PDF_BYTES:
        raise PDFExtractionError("PDF size must be between 1 byte and 10 MiB")
    if not content.startswith(b"%PDF-"):
        raise PDFExtractionError("file is not a PDF")
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted:
            raise PDFExtractionError("encrypted PDFs are not supported")
        count = len(reader.pages)
        if count < 1 or count > MAX_PDF_PAGES:
            raise PDFExtractionError("PDF must have 1 to 100 pages")
        pages: list[PageText] = []
        total_chars = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if len(text) > MAX_PAGE_CHARS:
                raise PDFExtractionError("PDF page text exceeds extraction limit")
            total_chars += len(text)
            if total_chars > MAX_TOTAL_CHARS:
                raise PDFExtractionError("PDF text exceeds extraction limit")
            if text.strip():
                pages.append(PageText(page_number=number, text=text))
        if not pages:
            raise PDFExtractionError("PDF has no extractable text")
        return tuple(pages)
    except PDFExtractionError:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, OSError, IndexError) as exc:
        raise PDFExtractionError("PDF cannot be parsed") from exc
