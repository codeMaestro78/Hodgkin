from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from research_api.structured_output import (
    StructuredModelOutputError,
    parse_structured_response,
    structured_output_failure_code,
)


class Payload(BaseModel):
    answer: str


def test_writer_output_limit_has_a_safe_user_failure_code():
    response = SimpleNamespace(
        output_text="",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        output=[],
    )
    with pytest.raises(StructuredModelOutputError) as raised:
        parse_structured_response(response, Payload, operation="research.writer.structured_output")

    assert structured_output_failure_code(raised.value) == "writer_output_limit_reached"


def test_other_structured_failures_remain_generic():
    error = StructuredModelOutputError(
        "provider_incomplete",
        operation="research.claim_review.structured_output",
        incomplete_reason="content_filter",
    )
    assert structured_output_failure_code(error) == "model_output_incomplete"


def test_unrelated_exception_without_a_cause_is_not_reclassified():
    assert structured_output_failure_code(TimeoutError("run deadline elapsed")) is None
