"""Report V3 pins report-level provenance and conflict references."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from research_api.report_document import validate_report_document


def uid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def test_migration_only_expands_immutable_report_document_allowlist():
    path = (
        Path(__file__).resolve().parents[2]
        / "src/research_api/db/migrations/versions/0016_report_provenance_conflicts.py"
    )
    spec = importlib.util.spec_from_file_location("report_v3_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0016" and module.down_revision == "0015"
    from unittest.mock import patch

    with patch.object(module, "op") as operation:
        module.upgrade()
    sql = "\n".join(call.args[0] for call in operation.execute.call_args_list)
    assert "IN ('1', '2', '3')" in sql
    assert "octet_length(document::text) <= 524288" in sql
    assert "DROP TRIGGER" not in sql and "CREATE TRIGGER" not in sql
    with pytest.raises(RuntimeError, match="preserves published report V3"):
        module.downgrade()


@pytest.fixture
def v3() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[4]
        / "packages/contracts/fixtures/valid/report-document-v1.json"
    )
    base = json.loads(path.read_text())
    claim = base["findings"][0]["id"]
    source_a = base["findings"][0]["sourceIds"][0]
    source_b = uid(101)
    from_source, to_source = sorted((source_a, source_b))
    base.update(
        {
            "version": 3,
            "assessmentVersion": "provenance-conflicts-v1",
            "runId": uid(400),
            "planId": uid(401),
            "assessmentId": uid(402),
            "modePolicyVersion": "research-mode-policy-v1",
            "dimensions": [
                {
                    "id": uid(500),
                    "label": "Operational recovery",
                    "requirementIds": ["question", "requirement-1"],
                    "status": "verified_covered",
                    "claimIds": [claim],
                    "reason": "Reviewed evidence was recorded.",
                    "basis": "criterion-review-v1",
                    "criteria": [
                        {
                            "id": uid(600),
                            "outcome": "met",
                            "claimIds": [claim],
                            "basis": "criterion-review-v1",
                            "reason": "Reviewed support was recorded.",
                        }
                    ],
                }
            ],
            "requirementOutcomes": [
                {
                    "id": "question",
                    "outcome": "established",
                    "dimensionIds": [uid(500)],
                    "claimIds": [claim],
                    "reason": "The planned criterion was established.",
                },
                {
                    "id": "requirement-1",
                    "outcome": "established",
                    "dimensionIds": [uid(500)],
                    "claimIds": [claim],
                    "reason": "The requested criterion was established.",
                },
            ],
            "comparisons": [],
            "sourceIndependence": {
                "status": "unknown",
                "reason": "Observed source relationships do not establish independence.",
            },
            "sourceRelationships": [
                {
                    "fromSourceId": from_source,
                    "toSourceId": to_source,
                    "kind": "same_work",
                    "confidence": "observed",
                    "basis": "observed_doi_match",
                    "identifier": "doi:10.1234/example",
                }
            ],
            "conflicts": [
                {
                    "id": uid(700),
                    "dimensionId": uid(500),
                    "criterionIds": [uid(600)],
                    "claimIds": [claim, uid(8)],
                    "status": "potential",
                    "basis": "criterion-review-v1",
                    "reason": "Independent criterion review nominated a potential disagreement.",
                }
            ],
        }
    )
    # Add the second verified finding referenced by the potential conflict.
    second = deepcopy(base["findings"][0])
    second.update(
        id=uid(8),
        text="A second verified statement that may disagree.",
        sourceIds=[source_b],
        citationIds=[uid(9)],
    )
    base["findings"].append(second)
    base["sections"][0]["claimIds"].append(second["id"])
    base["dimensions"][0]["claimIds"].append(second["id"])
    base["dimensions"][0]["criteria"][0]["claimIds"].append(second["id"])
    for outcome in base["requirementOutcomes"]:
        outcome["claimIds"].append(second["id"])
    base["quality"]["verifiedFindings"] = len(base["findings"])
    return base


def test_v3_accepts_only_report_scoped_provenance_and_assessed_conflicts(v3):
    assert validate_report_document(v3) == v3


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("sourceRelationships", 0, "toSourceId"), uid(99)),
        (("sourceRelationships", 0, "fromSourceId"), "00000000-0000-4000-8000-000000000000"),
        (("sourceRelationships", 0, "basis"), "publisher_guess"),
        (("sourceRelationships", 0, "confidence"), "inferred"),
        (("sourceRelationships", 0, "identifier"), "doi:not-a-doi"),
        (("conflicts", 0, "claimIds"), [uid(99), uid(8)]),
        (("conflicts", 0, "dimensionId"), uid(99)),
        (("conflicts", 0, "criterionIds"), [uid(99)]),
        (("conflicts", 0, "status"), "confirmed"),
    ],
)
def test_v3_rejects_unscoped_or_overstated_records(v3, path, value):
    target = v3
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_report_document(v3)


def test_v1_and_v2_dispatch_remains_unchanged(v3):
    v2 = deepcopy(v3)
    v2.update(version=2, assessmentVersion="coverage-ledger-v1")
    for key in ("sourceRelationships", "conflicts"):
        del v2[key]
    # V2 is separately covered by its existing schema and reader tests; the
    # V3-only additions must never be retrofitted into historical documents.
    assert validate_report_document(v2)["version"] == 2
