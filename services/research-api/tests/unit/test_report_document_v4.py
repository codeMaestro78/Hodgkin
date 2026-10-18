"""Report V4 orders exact verified findings; it cannot add or alter facts."""

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from research_api.mode_composer import compose_report
from research_api.report_document import report_diagnostics, validate_report_document
from research_api.report_document_v4 import enhance_report_document_v4
from tests.unit.test_report_document_v3 import uid
from tests.unit.test_report_document_v3 import v3 as v3  # noqa: F401 -- pytest fixture import

NARRATIVE_CLAIM = uid(900)


def test_migration_only_adds_v4_to_immutable_report_allowlist():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0017_report_evidence_narrative.py"
    )
    spec = importlib.util.spec_from_file_location("report_v4_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0017" and module.down_revision == "0016"
    with patch.object(module, "op") as operation:
        module.upgrade()
    sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    assert "IN ('1', '2', '3', '4')" in sql
    assert "octet_length(document::text) <= 524288" in sql
    assert "DROP TRIGGER" not in sql and "CREATE TRIGGER" not in sql
    with pytest.raises(RuntimeError, match="preserves published report V4"):
        module.downgrade()


@pytest.fixture
def v4(v3: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    doc = deepcopy(v3)
    narrative_finding = deepcopy(doc["findings"][0])
    narrative_finding.update(
        id=NARRATIVE_CLAIM,
        text="A verified explanatory statement from the same passage.",
        section="risks",
        citationIds=[uid(901)],
    )
    doc["findings"].append(narrative_finding)
    doc["sections"][3]["claimIds"].append(NARRATIVE_CLAIM)
    doc["quality"]["verifiedFindings"] = len(doc["findings"])
    first, second = doc["findings"][0], doc["findings"][1]
    return enhance_report_document_v4(
        doc,
        narrative={
            "basis": "narrative-composition-v1",
            "status": "composed",
            "reason": None,
            "blocks": [
                {
                    "id": "narrative-1",
                    "role": "answer",
                    "dimensionId": None,
                    "sentences": [
                        {
                            "claimId": first["id"],
                            "citationIds": first["citationIds"],
                            "origin": "ledger",
                        }
                    ],
                },
                {
                    "id": "narrative-2",
                    "role": "tradeoffs",
                    "dimensionId": None,
                    "sentences": [
                        {
                            "claimId": NARRATIVE_CLAIM,
                            "citationIds": [uid(901)],
                            "origin": "narrative",
                        },
                        {
                            "claimId": second["id"],
                            "citationIds": second["citationIds"],
                            "origin": "ledger",
                        },
                    ],
                },
            ],
            "narrativeClaimIds": [NARRATIVE_CLAIM],
            "proposedSentenceCount": 5,
            "publishedSentenceCount": 3,
            "rejectedSentenceCount": 2,
        },
    )


def test_v4_accepts_a_narrative_of_exact_verified_findings(v4):
    assert validate_report_document(v4) == v4
    diagnostic = report_diagnostics(v4)
    assert diagnostic["documentVersion"] == 4
    assert diagnostic["assessed"]["dimensionsTotal"] == 1
    assert diagnostic["narrative"] == {
        "status": "composed",
        "reason": None,
        "blocks": 2,
        "narrativeClaims": 1,
        "proposedSentences": 5,
        "publishedSentences": 3,
    }


def mutate(doc, path, value):
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("narrative", "blocks", 0, "sentences", 0, "claimId"), uid(999)),
        (("narrative", "blocks", 0, "sentences", 0, "citationIds"), [uid(901)]),
        (("narrative", "blocks", 0, "sentences", 0, "origin"), "narrative"),
        (("narrative", "blocks", 1, "sentences", 0, "origin"), "ledger"),
        (("narrative", "blocks", 1, "sentences", 1, "claimId"), uid(1)),
        (("narrative", "blocks", 0, "id"), "narrative-2"),
        (("narrative", "blocks", 1, "role"), "answer"),
        (("narrative", "blocks", 0, "dimensionId"), uid(500)),
        (("narrative", "blocks", 1, "role"), "dimension"),
        (("narrative", "blocks", 1, "role"), "invented"),
        (("narrative", "status"), "not_composed"),
        (("narrative", "reason"), "composition_failed"),
        (("narrative", "narrativeClaimIds"), [NARRATIVE_CLAIM, NARRATIVE_CLAIM]),
        (("narrative", "narrativeClaimIds"), [NARRATIVE_CLAIM, uid(1)]),
        (("narrative", "publishedSentenceCount"), 2),
        (("narrative", "rejectedSentenceCount"), 1),
        (("narrative", "basis"), "free-text-v1"),
    ],
)
def test_v4_rejects_dangling_altered_or_misattributed_narrative(v4, path, value):
    mutate(v4, path, value)
    with pytest.raises(ValueError):
        validate_report_document(v4)


