"""Canonical hash payload for immutable report versions."""

from typing import Any


def report_integrity_payload(report: Any) -> dict[str, object]:
    payload: dict[str, object] = {"markdown": report.markdown, "document": report.document}
    accounting = getattr(report, "retrieval_accounting", None)
    if accounting is not None:
        payload["retrievalAccounting"] = accounting
    return payload
