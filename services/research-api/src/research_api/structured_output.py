"""Validate model structured output with diagnostics that never include its body."""

from __future__ import annotations

import json
from collections.abc import Callable
from time import monotonic
from typing import Any

from pydantic import BaseModel, ValidationError

from research_api.telemetry import operation_event

_RESPONSE_STATUSES = {"completed", "incomplete", "failed", "cancelled"}
_INCOMPLETE_REASONS = {"max_output_tokens", "content_filter"}


class StructuredModelOutputError(ValueError):
    """A provider response was received but could not satisfy its output contract."""

    def __init__(
        self,
        category: str,
        *,
        operation: str = "unknown",
        incomplete_reason: str | None = None,
    ) -> None:
        self.category = category
        self.operation = operation
        self.incomplete_reason = incomplete_reason
        super().__init__(f"structured model output rejected: {category}")


def structured_output_failure_code(error: BaseException) -> str | None:
    """Translate only known, sanitized failure facts into stable public codes."""
    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(4):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, StructuredModelOutputError):
            if (
                current.operation == "research.writer.structured_output"
                and current.category == "provider_incomplete"
                and current.incomplete_reason == "max_output_tokens"
            ):
                return "writer_output_limit_reached"
            if current.category == "provider_incomplete":
                return "model_output_incomplete"
            if current.category == "refusal":
                return "model_refused_output"
            return "model_output_invalid"
        current = current.__cause__ or current.__context__
    return None


def _refused(response: Any) -> bool:
    for item in getattr(response, "output", ()) or ():
        for content in getattr(item, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def parse_structured_response[T: BaseModel](
    response: Any,
    model: type[T],
    *,
    operation: str,
    transform: Callable[[Any], Any] | None = None,
) -> T:
    """Parse, transform, and validate output, logging only bounded safe facts.

    Do not attach response text, provider messages, prompts, or Pydantic error
    details to telemetry; all may contain source or user content.
    """
    started = monotonic()
    raw_status = getattr(response, "status", None)
    status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in _RESPONSE_STATUSES
        else "unknown"
    )
    incomplete = getattr(response, "incomplete_details", None)
    raw_reason = getattr(incomplete, "reason", None)
    incomplete_reason = (
        raw_reason
        if isinstance(raw_reason, str) and raw_reason in _INCOMPLETE_REASONS
        else "other"
        if raw_reason is not None
        else None
    )
    text = getattr(response, "output_text", None)
    output_bytes = len(text.encode("utf-8")) if isinstance(text, str) else 0
    refusal = _refused(response)

    category: str | None = None
    parsed: Any = None
    if refusal:
        category = "refusal"
    elif status == "incomplete":
        category = "provider_incomplete"
    elif status == "failed":
        category = "provider_failed"
    elif status == "cancelled":
        category = "provider_cancelled"
    elif not isinstance(text, str) or not text.strip():
        category = "empty_output"
    else:
        try:
            parsed = json.loads(text)
            if transform is not None:
                parsed = transform(parsed)
            result = model.model_validate(parsed)
        except json.JSONDecodeError as error:
            category = (
                "truncated_json"
                if error.pos >= len(text.rstrip()) or error.msg.startswith("Unterminated string")
                else "invalid_json"
            )
        except ValidationError:
            category = "schema_validation"
        except (TypeError, ValueError):
            category = "payload_validation"
        except Exception:
            # Transforms (e.g. passage-reference restoration) are part of the
            # validation boundary too. Do not leak their source-bearing errors.
            category = "payload_validation"
        else:
            operation_event(
                operation,
                started=started,
                outcome="succeeded",
                responseStatus=status,
                outputBytes=output_bytes,
                refusal=False,
                incompleteReason=incomplete_reason,
                parseCategory="valid",
            )
            return result

    operation_event(
        operation,
        started=started,
        outcome="rejected",
        responseStatus=status,
        outputBytes=output_bytes,
        refusal=refusal,
        incompleteReason=incomplete_reason,
        parseCategory=category,
    )
    raise StructuredModelOutputError(
        category or "unknown",
        operation=operation,
        incomplete_reason=incomplete_reason,
    )