def test_v4_rejects_roles_outside_the_mode_and_extra_text(v4):
    focused = deepcopy(v4)
    focused["mode"] = "focused"
    focused["narrative"]["blocks"][1]["role"] = "synthesis"
    with pytest.raises(ValueError):
        validate_report_document(focused)
    prose = deepcopy(v4)
    prose["narrative"]["blocks"][0]["text"] = "An unverified transition."
    with pytest.raises(ValueError):
        validate_report_document(prose)


def test_uncomposed_v4_keeps_ledger_and_explains_the_reason(v3):  # noqa: F811
    doc = enhance_report_document_v4(
        v3,
        narrative={
            "basis": "narrative-composition-v1",
            "status": "not_composed",
            "reason": "insufficient_time",
            "blocks": [],
            "narrativeClaimIds": [],
            "proposedSentenceCount": 0,
            "publishedSentenceCount": 0,
            "rejectedSentenceCount": 0,
        },
    )
    sources = sorted({source for finding in doc["findings"] for source in finding["sourceIds"]})
    markdown = compose_report(
        doc, sources=[(source, "Source", "https://example.org") for source in sources]
    )
    assert "Narrative composition was not applied" in markdown
    assert "## Executive findings" in markdown
    for finding in doc["findings"]:
        assert markdown.count(finding["text"]) >= 1


def test_composed_v4_renders_exact_findings_under_fixed_headings(v4):
    sources = sorted({source for finding in v4["findings"] for source in finding["sourceIds"]})
    markdown = compose_report(
        v4, sources=[(source, "Source", "https://example.org") for source in sources]
    )
    assert markdown.index("## Executive answer") < markdown.index("## Trade-offs and caveats")
    assert "## Executive findings" not in markdown
    assert "## Additional verified findings" not in markdown
    for finding in v4["findings"]:
        assert finding["text"] in markdown
    assert "Narrative composition published 3 of 5 proposed sentences" in markdown
    # Conflicts remain visible as potential, unresolved disagreements.
    assert "## Potential evidence disagreements" in markdown
    assert markdown == compose_report(
        v4, sources=[(source, "Source", "https://example.org") for source in sources]
    )


def test_composed_v4_places_unordered_findings_after_the_narrative(v4):
    v4["narrative"]["blocks"] = v4["narrative"]["blocks"][1:]
    v4["narrative"]["blocks"][0]["id"] = "narrative-1"
    v4["narrative"]["publishedSentenceCount"] = 2
    v4["narrative"]["rejectedSentenceCount"] = 3
    sources = sorted({source for finding in v4["findings"] for source in finding["sourceIds"]})
    markdown = compose_report(
        v4, sources=[(source, "Source", "https://example.org") for source in sources]
    )
    assert markdown.index("## Trade-offs and caveats") < markdown.index(
        "## Additional verified findings"
    )
    assert v4["findings"][0]["text"] in markdown
