import json
from pathlib import Path

FIXTURE = Path(__file__).parents[2] / "evaluation/retrieval/v1"


def test_draft_retrieval_benchmark_has_explicit_diverse_requirements_without_gold_labels():
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    cases = [
        json.loads(line)
        for line in (FIXTURE / "cases.jsonl").read_text().splitlines()
        if line.strip()
    ]

    assert manifest["status"] == "draft_questions_only"
    assert manifest["candidatePoolsFrozen"] is False
    assert manifest["independentReviewers"] == 0
    assert len(cases) == manifest["questionCount"] == 20
    assert len({case["id"] for case in cases}) == len(cases)
    assert len({case["domain"] for case in cases}) >= 15
    assert {case["academicIndexExpected"] for case in cases} == {True, False}
    assert all(len(case["requirements"]) >= 2 for case in cases)
    assert all(
        requirement["id"] and requirement["text"].strip()
        for case in cases
        for requirement in case["requirements"]
    )
    assert not any("gold" in case or "label" in case for case in cases)


def test_retrieval_rubric_requires_blinding_and_keeps_corpus_recall_claim_bounded():
    rubric = (FIXTURE / "rubric.md").read_text()

    assert "Hide provider, retrieval" in rubric
    assert "Two reviewers" in rubric
    assert "not corpus recall" in rubric
    assert "A live paid evaluation requires explicit" in rubric
    assert "authorization; this draft authorizes no provider calls." in rubric
