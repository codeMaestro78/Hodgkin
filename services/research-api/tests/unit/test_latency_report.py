"""Synthetic timing fixtures only: no SDK, application, credentials, or paid calls."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "latency_report.py"
spec = importlib.util.spec_from_file_location("latency_report", SCRIPT)
assert spec is not None and spec.loader is not None
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)

RUN = "00000000-0000-0000-0000-000000000001"
OTHER_RUN = "00000000-0000-0000-0000-000000000002"


def event(ms=100, **fields):
    return {
        "event": "operation.outcome",
        "operation": "node.planner",
        "runId": RUN,
        "durationMs": ms,
        "outcome": "succeeded",
        **fields,
    }


def analyze(*records, **options):
    return reporter.analyze(io.StringIO("".join(json.dumps(r) + "\n" for r in records)), **options)


def test_synthetic_delays_have_exact_nearest_rank_percentiles_and_run_nodes():
    report = analyze(*(event(ms) for ms in range(100, 2100, 100)))
    expected = {"count": 20, "p50_ms": 1000, "p95_ms": 1900, "max_ms": 2000}
    assert report["operations"][0]["success"] == expected
    assert report["run_nodes"][0]["success"] == expected
    assert report["run_nodes"][0]["run_id"] == RUN


def test_first_verified_finding_is_a_milestone_not_a_fake_duration():
    records = [
        {
            "event": "research.milestone",
            "milestone": "research.first_verified_finding",
            "runId": RUN,
            "verifiedFindingCount": 2,
            "recordedAt": "2026-10-17T12:00:00.000+00:00",
        },
        event(
            0,
            operation="research.first_verified_finding",
            verifiedFindingCount=2,
            recordedAt="2026-10-17T12:00:00.000+00:00",
        ),
    ]
    report = analyze(*records)
    assert report["milestones"] == [
        {"milestone": "research.first_verified_finding", "count": 2}
    ]
    assert report["operations"] == []
    assert "2026-10-17" not in json.dumps(report)


def test_retry_attempts_diagnostics_and_enclosing_nodes_remain_separate():
    report = analyze(
        event(700),
        event(
            100,
            event="dependency.outcome",
            operation="model",
            provider="openai",
            outcome="released",
            attempt=1,
            retryScheduled=True,
        ),
        event(
            500,
            event="dependency.outcome",
            operation="model",
            provider="openai",
            outcome="consumed",
            attempt=2,
        ),
        event(
            None,
            event="dependency.outcome",
            operation="accounting",
            provider="openai",
            outcome="estimated",
        ),
        event(90, event="dependency.outcome", operation="search", provider="tavily"),
    )
    attempt = next(r for r in report["dependencies"] if r["operation"] == "model")
    assert attempt["category"] == "attempt"
    assert attempt["success"]["max_ms"] == 500
    assert attempt["errors"]["max_ms"] == 100
    assert attempt["records"] == 2
    assert attempt["attempt_numbers"] == {"1": 1, "2": 1}
    assert attempt["retries_scheduled"] == 1
    diagnostic = next(r for r in report["dependencies"] if r["operation"] == "accounting")
    assert diagnostic["category"] == "diagnostic"
    assert diagnostic["excluded_durations"] == 1
    assert report["operations"][0]["success"]["count"] == 1


def test_model_start_is_not_counted_as_a_second_attempt():
    report = analyze(
        event(
            None,
            event="dependency.outcome",
            operation="model",
            provider="openrouter",
            outcome="started",
        ),
        event(
            50,
            event="dependency.outcome",
            operation="model",
            provider="openrouter",
            outcome="consumed",
            remoteDurationMs=40,
        ),
    )
    assert report["input"]["lifecycle"] == 1
    group = report["dependencies"][0]
    assert group["provider"] == "openrouter"
    assert group["records"] == 1
    assert group["excluded_durations"] == 0
    assert group["success"]["count"] == 1


def test_collection_stage_timings_keep_admission_artifacts_and_persistence_visible():
    report = analyze(
        event(11, operation="research.extract.admission"),
        event(22, operation="research.source.artifacts"),
        event(33, operation="research.source.persistence"),
    )
    observed = {row["operation"]: row["success"]["max_ms"] for row in report["operations"]}
    assert observed == {
        "research.extract.admission": 11,
        "research.source.artifacts": 22,
        "research.source.persistence": 33,
    }


def test_database_query_timings_are_grouped_by_safe_family_and_command():
    rows = analyze(
        event(
            12,
            operation="db.statement.timing",
            commandCategory="SELECT",
            queryFamily="run",
        ),
        event(
            34,
            operation="db.statement.timing",
            commandCategory="UPDATE",
            queryFamily="run_exclusive",
        ),
    )["operations"]
    measurements = [
        (row["command_category"], row["query_family"], row["success"]["max_ms"])
        for row in rows
    ]
    assert measurements == [
        ("SELECT", "run", 12),
        ("UPDATE", "run_exclusive", 34),
    ]


@pytest.mark.parametrize(
    "bad", [None, float("nan"), float("inf"), -float("inf"), -1, True, "200", {}, [], 10**400]
)
def test_invalid_durations_are_excluded_not_zeroed(bad):
    group = analyze(event(bad), event(0))["operations"][0]
    assert group["records"] == 2
    assert group["excluded_durations"] == 1
    assert group["success"] == {"count": 1, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}


def test_filtering_and_unknown_data_never_echo_secrets_or_prompts():
    secret = "sk-fixture-secret prompt: private question https://private.test?token=secret"  # noqa: S105
    record = event(
        42,
        operation=secret,
        provider=secret,
        outcome=secret,
        runId=secret,
        errors=[{"message": secret}],
        prompt=secret,
        reason=secret,
        requestId=secret,
        headers={"Authorization": secret},
    )
    report = analyze(record, event(100), event(9000, runId=OTHER_RUN), run_id=RUN)
    assert report["input"]["filtered"] == 2
    assert report["operations"][0]["success"]["max_ms"] == 100
    output = json.dumps(analyze(record, {**record, "event": "dependency.outcome"}))
    assert secret not in output
    assert "private question" not in output
    assert "Authorization" not in output
    assert "redacted:" in output
    assert json.loads(output)["operations"][0]["other"]["count"] == 1


def test_malformed_unknown_and_nested_records_are_counted_safely():
    stream = io.StringIO(
        'secret invalid JSON\n[]\n{"event": []}\n'
        + json.dumps({"message": json.dumps(event())})
        + "\n"
        + json.dumps(event(30))
        + "\n"
    )
    report = reporter.analyze(stream)
    assert report["input"] == {"lines": 5, "malformed": 1, "ignored": 3, "accepted": 1}


def test_http_status_errors_and_headers_are_not_evidence_or_queue_wait():
    report = analyze(
        event(1000, operation="http.request", firstByteMs=25, statusCode=503),
        event(20, operation="http.headers"),
    )
    request = next(r for r in report["operations"] if r["operation"] == "http.request")
    assert request["errors"]["count"] == 1
    assert request["success"]["count"] == 0
    assert report["response_headers"][0]["errors"]["p50_ms"] == 25
    assert set(report["missing_signals"]) == {"queue_wait"}


def test_empty_input_has_missing_signals_and_no_fabricated_measurements():
    report = analyze()
    assert report["operations"] == report["dependencies"] == report["run_nodes"] == []
    assert report["missing_signals"]


def test_errors_without_duration_remain_counted_and_runs_stay_separate():
    report = analyze(event(None, outcome="failed"), event(99, runId=OTHER_RUN))
    group = report["operations"][0]
    assert group["record_counts"] == {"errors": 1, "success": 1}
    assert group["errors"]["count"] == 0
    assert group["errors"]["p95_ms"] is None
    assert len(report["run_nodes"]) == 2
    assert report["run_nodes"][0]["run_id"] != report["run_nodes"][1]["run_id"]


def test_bounds_fail_without_partial_report_or_raw_input(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event()) + "\nsecret\n"))
    assert reporter.main(["--max-records", "1"]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "secret" not in captured.err
    with pytest.raises(reporter.InputLimitError):
        reporter.analyze(io.StringIO("x" * (reporter.MAX_LINE_CHARS + 1)))


def test_cli_file_and_stdin_produce_same_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "synthetic.jsonl"
    raw = json.dumps(event(120)) + "\n"
    path.write_text(raw)
    assert reporter.main([str(path), "--run-id", RUN]) == 0
    from_file = json.loads(capsys.readouterr().out)
    monkeypatch.setattr("sys.stdin", io.StringIO(raw))
    assert reporter.main(["-", "--run-id", RUN]) == 0
    assert json.loads(capsys.readouterr().out) == from_file


@pytest.mark.parametrize(
    "options", [["--run-id", "secret"], ["--max-records", "0"], ["/nonexistent/secret-file"]]
)
def test_cli_input_errors_are_generic(options, capsys):
    assert reporter.main(options) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "secret" not in captured.err


def test_remote_attempt_distributions_preserve_total_metrics_and_record_counts():
    records = [
        event(
            1000 + ms,
            event="dependency.outcome",
            operation="model",
            provider="openai",
            outcome="consumed",
            remoteDurationMs=ms,
        )
        for ms in range(100, 2100, 100)
    ]
    records.extend(
        [
            event(
                900,
                event="dependency.outcome",
                operation="model",
                provider="openai",
                outcome="uncertain",
                remoteDurationMs=700,
            ),
            event(
                80,
                event="dependency.outcome",
                operation="model",
                provider="openai",
                outcome="cached",
                remoteDurationMs=0,
            ),
        ]
    )
    group = analyze(*records)["dependencies"][0]
    assert group["remote_success"] == {
        "count": 20,
        "p50_ms": 1000,
        "p95_ms": 1900,
        "max_ms": 2000,
    }
    assert group["remote_errors"] == {
        "count": 1,
        "p50_ms": 700,
        "p95_ms": 700,
        "max_ms": 700,
    }
    assert group["remote_other"] == {"count": 1, "p50_ms": 0, "p95_ms": 0, "max_ms": 0}
    assert group["excluded_remote_durations"] == 0
    legacy = analyze(*[{k: v for k, v in r.items() if k != "remoteDurationMs"} for r in records])[
        "dependencies"
    ][0]
    assert {
        k: v
        for k, v in group.items()
        if not k.startswith("remote_") and k != "excluded_remote_durations"
    } == {
        k: v
        for k, v in legacy.items()
        if not k.startswith("remote_") and k != "excluded_remote_durations"
    }
    assert group["records"] == 22
    assert group["success"]["p95_ms"] == 2900


@pytest.mark.parametrize(
    "bad",
    [
        None,
        float("nan"),
        float("inf"),
        -float("inf"),
        -1,
        True,
        "private prompt sk-fixture",
        {},
        [],
        10**400,
    ],
)
def test_remote_invalid_and_missing_values_are_excluded_independently(bad):
    report = analyze(
        event(
            20,
            event="dependency.outcome",
            operation="search",
            provider="tavily",
            remoteDurationMs=bad,
        ),
        event(30, event="dependency.outcome", operation="search", provider="tavily"),
        event(
            None,
            event="dependency.outcome",
            operation="search",
            provider="tavily",
            remoteDurationMs=10,
        ),
    )
    group = report["dependencies"][0]
    assert group["excluded_remote_durations"] == 2
    assert group["excluded_durations"] == 1
    assert group["remote_success"] == {
        "count": 1,
        "p50_ms": 10,
        "p95_ms": 10,
        "max_ms": 10,
    }
    assert group["success"]["count"] == 2
    assert "private prompt" not in json.dumps(report, allow_nan=False)


def test_remote_fields_only_apply_to_attempt_groups_and_respect_run_filter():
    report = analyze(
        event(100, remoteDurationMs=99),
        event(
            100,
            event="dependency.outcome",
            operation="accounting",
            provider="openai",
            remoteDurationMs=99,
        ),
        event(
            100,
            event="dependency.outcome",
            operation="extract",
            provider="tavily",
            remoteDurationMs=99,
            runId=OTHER_RUN,
        ),
        event(
            100,
            event="dependency.outcome",
            operation="extract",
            provider="tavily",
            remoteDurationMs=20,
            statusCode=503,
        ),
        run_id=RUN,
    )
    assert "remote_success" not in report["operations"][0]
    assert "remote_success" not in report["run_nodes"][0]
    diagnostic = next(r for r in report["dependencies"] if r["category"] == "diagnostic")
    assert "remote_success" not in diagnostic
    attempt = next(r for r in report["dependencies"] if r["category"] == "attempt")
    assert attempt["remote_errors"]["max_ms"] == 20
    assert attempt["remote_success"]["count"] == 0


def test_legacy_attempt_and_replay_without_fresh_remote_timing_are_not_zero_samples():
    group = analyze(
        event(50, event="dependency.outcome", operation="model", provider="openai"),
        event(
            None, event="dependency.outcome", operation="model", provider="openai", outcome="cached"
        ),
    )["dependencies"][0]
    assert group["excluded_remote_durations"] == 2
    for bucket in ("success", "errors", "other"):
        assert group[f"remote_{bucket}"] == {
            "count": 0,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }
