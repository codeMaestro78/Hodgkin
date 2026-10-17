"""V4 report projection: an evidence-verified narrative over the immutable ledger.

The narrative only orders published findings into mode-specific blocks. Every
sentence is an exact finding with its existing citations; narrative-origin
findings passed the same exact-passage and fully supportive review gate.
"""

from copy import deepcopy
from typing import Any

from research_api.narrative_composer import NARRATIVE_LIMITS
from research_api.report_document import _unique
from research_api.report_document_v3 import validate_report_document_v3


def validate_report_document_v4(document: dict[str, Any]) -> dict[str, Any]:
    from research_api.schemas.generated.report_document_v3 import ReportDocumentV3
    from research_api.schemas.generated.report_document_v4 import ReportDocumentV4

    doc = ReportDocumentV4.model_validate(deepcopy(document)).model_dump(mode="json", by_alias=True)
    v3_keys = {field.alias or name for name, field in ReportDocumentV3.model_fields.items()}
    validate_report_document_v3(
        {
            **{key: doc[key] for key in v3_keys},
            "version": 3,
            "assessmentVersion": "provenance-conflicts-v1",
        }
    )
    narrative = doc["narrative"]
    limits = NARRATIVE_LIMITS[doc["mode"]]
    composed = narrative["status"] == "composed"
    if composed != bool(narrative["blocks"]):
        raise ValueError("Composed narrative status must match its blocks")
    if composed != (narrative["reason"] is None):
        raise ValueError("Only an uncomposed narrative records a reason")
    if len(narrative["blocks"]) > limits.max_blocks:
        raise ValueError("Narrative exceeds its mode block limit")
    if len(narrative["narrativeClaimIds"]) > limits.max_new_claims:
        raise ValueError("Narrative exceeds its mode claim limit")
    _unique(narrative["narrativeClaimIds"], "narrative claim IDs")
    findings = {finding["id"]: finding for finding in doc["findings"]}
    dimensions = {dimension["id"] for dimension in doc["dimensions"]}
    narrative_ids = set(narrative["narrativeClaimIds"])
    placed: list[str] = []
    block_keys = []
    for index, block in enumerate(narrative["blocks"]):
        if block["id"] != f"narrative-{index + 1}":
            raise ValueError("Narrative block IDs must be sequential")
        if block["role"] not in limits.roles:
            raise ValueError("Narrative role is not allowed for this mode")
        if block["role"] == "answer" and index != 0:
            raise ValueError("The answer block must open the narrative")
        if (block["role"] == "dimension") != (block["dimensionId"] is not None):
            raise ValueError("Only dimension blocks reference a dimension")
        if block["dimensionId"] is not None and block["dimensionId"] not in dimensions:
            raise ValueError("Narrative block references an unknown dimension")
        if len(block["sentences"]) > limits.max_sentences:
            raise ValueError("Narrative block exceeds its mode sentence limit")
        block_keys.append((block["role"], block["dimensionId"]))
        for sentence in block["sentences"]:
            finding = findings.get(sentence["claimId"])
            if finding is None:
                raise ValueError("Narrative sentence references an unknown finding")
            if sentence["citationIds"] != finding["citationIds"]:
                raise ValueError("Narrative citations must match the verified finding")
            if (sentence["origin"] == "narrative") != (sentence["claimId"] in narrative_ids):
                raise ValueError("Narrative sentence origin does not match its claim")
            placed.append(sentence["claimId"])
    _unique(block_keys, "narrative blocks")
    _unique(placed, "narrative findings")
    if not narrative_ids <= set(placed):
        raise ValueError("Every narrative claim must be placed in the narrative")
    if narrative["publishedSentenceCount"] != len(placed):
        raise ValueError("Published narrative count must match its sentences")
    if (
        narrative["rejectedSentenceCount"]
        != narrative["proposedSentenceCount"] - narrative["publishedSentenceCount"]
    ):
        raise ValueError("Rejected narrative count must match proposed and published counts")
    return doc


def enhance_report_document_v4(
    document: dict[str, Any], *, narrative: dict[str, Any]
) -> dict[str, Any]:
    """Extend V3 with a narrative projection; never changes the factual ledger."""
    base = validate_report_document_v3(document)
    return validate_report_document_v4(
        {
            **base,
            "version": 4,
            "assessmentVersion": "evidence-narrative-v1",
            "narrative": narrative,
        }
    )
