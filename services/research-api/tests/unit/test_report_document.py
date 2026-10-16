"""Pure report domain regressions: no infrastructure or provider calls."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

from research_api.report_document import build_report_document, validate_report_document
from research_api.schemas.generated.report_document_v1 import ReportDocumentV1


def uid(number):
    return str(UUID(int=(4 << 76) | (2 << 62) | number))


def finding(number=1, section="mechanisms", indices=None):
    return {
        "id": uid(number),
        "text": f"Verified statement {number}.",
        "section": section,
        "citationIds": [uid(100 + number)],
        "sourceIds": [uid(200 + number)],
        "subQuestionId": uid(300),
        "requirementIndices": [] if indices is None else indices,
    }


def build(**overrides):
    args = {
        "question": "Compare approaches",
        "max_search_calls": 6,
        "requirements": [],
        "findings": [],
        "questions": [{"id": uid(300), "question": "How do they work?"}],
        "excluded": 2,
    }
    args.update(overrides)
    return build_report_document(**args)


def test_empty_report_keeps_main_question_and_unresolved_coverage():
    doc = build(requirements=["Assess risk"])
    assert doc["quality"]["status"] == "insufficient_evidence"
    assert doc["quality"]["excludedFindings"] == 2
    assert doc["requirements"][0] == {
        "id": "question",
        "origin": "main_question",
        "text": "Compare approaches",
        "status": "unresolved",
        "claimIds": [],
        "basis": "not_established",
    }
    assert all(row["status"] == "unresolved" for row in doc["requirements"])
    assert doc["questionCoverage"][0]["basis"] == "not_established"
    assert all(not s["claimIds"] for s in doc["sections"])


def test_builder_matches_shared_typescript_contract_fixture():
    fixture = (
        Path(__file__).parents[4] / "packages/contracts/fixtures/valid/report-document-v1.json"
    )
    expected = json.loads(fixture.read_text())
    f = expected["findings"][0]
    q = expected["questionCoverage"][0]
    actual = build(
        max_search_calls=20,
        requirements=["Assess costs"],
        questions=[{"id": q["id"], "question": q["text"]}],
        findings=[{**f, "subQuestionId": q["id"], "requirementIndices": [0]}],
    )
    assert actual == expected


@pytest.mark.parametrize(
    "calls,mode",
    [(0, "focused"), (6, "focused"), (7, "balanced"), (12, "balanced"), (13, "deep"), (20, "deep")],
)
@pytest.mark.parametrize("complete", [False, True])
def test_sparse_and_full_mode_reports_never_certify_completeness(calls, mode, complete):
    sections = ["overview", "mechanisms", "comparison", "risks", "implications"]
    inputs = [finding(i + 1, key) for i, key in enumerate(sections if complete else sections[:1])]
    doc = build(max_search_calls=calls, findings=inputs)
    assert doc["mode"] == mode
    assert doc["quality"]["status"] == "partial"
    assert "not been assessed" in doc["quality"]["reason"]
    assert doc["questionCoverage"][0]["status"] == "addressed"
    assert doc["requirements"][0]["status"] == "unresolved"
    ReportDocumentV1.model_validate(doc)


def test_requirement_links_are_associations_and_invalid_nominations_are_ignored():
    doc = build(
        requirements=["Assess risk", "Assess costs"],
        findings=[
            finding(indices=[0, 0, -1, 20, "1", True, 1.0, None]),
        ],
    )
    assert doc["requirements"][1]["claimIds"] == [uid(1)]
    assert doc["requirements"][1]["basis"] == "model_linked_verified_findings"
    assert doc["requirements"][2]["status"] == "unresolved"
    assert doc["requirements"][0]["claimIds"] == []
    assert doc["quality"]["status"] == "partial"


def test_summary_fallback_preserves_every_claim_exactly_once_and_input_labels():
    inputs = [finding(1), finding(2, "comparison"), finding(3, "risks"), finding(4)]
    before = deepcopy(inputs)
    doc = build(findings=inputs)
    assert doc["sections"][0]["claimIds"] == [uid(1), uid(2)]
    assert doc["sections"][1]["claimIds"] == [uid(4)]
    placed = [id_ for row in doc["sections"] for id_ in row["claimIds"]]
    assert sorted(placed) == sorted(f["id"] for f in inputs)
    assert inputs == before
    assert doc["findings"][0]["section"] == "mechanisms"
    assert "requirementIndices" not in doc["findings"][0]
    assert "subQuestionId" not in doc["findings"][0]
    assert doc == build(findings=inputs)


def test_explicit_overview_prevents_fallback_and_never_drops_other_claims():
    doc = build(findings=[finding(1), finding(2, "overview"), finding(3)])
    assert doc["sections"][0]["claimIds"] == [uid(2)]
    assert doc["sections"][1]["claimIds"] == [uid(1), uid(3)]


def test_api_length_bounds_and_twenty_explicit_requirements():
    doc = build(question="Q" * 10000, requirements=["R" * 500] * 20)
    assert len(doc["requirements"]) == 21
    assert len(doc["requirements"][0]["text"]) == 10000
    assert doc["title"] == "Q" * 10000


@pytest.mark.parametrize(
    "overrides",
    [
        {"question": "Q" * 10001},
        {"requirements": ["R" * 501]},
        {"requirements": ["R"] * 21},
        {"findings": [finding(i) for i in range(41)]},
        {"questions": [{"id": uid(300 + i), "question": "Q"} for i in range(17)]},
        {"questions": [{"id": uid(300), "question": "Q" * 1001}]},
        {"findings": [finding(), finding()]},
        {"questions": [{"id": uid(300), "question": "Q"}] * 2},
        {"questions": [], "findings": [finding()]},
        {"findings": [{**finding(), "id": "bogus"}]},
        {"findings": [{**finding(), "citationIds": []}]},
        {"findings": [{**finding(), "citationIds": [uid(101), uid(101)]}]},
        {"findings": [{**finding(), "sourceIds": [uid(201), uid(201)]}]},
        {"findings": [{**finding(), "text": "x" * 1201}]},
        {"findings": [{**finding(), "body": "raw source body"}]},
        {"excluded": -1},
        {"max_search_calls": True},
    ],
)
def test_invalid_inputs_fail_before_projection(overrides):
    with pytest.raises(ValueError):
        build(**overrides)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["sections"][0]["claimIds"].append(uid(999)),
        lambda d: d["sections"][0]["claimIds"].append(uid(1)),
        lambda d: d["sections"][0]["claimIds"].clear(),
        lambda d: d["sections"][1].update(id="overview"),
        lambda d: d["findings"].append(deepcopy(d["findings"][0])),
        lambda d: d["requirements"][0].update(claimIds=[uid(1)]),
        lambda d: d["requirements"][0].update(origin="user_requirement"),
        lambda d: d["questionCoverage"][0].update(basis="not_established"),
        lambda d: d["quality"].update(status="answered"),
        lambda d: d["quality"].update(status="insufficient_evidence"),
        lambda d: d["quality"].update(verifiedFindings=0),
        lambda d: d.update(rawPageContent="body"),
    ],
)
def test_document_validation_rejects_dangling_links_and_false_assessments(mutation):
    doc = build(findings=[finding()])
    mutation(doc)
    with pytest.raises(ValueError):
        validate_report_document(doc)
