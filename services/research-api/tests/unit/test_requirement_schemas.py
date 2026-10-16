"""Admission and strict model schemas reject invalid briefs before paid dispatch."""

import pytest
from pydantic import ValidationError

from research_api.graph.builder import (
    BalancedRequirementAssertions,
    DeepRequirementAssertions,
    FocusedRequirementAssertions,
)
from research_api.schemas.generated.create_research_run_request import CreateResearchRunRequest


@pytest.mark.parametrize(
    "model,limit",
    [
        (FocusedRequirementAssertions, 12),
        (BalancedRequirementAssertions, 24),
        (DeepRequirementAssertions, 40),
    ],
)
def test_requirement_writer_schema_requires_every_property(model, limit):
    schema = model.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["claims"]["maxItems"] == limit
    assertion = schema["$defs"]["RequirementAssertion"]
    assert assertion["additionalProperties"] is False
    assert set(assertion["required"]) == set(assertion["properties"])
    assert "requirement_indices" in assertion["required"]
    assert "figures" in assertion["required"]
    assert all("default" not in prop for prop in assertion["properties"].values())
    figure = schema["$defs"]["FigureDraft"]
    assert figure["additionalProperties"] is False
    assert set(figure["required"]) == set(figure["properties"])

    citation = schema["$defs"]["CitationDraft"]
    assert set(citation["required"]) == set(citation["properties"])


def test_drafts_recorded_before_figures_still_parse():
    parsed = DeepRequirementAssertions.model_validate_json(
        '{"claims":[{"claim":"x","citations":[],"caveats":[],"section":"risks",'
        '"requirement_indices":[]}]}'
    )
    assert parsed.claims[0].figures == []


@pytest.mark.parametrize("requirements", [[""], ["   "], ["x" * 501], ["x"] * 21])
def test_invalid_requirements_are_rejected_at_the_api_boundary(requirements):
    with pytest.raises(ValidationError):
        CreateResearchRunRequest.model_validate(
            {
                "question": "Compare research approaches",
                "reportRequirements": requirements,
            }
        )
