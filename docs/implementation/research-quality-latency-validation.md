# Fresh quality and latency validation — 2026-10-16

## Scope

Three fresh Focused runs used live configured OpenAI/Tavily services with local
PostgreSQL, Redis, object storage, durable dispatch and checkpoints. Persistence
was isolated in `research_quality_validation_20261016`; no hosted research was
created or modified. Each run retained six provider operations and the existing
180-second active budget. Approval was not requested by this benchmark, so these
durations exclude human review. They include run creation through job execution
and report persistence, not browser rendering or authenticated hosted API calls.

Workload: compare Kafka event-driven microservices with Temporal workflow
orchestration for high-throughput fintech ledgers, including durability,
consistency boundaries, failure handling and operational trade-offs. All three
model roles used the configured `gpt-6-luna` route; no model swap was made.

## Failure found and repaired

The first run (`f5a2c0cb-3249-4798-8a28-e752f5e62888`) failed after 14.78 seconds:
the provider rejected source quotations containing quotation marks in strict
schema enum literals. This was a real writer request failure, not low latency.

The writer now selects source-bound ASCII passage IDs instead of generating
quotation text. The server restores literal text from the saved evidence before
the existing exact-span and semantic-support checks. Source text stays out of
schema enum values and is not repeated in generated output. Unknown or
cross-source IDs reject the entire candidate. Existing legacy-request replay
is retained; no verification rule, timeout, budget or retry allowance was relaxed.

## Successful runs after repair

| Run ID | Total | First source | Sources | Verified / candidates | Quality |
| --- | ---: | ---: | ---: | ---: | --- |
| `1762f271-a743-4a68-bd9e-8eedd4ce9519` | 40.21 s | 11.48 s | 5 | 11 / 12 | partial |
| `ff1a8534-2d7f-44da-8521-a5520985d076` | 44.02 s | 12.90 s | 5 | 5 / 7 | partial |

Both used exactly six provider operations and had no provider errors or retries.
The first excluded candidate stated a lack of comparative evidence without a
supporting citation; the second excluded two partially supported claims. Exclusion
was retained rather than weakening the evidence gate. The published findings
contain useful architectural facts, but do not establish measured ledger
throughput or a complete consistency comparison. Source balance and report
completeness still need improvement. A completed execution is not a complete answer.

| Remote model boundary | First success | Repeat |
| --- | ---: | ---: |
| Planner | 7.50 s | 8.31 s |
| Writer | 22.79 s | 25.44 s |
| Claim review | 4.03 s | 4.26 s |

Collection took approximately 5.1 seconds in each successful check. Writer output
dominates the measured critical path. These boundaries overlap enclosing node
timings and must not be added twice. Two successful checks are not a stable p95
or a production SLA. Estimated ledger cost was $0.050073 and $0.050139 respectively;
these are policy estimates, not verified provider billing.

## Separate hosted transport probes

Read-only probes observed a cold database connection at approximately 2.42 seconds
and three warm `SELECT 1` calls at 154–155 ms. Supabase Auth's health endpoint
returned HTTP 200 in 512 ms cold and 176 ms warm. A health request is not an
authenticated user validation, and `SELECT 1` is not a full tenant snapshot.
Hosted end-to-end latency remains unmeasured by these local-persistence runs.

## Reproduction and next gates

The opt-in `scripts/benchmark_focused.py` supports `--question` for one explicit
workload and emits model role, remote/total duration, quality and rejection
summaries. It retains its paid-call confirmation and loopback-persistence guards.
The offline analyzer excludes model-start lifecycle records from attempt counts,
so one start/end pair cannot inflate completion counts or missing-duration totals.
Operational output does not include prompts, credentials or raw provider replies.

Restart the API to load the repaired writer. Then measure an authenticated
hosted run and dashboard independently. Compare model routes or output verbosity
only against a fixed workload and quality gate; do not promise sub-10-second
research by dropping verification or truncating reports. Repeat under representative
load before setting latency objectives. No deployment or hosted schema change is
part of this validation.
