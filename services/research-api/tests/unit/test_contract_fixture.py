import json
from pathlib import Path

from pydantic import ValidationError

from research_api.schemas.generated.research_state import ResearchState


def test_shared_contract_fixture_is_available_to_python_suite() -> None:
    fixture = Path(__file__).parents[4] / "packages/contracts/fixtures/valid/research-state.json"
    payload = json.loads(fixture.read_text())
    assert payload["schemaVersion"] == "1.1"
    assert payload["sourceIds"] == []
    assert "rawPageContent" not in payload
    assert ResearchState.model_validate(payload).schema_version == "1.1"


def test_python_contract_rejects_the_shared_invalid_fixture() -> None:
    fixture = (
        Path(__file__).parents[4]
        / "packages/contracts/fixtures/invalid/research-state-raw-content.json"
    )
    payload = json.loads(fixture.read_text())
    try:
        ResearchState.model_validate(payload)
    except ValidationError:
        return
    raise AssertionError("generated Pydantic contract accepted raw graph-state content")
