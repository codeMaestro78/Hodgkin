from research_api.graph.builder import PlannerOutput, SynthesisOutput


def test_openai_planner_schema_forbids_extra_properties() -> None:
    schema = PlannerOutput.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["$defs"]["PlannedQuestion"]["additionalProperties"] is False


def test_openai_synthesis_schema_requires_every_nested_property() -> None:
    schema = SynthesisOutput.model_json_schema()

    assert schema["$defs"]["ClaimDraft"]["required"] == [
        "claim",
        "citations",
        "caveats",
    ]
