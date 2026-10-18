import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from research_api.structured_output import (
    StructuredModelOutputError,
    parse_structured_response,
)


class Payload(BaseModel):
    answer: str


def response(text, *, status="completed", reason=None, output=()):
    return SimpleNamespace(
        output_text=text,
        status=status,
        incomplete_details=SimpleNamespace(reason=reason) if reason else None,
        output=output,
    )


@pytest.mark.parametrize(
    ("item", "category"),
    [
        (response(""), "empty_output"),
        (response("not json"), "invalid_json"),
        (response('{"answer":'), "truncated_json"),
        (response('{"wrong": "shape"}'), "schema_validation"),
        (
            response('{"answer":"secret"}', status="incomplete", reason="max_output_tokens"),
            "provider_incomplete",
        ),
        (
            response(
                '{"answer":"secret"}',
                output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
            ),
            "refusal",
        ),
        (response('{"answer":"secret"}', status="cancelled"), "provider_cancelled"),
    ],
)
def test_structured_output_rejections_are_classified_without_logging_payload(
    item, category, caplog
):
    caplog.set_level(logging.INFO, logger="research_api.dependencies")
    response_marker = "private-model-response-marker"
    item.output_text = item.output_text.replace("secret", response_marker)

    with pytest.raises(StructuredModelOutputError) as error:
        parse_structured_response(item, Payload, operation="test.structured_output")

    assert error.value.category == category
    records = [record.message for record in caplog.records]
    diagnostic = next(
        json.loads(line) for line in records if '"operation": "test.structured_output"' in line
    )
    assert diagnostic["parseCategory"] == category
    assert diagnostic["responseStatus"] in {
        "completed",
        "incomplete",
        "failed",
        "cancelled",
    }
    assert isinstance(diagnostic["outputBytes"], int)
    assert response_marker not in "\n".join(records)


def test_structured_output_success_validates_and_logs_only_summary(caplog):
    caplog.set_level(logging.INFO, logger="research_api.dependencies")
    result = parse_structured_response(
        response('{"answer":"safe"}'), Payload, operation="test.structured_output"
    )

    assert result.answer == "safe"
    diagnostic = next(
        json.loads(record.message)
        for record in caplog.records
        if '"operation": "test.structured_output"' in record.message
    )
    assert diagnostic["parseCategory"] == "valid"
    assert diagnostic["outcome"] == "succeeded"
