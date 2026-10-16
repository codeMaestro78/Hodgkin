# Offline latency measurement

## Historical observations, not a current benchmark

Read-only analysis of the previously supplied service attachment `71be935d`
accepted 146 JSON records from 270 lines; 124 lines were malformed/skipped by
strict JSONL parsing. For its successful dependency records:

| Boundary | Samples | p50 | p95 (nearest rank) |
| --- | ---: | ---: | ---: |
| OpenAI attempt including accounting | 6 | 8,067.27 ms | 12,040.34 ms |
| Tavily search HTTP/status boundary | 6 | 3,165.41 ms | 4,939.74 ms |
| Tavily extract HTTP/status boundary | 6 | 553.32 ms | 1,081.43 ms |

Two collection-node records had p50 42,931.41 ms and p95 43,316.43 ms; two
synthesis-node records had p50 26,637.50 ms and p95 29,021.23 ms. These enclosing
spans overlap the dependency records and must not be added to them.

The older attachment `f0816a6e` accepted 415 records from 443 lines. It had two
successful model, three search and three extraction attempt records, plus a
28,461 ms synthesizer error span. Across both files, all 26 model/search/extract
records lacked remote timings. Skipped log lines were not recovered by speculative
prefix parsing. Tiny, partially observed historical samples cannot establish a
current production percentile, remote compute time or a controlled speedup.

## Usage

From `services/research-api`:

```sh
python scripts/latency_report.py /path/to/operations.jsonl
python scripts/latency_report.py - --run-id 00000000-0000-0000-0000-000000000001 < operations.jsonl
.venv/bin/pytest tests/unit/test_latency_report.py
```

The script uses only the Python standard library, imports no service modules,
reads no environment/configuration/credentials, and makes no network calls.
Supply one JSON object per line, with `event` equal to `operation.outcome` or
`dependency.outcome`, as emitted by `src/research_api/telemetry.py`.
Required dimensions are `operation`, `outcome`, and optionally `provider` and
`runId`; total duration is numeric `durationMs`. Attempt records can also supply
optional numeric `remoteDurationMs` on the same event. Non-JSON console prefixes and JSON
logging envelopes are not unwrapped. Export the JSON message field first.

No production measurements are bundled or claimed. Tests use synthetic recorded
delays; they validate arithmetic and handling, not live provider performance.

## Reading the report

- `operations`: each operation independently, including enclosing graph/node spans.
- `dependencies`: operation/provider pairs, with `category=attempt` for
  `model`, `search`, and `extract`; other dependency events are diagnostics.
- `run_nodes`: node operations grouped by run UUID and node, a second view of
  the same node records. Repeated node executions remain separate observations.
- `response_headers`: `firstByteMs` from `http.request` records only. This is
  response-start latency, not time to a token or meaningful evidence.

Each group reports `success`, `errors`, and `other` distributions with count,
p50, p95, and max in milliseconds. Percentiles use exact nearest rank:
sorted value at index `ceil(p * count) - 1`. An empty distribution has count 0
and null statistics. Counts in distributions include only valid durations;
`records`, `record_counts`, `outcomes`, and `excluded_durations` also account for
events without valid timing. Zero is valid; null, booleans, strings, negative,
nonfinite, and overflowing durations are excluded. Error durations never enter
success percentiles.

Attempt groups additionally report `remote_success`, `remote_errors`, and
`remote_other`, using the same outcome buckets and percentile method, plus
`excluded_remote_durations`. Missing `remoteDurationMs` (including older logs),
null, or invalid values increment this separate exclusion count; they are never
replaced by zero or by `durationMs`. Remote and total validity are independent.
Existing fields and counts keep their meanings; adding remote timing does not
create extra records. Diagnostics and operation/node groups have no remote fields.

Remote duration measures the SDK/client/network boundary, including local client
processing, network transit, and remote response wait. It is not provider-compute-only
latency. Existing `durationMs` measures the total attempt through the log emission
point, including accounting where applicable. Remote time is contained within
total time: do not sum these distributions or subtract their percentiles to
estimate accounting overhead. Replayed receipts have no fresh remote timing;
the analyzer does not synthesize one from a receipt or total duration.

`succeeded` and `consumed` are successes. `failed`, `released`, `uncertain`,
`not_dispatched`, `cancelled`, and `rejected` enter the error bucket.
Here error includes non-success dispatch outcomes: `not_dispatched` admission
diagnostics can mean cache/quota policy, not a provider outage. Other recognized
outcomes and unrecognized outcomes enter `other`. HTTP `statusCode >= 400`
overrides the bucket to errors, even if the original `outcomes` says succeeded.

Do not add durations across nested operations or combine operation and attempt
counts. Do not add `run_nodes` counts to `operations`. There is no grand total
of elapsed time: overlapping operations and parallelism make that misleading.
No unique dispatch ID is logged, so duplicated log lines cannot be reliably
deduplicated; `attempt=1` is not an identity. Use a single nonduplicated export.
Provider logs lack node/model-name dimensions, so the report does not attribute
model attempts to individual nodes or model variants.

## Existing boundaries and instrumentation gaps

The total and remote boundaries below are confirmed in the current working tree.
`model_budget.py` and `providers/tavily.py` supply optional remote durations, and
`telemetry.py` emits `remoteDurationMs` on the existing dependency outcome event,
with no additional records. The analyzer supports both current and older logs.
These boundaries describe client-observed durations rather than provider-only service time:

| Source | Actual measurement | Limits |
| --- | --- | --- |
| `model_budget.py:model_response` | `dependency.outcome`, `openai/model`, each ledger-backed dispatch attempt. `durationMs` starts immediately before `client.responses.create`; optional `remoteDurationMs` uses that same start and stops immediately when the SDK response/failure returns, before accounting. | Total success ends after usage validation, receipt persistence, reservation settlement, and budget reads; total failure ends after accounting transition. Remote excludes that settlement work but includes SDK/client/network time. Retry delay and pre-dispatch admission are outside both intervals. Replayed receipts are not fresh dispatches. |
| `providers/tavily.py:TavilyAdapter._post` | `tavily/search` or `tavily/extract` per HTTP attempt, starting before `httpx.post`. Optional `remoteDurationMs` is captured after HTTP receive/status check, or when that boundary fails; `durationMs` ends at the existing outcome log. | Remote includes client/network work. Both exclude subsequent JSON decoding/schema validation, artifact persistence, and ingestion. A timed HTTP success can still fail later validation. Remote and total overlap; do not sum. |
| `graph/builder.py:tracked` | `node.<name>` duration around cancellation check, task start, and node function | Ends before `finish_node`; graph interrupts do not emit a node outcome. Nodes are intake, planner, research_worker, reflector, planner_delta, verifier, synthesizer, and conditional approval_gate. |
| `graph/builder.py:run_graph` | `research.graph` from function entry through graph invocation, including claim/setup and checkpoint reads | Nested with node/attempt spans; not enqueue-to-completion or browser-perceived latency. Some cancellation/lease-loss paths emit no terminal duration. |
| `main.py:RequestTiming` | `http.headers`, `http.request`, request `firstByteMs` | HTTP request duration includes SSE stream lifetime; response-start is not first SSE evidence. No route strings are copied into the report. |
| `jobs.py:claim/finish`, `dispatcher.py` | Claim/finish call duration and dispatcher operations | Claim duration is not queue residence; `activeMs` and `remainingMs` are accounting/budget facts, not queue samples. |
| `ingestion.py` | Source/admission/accounting diagnostics | Most have null durations and are not completion measurements. |

Missing instrumentation to report to the runtime owner:

- `model_budget.py:model_response` returns directly without telemetry when
  `model_run` is unset; replay paths also return without a fresh dispatch timing.
  Older model records without `remoteDurationMs` cannot isolate the SDK boundary
  from settlement work. The optional field resolves that boundary without
  measuring provider compute alone or time to first token. Node/model attribution
  is outside this slice.
- Queue wait needs an actual enqueue-to-successful-claim duration, with explicit
  handling for retries/recovery. Current claim logs do not contain that interval.
- First evidence needs a defined milestone (source discovered versus verified
  claim committed) and duration from run acceptance. Existing operational logs
  lack that correlated timing; response headers cannot substitute for it.
- Routine auth/database/HTTP records can be suppressed at INFO by
  `telemetry.py:operation_event`; slow-statement logs are threshold-selected.
  Distributions describe only exported records and may be biased. Missing
  measurements do not establish low latency.

The report always marks queue wait and first evidence missing for this input
contract. It does not infer them from timestamps, graph spans, budget counters,
or arbitrary extra fields. No runtime instrumentation is changed by this tool.

## Privacy and bounds

Only audited static operation/provider/outcome labels are output verbatim.
Unknown operation/provider/non-UUID run labels become truncated SHA-256 labels;
unrecognized outcomes become `other`. UUID run IDs remain visible for traceability.
Hashes are pseudonyms, not cryptographic anonymization of low-entropy labels.
Prompts, paths, URLs, headers, request IDs, exception details, and extra fields
are neither retained nor copied to stdout/stderr. Input errors use a generic
message without raw records, paths, or exception text.

Input is streamed, capped at 100,000 physical lines by default (including ignored
and filtered lines), and 1,048,576 characters per line. `--max-records` changes
the line cap. All valid observations up to the cap are retained for exact
percentiles; memory is O(line cap plus maximum line size), with additional copies
for sorting, optional remote observations, and the per-run node/header views. This is a bounded small-export
tool, not an unlimited log ingestion system. No reservoir sampling is used.
Exceeding either bound exits 2 without emitting a partial report. Narrow the
export before using a larger cap. Invalid run UUIDs/unreadable input also exit 2;
malformed lines are counted and skipped, so review `input` counters.
