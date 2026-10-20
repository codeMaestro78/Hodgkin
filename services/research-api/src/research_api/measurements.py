"""Exact-passage admission and deterministic chart grouping for measurements."""

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast

from pydantic import BaseModel, ConfigDict, Field

_NUMBER = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$")
_MAX_PLOT_MAGNITUDE = Decimal("1e18")


class MeasurementProposal(BaseModel):
    """Model-suggested fields; none is trusted until matched to a supported quote."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1, max_length=160)
    metric: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=80)
    unit: Annotated[str, Field(min_length=1, max_length=40)] | None
    population: Annotated[str, Field(min_length=1, max_length=240)] | None
    period: Annotated[str, Field(min_length=1, max_length=120)] | None
    method: Annotated[str, Field(min_length=1, max_length=240)] | None
    definition: Annotated[str, Field(min_length=1, max_length=300)] | None
    source_location: Annotated[str, Field(min_length=1, max_length=120)] | None
    claim_index: int = Field(ge=0, le=39)
    citation_index: int = Field(ge=0, le=7)


def _plot_value(value: str) -> str | None:
    if not _NUMBER.fullmatch(value):
        return None
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) > _MAX_PLOT_MAGNITUDE:
        return None
    # This is only an exact numeric coordinate for plotting. The source literal remains `value`.
    return format(number, "f")


def _value_unit_is_adjacent(value: str, unit: str, quote: str) -> bool:
    """Require an asserted unit to be attached to the exact source value."""
    value_pattern = re.escape(value)
    unit_pattern = re.escape(unit)
    if unit in {"$", "€", "£"}:
        patterns: tuple[str, ...] = (
            unit_pattern + r"\s*" + value_pattern,
            value_pattern + r"\s*" + unit_pattern,
        )
    else:
        patterns = (value_pattern + r"\s*" + unit_pattern,)
    return any(re.search(pattern, quote) is not None for pattern in patterns)


def _value_is_literal(value: str, quote: str) -> bool:
    """Avoid accepting a scalar found only inside a larger number or a reported range."""
    if not _NUMBER.fullmatch(value):
        return value in quote
    match = re.search(r"(?<![\d.,])" + re.escape(value) + r"(?![\d.,])", quote)
    if match is None:
        return False
    suffix = quote[match.end() :]
    return re.match(r"\s*[-–—]\s*\d", suffix) is None


def review_measurements(
    proposals: list[MeasurementProposal], audited: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Admit measurements only when all asserted descriptors are literal in a supported quote."""
    receipts: list[dict[str, Any]] = []
    for proposal in proposals:
        reasons: list[str] = []
        claim = audited[proposal.claim_index] if proposal.claim_index < len(audited) else None
        citation = (
            claim["citations"][proposal.citation_index]
            if claim is not None and proposal.citation_index < len(claim["citations"])
            else None
        )
        if claim is None or claim["status"] != "supported":
            reasons.append("claim_not_supported")
        if citation is None:
            reasons.append("citation_not_verified")
        quote = citation["quote"] if citation else ""
        claim_text = claim["claim"] if claim else ""
        for name in ("subject", "metric", "value"):
            value = getattr(proposal, name)
            if not (_value_is_literal(value, quote) if name == "value" else value in quote):
                reasons.append(f"{name}_not_in_exact_passage")
        for name in ("unit", "population", "period", "method", "definition", "source_location"):
            value = getattr(proposal, name)
            if value is not None and value not in quote:
                reasons.append(f"{name}_not_in_exact_passage")
        if proposal.unit is not None and not _value_unit_is_adjacent(
            proposal.value, proposal.unit, quote
        ):
            reasons.append("value_unit_not_adjacent_in_exact_passage")
        if proposal.value not in claim_text:
            reasons.append("value_not_in_supported_claim")
        if proposal.subject.casefold() not in (claim_text + "\n" + quote).casefold():
            reasons.append("subject_not_in_claim_or_passage")
        if proposal.metric.casefold() not in (claim_text + "\n" + quote).casefold():
            reasons.append("metric_not_in_claim_or_passage")

        plot_value = _plot_value(proposal.value)
        result = None
        if not reasons and citation and claim:
            result = {
                "id": f"measurement-{len(receipts) + 1}",
                "title": f"{proposal.metric}: {proposal.subject}",
                "claimId": claim["claim_id"],
                "citationId": citation["citation_id"],
                "sourceId": citation["source_id"],
                "sourceArtifactHash": citation["source_hash"],
                "subject": proposal.subject,
                "metric": proposal.metric,
                "value": proposal.value,
                "unit": proposal.unit,
                "population": proposal.population,
                "period": proposal.period,
                "method": proposal.method,
                "definition": proposal.definition,
                "sourcePassage": quote,
                "sourceLocation": proposal.source_location,
                "plotValue": plot_value,
                "verification": "exact_passage_and_scoped_semantic_claim_review_v1",
            }
        receipts.append(
            {
                "proposal": proposal.model_dump(mode="json"),
                "status": "supported" if result else "not_assessed",
                "reasons": reasons,
                "result": result,
            }
        )
    return receipts


def compatible_measurement_charts(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build bar charts only from exact-match definitions and fully known comparison scope."""
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in measurements:
        fields = ("metric", "unit", "population", "period", "method", "definition")
        values = tuple(row.get(field) for field in fields)
        if any(not isinstance(value, str) or not value.strip() for value in values):
            continue
        if not isinstance(row.get("plotValue"), str) or _plot_value(row["plotValue"]) is None:
            continue
        if Decimal(row["plotValue"]) < 0:
            continue
        key = cast(tuple[str, str, str, str, str, str], values)
        groups.setdefault(key, []).append(row)
    charts: list[dict[str, Any]] = []
    for key, rows in groups.items():
        if len(rows) < 2 or len(rows) > 24:
            continue
        subjects = [row["subject"] for row in rows]
        if len(set(subjects)) != len(subjects):
            continue
        metric, unit, population, period, method, definition = key
        charts.append(
            {
                "id": f"measurement-chart-{len(charts) + 1}",
                "title": f"{metric} by subject",
                "metric": metric,
                "unit": unit,
                "population": population,
                "period": period,
                "method": method,
                "definition": definition,
                "measurementIds": [row["id"] for row in rows],
                "basis": "identical_metric_unit_population_period_method_definition_v1",
            }
        )
    return charts


def measurement_comparisons(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project same-metric rows and state comparability without filling missing fields."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in measurements:
        groups.setdefault(row["metric"], []).append(row)
    comparisons: list[dict[str, Any]] = []
    scope_fields = ("unit", "population", "period", "method", "definition")
    for metric, rows in groups.items():
        if len(rows) < 2:
            continue
        scope = [tuple(row.get(field) for field in scope_fields) for row in rows]
        complete = all(
            all(isinstance(value, str) and value.strip() for value in row_scope)
            for row_scope in scope
        )
        unique_subjects = len({row["subject"] for row in rows}) == len(rows)
        comparable = complete and unique_subjects and all(item == scope[0] for item in scope)
        comparisons.append(
            {
                "id": f"measurement-comparison-{len(comparisons) + 1}",
                "metric": metric,
                "measurementIds": [row["id"] for row in rows],
                "status": "comparable" if comparable else "not_established",
                "basis": (
                    "exact_scope_match_v1" if comparable else "missing_or_incompatible_scope_v1"
                ),
            }
        )
    return comparisons
