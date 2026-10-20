"""Deterministic evidence associations, never an assessment of semantic completeness.

Callers MUST supply only verified findings and resolve citation/source IDs against
their evidence registry before calling. UUID shape alone cannot establish that an
external citation exists. No provider, database, or model is called here.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from research_api.mode_reports import policy_for_mode
from research_api.schemas.generated.report_document_v1 import ReportDocumentV1

_Text = Annotated[str, Field(min_length=1, max_length=1000)]
_Section = Literal["overview", "mechanisms", "comparison", "risks", "implications"]


def _unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {label}")


class _Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    question: _Text


class _Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: UUID
    text: Annotated[str, Field(min_length=1, max_length=1200)]
    section: _Section
    citation_ids: Annotated[list[UUID], Field(alias="citationIds", min_length=1, max_length=8)]
    source_ids: Annotated[list[UUID], Field(alias="sourceIds", min_length=1, max_length=8)]
    sub_question_id: UUID = Field(alias="subQuestionId")
    # These nominations are untrusted; invalid indices (including bools) are ignored.
    requirement_indices: Annotated[list[Any], Field(alias="requirementIndices", max_length=20)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, Field(min_length=1, max_length=10000)]
    max_search_calls: Annotated[StrictInt, Field(ge=0)]
    mode: Literal["focused", "balanced", "deep"] | None = None
    requirements: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")]],
        Field(max_length=20),
    ]
    findings: Annotated[list[_Finding], Field(max_length=40)]
    questions: Annotated[list[_Question], Field(max_length=16)]
    excluded: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def relations(self) -> "_Input":
        _unique([f.id for f in self.findings], "finding IDs")
        _unique([q.id for q in self.questions], "question IDs")
        known = {q.id for q in self.questions}
        for finding in self.findings:
            if finding.sub_question_id not in known:
                raise ValueError("Unknown subQuestionId")
            _unique(finding.citation_ids, "citation links")
            _unique(finding.source_ids, "source links")
        return self


def validate_report_document(document: dict[str, Any]) -> dict[str, Any]:
    if document.get("version") == 6:
        from research_api.report_document_v6 import validate_report_document_v6

        return validate_report_document_v6(document)
    if document.get("version") == 5:
        from research_api.report_document_v5 import validate_report_document_v5

        return validate_report_document_v5(document)
    if document.get("version") == 4:
        from research_api.report_document_v4 import validate_report_document_v4

        return validate_report_document_v4(document)
    if document.get("version") == 3:
        from research_api.report_document_v3 import validate_report_document_v3

        return validate_report_document_v3(document)
    if document.get("version") == 2:
        from research_api.report_document_v2 import validate_report_document_v2

        return validate_report_document_v2(document)
    return _validate_report_document_v1(document)


def report_diagnostics(document: dict[str, Any]) -> dict[str, Any]:
    """Offline benchmark counters, keeping provenance distinct from assessment.

    These are recorded model outcomes, not human gold labels or measured quality.
    Historical V1 documents have no assessed coverage; report null, never zero.
    """
    doc = validate_report_document(document)
    return {
        "documentVersion": doc["version"],
        "assessmentVersion": doc["assessmentVersion"],
        "verifiedFindings": len(doc["findings"]),
        "provenanceOnly": {
            "requirementsLinked": sum(bool(row["claimIds"]) for row in doc["requirements"]),
            "questionsLinked": sum(bool(row["claimIds"]) for row in doc["questionCoverage"]),
        },
        "assessed": {
            "dimensionsTotal": len(doc["dimensions"]),
            "dimensionsVerifiedCovered": sum(
                row["status"] == "verified_covered" for row in doc["dimensions"]
            ),
            "requirementsEstablished": sum(
                row["outcome"] == "established" for row in doc["requirementOutcomes"]
            ),
            "requirementsUnassessed": sum(
                row["outcome"] == "not_assessed" for row in doc["requirementOutcomes"]
            ),
        }
        if doc["version"] >= 2
        else None,
        "narrative": {
            "status": doc["narrative"]["status"],
            "reason": doc["narrative"]["reason"],
            "blocks": len(doc["narrative"]["blocks"]),
            "narrativeClaims": len(doc["narrative"]["narrativeClaimIds"]),
            "proposedSentences": doc["narrative"]["proposedSentenceCount"],
            "publishedSentences": doc["narrative"]["publishedSentenceCount"],
        }
        if doc["version"] >= 4
        else None,
        "technicalResults": {
            "published": len(doc["technicalResults"]),
        }
        if doc["version"] >= 5
        else None,
        "independenceAssessed": False,
        "humanQualityAssessed": False,
    }


def _validate_report_document_v1(document: dict[str, Any]) -> dict[str, Any]:
    """Validate generated shape plus internal references; return JSON-safe aliases.

    External citation/source existence remains the caller's responsibility. JSON
    Schema cannot express cross-row relations, so enforce them after Pydantic.
    `answered` is retained in the shared shape for future independent assessment.
    """
    doc = ReportDocumentV1.model_validate(document).model_dump(mode="json", by_alias=True)
    findings = doc["findings"]
    ids = [f["id"] for f in findings]
    _unique(ids, "finding IDs")
    for key in ("sections", "requirements", "questionCoverage"):
        _unique([r["id"] for r in doc[key]], f"{key} IDs")
        for row in doc[key]:
            _unique(row["claimIds"], "claim links")
            if not set(row["claimIds"]).issubset(ids):
                raise ValueError("Dangling claim ID")
    for finding in findings:
        _unique(finding["citationIds"], "citation links")
        _unique(finding["sourceIds"], "source links")
    overview = [f["id"] for f in findings if f["section"] == "overview"] or ids[:2]
    for row in doc["sections"]:
        expected = [
            f["id"]
            for f in findings
            if (
                f["id"] in overview
                if row["id"] == "overview"
                else f["id"] not in overview and f["section"] == row["id"]
            )
        ]
        if row["claimIds"] != expected:
            raise ValueError("Invalid section placement")
    for index, row in enumerate(doc["requirements"]):
        if row["id"] != ("question" if index == 0 else f"requirement-{index}") or row["origin"] != (
            "main_question" if index == 0 else "user_requirement"
        ):
            raise ValueError("Invalid requirement identity")
        if index == 0 and (row["text"] != doc["title"] or row["claimIds"]):
            raise ValueError("Main question is unassessed")
        if index > 0 and len(row["text"]) > 500:
            raise ValueError("User requirement exceeds 500 characters")
    for key, basis in (
        ("requirements", "model_linked_verified_findings"),
        ("questionCoverage", "collection_provenance"),
    ):
        for row in doc[key]:
            linked = bool(row["claimIds"])
            if row["status"] != ("addressed" if linked else "unresolved") or row["basis"] != (
                basis if linked else "not_established"
            ):
                raise ValueError("Invalid evidence association")
    quality = doc["quality"]
    if quality["status"] == "answered":
        raise ValueError("evidence-links-v1 cannot certify answered")
    if quality["verifiedFindings"] != len(findings):
        raise ValueError("Finding count mismatch")
    if (not findings) != (quality["status"] == "insufficient_evidence"):
        raise ValueError("Invalid evidence quality")
    return doc


def build_report_document(
    *,
    question: str,
    max_search_calls: int,
    requirements: list[str],
    findings: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    excluded: int,
    mode: Literal["focused", "balanced", "deep"] | None = None,
) -> dict[str, Any]:
    """Build V1 from caller-verified findings; never infer fulfillment from links.

    Requirement indices are zero-based into explicit requirements only. Summary
    fallback uses the first two claims once, preserving their original section
    labels on findings. Ordering and IDs are stable for identical inputs.
    """
    data = _Input.model_validate(
        {
            "question": question,
            "max_search_calls": max_search_calls,
            "requirements": requirements,
            "findings": findings,
            "questions": questions,
            "excluded": excluded,
            "mode": mode,
        }
    )
    policy = policy_for_mode(data.max_search_calls, mode=data.mode)
    projected = [
        f.model_dump(mode="json", by_alias=True, exclude={"sub_question_id", "requirement_indices"})
        for f in data.findings
    ]
    overview = [f["id"] for f in projected if f["section"] == "overview"] or [
        f["id"] for f in projected[:2]
    ]
    sections = [{"id": "overview", "title": "Executive summary", "claimIds": overview}]
    for key, title in policy.sections:
        sections.append(
            {
                "id": key,
                "title": title,
                "claimIds": [
                    f["id"] for f in projected if f["section"] == key and f["id"] not in overview
                ],
            }
        )
    associated = [
        {
            "id": "question",
            "origin": "main_question",
            "text": data.question,
            "status": "unresolved",
            "claimIds": [],
            "basis": "not_established",
        }
    ]
    for index, text in enumerate(data.requirements):
        linked = [
            str(f.id)
            for f in data.findings
            if any(type(i) is int and i == index for i in f.requirement_indices)
        ]
        associated.append(
            {
                "id": f"requirement-{index + 1}",
                "origin": "user_requirement",
                "text": text,
                "status": "addressed" if linked else "unresolved",
                "claimIds": linked,
                "basis": "model_linked_verified_findings" if linked else "not_established",
            }
        )
    coverage = []
    for sub_question in data.questions:
        linked = [str(f.id) for f in data.findings if f.sub_question_id == sub_question.id]
        coverage.append(
            {
                "id": str(sub_question.id),
                "text": sub_question.question,
                "status": "addressed" if linked else "unresolved",
                "claimIds": linked,
                "basis": "collection_provenance" if linked else "not_established",
            }
        )
    return validate_report_document(
        {
            "version": 1,
            "assessmentVersion": "evidence-links-v1",
            "mode": policy.mode,
            "title": data.question,
            "sections": sections,
            "findings": projected,
            "requirements": associated,
            "questionCoverage": coverage,
            "quality": {
                "status": "partial" if projected else "insufficient_evidence",
                "reason": (
                    "Linked evidence and collection provenance are associations only. "
                    "Completeness of the main question and user requirements has not been assessed."
                    if projected
                    else "No verified findings were established. Completeness of the main question "
                    "and user requirements has not been assessed."
                ),
                "verifiedFindings": len(projected),
                "excludedFindings": data.excluded,
            },
        }
    )
