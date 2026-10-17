import hashlib
import json
from types import SimpleNamespace

from fastapi import HTTPException

from research_api.report_integrity import report_integrity_payload
from research_api.sharing_exports_api import _canonical_report_hash


def test_legacy_report_hash_payload_remains_compatible():
    report = SimpleNamespace(markdown="# Report", document=None, retrieval_accounting=None)
    payload = report_integrity_payload(report)
    assert payload == {"markdown": "# Report", "document": None}


def test_new_report_hash_covers_the_immutable_accounting_snapshot():
    report = SimpleNamespace(
        markdown="# Report",
        document={"version": 4},
        retrieval_accounting={"schemaVersion": "1.1", "extractedSources": 3},
    )
    payload = report_integrity_payload(report)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    report.retrieval_accounting = {"schemaVersion": "1.1", "extractedSources": 4}
    changed_digest = hashlib.sha256(
        json.dumps(report_integrity_payload(report), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert digest != changed_digest


def test_export_integrity_verifies_snapshot_and_preserves_legacy_hashes():
    report = SimpleNamespace(
        markdown="# Report",
        document={"version": 4},
        retrieval_accounting={"schemaVersion": "1.1", "extractedSources": 3},
        content_hash=None,
    )
    expected = hashlib.sha256(
        json.dumps(report_integrity_payload(report), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report.content_hash = expected
    assert _canonical_report_hash(report) == expected
    report.retrieval_accounting["extractedSources"] = 4
    try:
        _canonical_report_hash(report)
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("tampered retrieval accounting must fail report integrity")
