# Commit-driven event delivery and dependency measurements

## Reproduced delay

The regression drives the actual SSE generator against local PostgreSQL. With
the old sleep-based tail, an event committed while the stream was idle missed a
350 ms delivery gate. The stream could sleep for up to five seconds. No model or
search-provider call is involved in this reproduction.

## Implementation and safety boundaries

- PostgreSQL stays authoritative. There are no new event types or migrations.
- `EventOutbox.append` registers ORM event references on its transaction. Only
  after outer commit does `tenant_session` select still-persistent event rows,
  coalesce routing IDs, and send hints. Outer and savepoint rollbacks are tested.
- Local subscribers wake synchronously; other processes receive optional Redis
  Pub/Sub hints. Pub/Sub is best effort, not a second event log.
- Register before replay, clear before the database read, and wait only after
  releasing the transaction/connection. This closes the read-to-wait race.
- The Redis bridge has two background tasks, at most two connections and a
  1,024-entry coalescing queue per process. Queue overflow drops hints, not data.
  Publishing/connection retries never delay commit or change a run's outcome.
- Redis connection failure logs one warning per unavailable period, without URLs
  or exception bodies. Startup does not await Redis availability; shutdown cancels
  and joins transport tasks and closes the client.
- Hints include only tenant/run UUIDs. They cannot bypass tenant/user predicates,
  advance event sequence numbers, return content or change durable state.
- Existing 1–5 second idle polling and reconnect replay remain the fallback for
  missed hints, unavailable Redis, disabled bridging and process restarts.

The fallback is deliberate: Redis documents Pub/Sub as
[at-most-once delivery](https://redis.io/docs/latest/develop/pubsub/), so a wake-up
cannot replace the durable cursor log. Client connection and shutdown handling
follow the [redis-py asyncio API](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html).

Faster polling was rejected because it increases database work during quiet runs.
PostgreSQL LISTEN was not added: it needs persistent session connections that may
not be compatible with a transaction pooler. Existing Redis is an optional hint
transport rather than a mandatory durable dependency.

## Measurements and regression checks

From `services/research-api` with loopback PostgreSQL and Redis running:

```sh
uv run pytest tests/integration/test_event_wakeups.py tests/unit/test_event_wakeup_hub.py -s
```

The local 10-event sample observed commit-to-generator delivery median 2.90 ms,
nearest-rank p95 3.29 ms. This measures time after the committing context exits;
it excludes the write transaction, browser rendering, network transit and remote
model/provider completion. It is not a production percentile or benchmark SLO.

Tests also cover the five-second approval-wait path, cross-instance Redis delivery,
missed-hint fallback, tenant/run isolation, bounded queues, duplicate hints,
rollback/savepoint filtering, Redis unavailability and resource cleanup. Existing
tests continue to cover terminal replay pagination and access controls.

## Model/provider latency

Existing `dependency.outcome` records gain optional numeric `remoteDurationMs`;
no extra attempt log is emitted. OpenAI captures it immediately when the SDK call
returns or raises, before local usage/receipt/accounting work. Tavily captures
the HTTP call and status check. Both include network/client overhead, not just
provider compute. `durationMs` retains its existing enclosing boundary.

A deterministic test adds a simulated five-second accounting delay and verifies
that remote timing stays 250 ms. Success/failure are separated; receipt replay
does not emit a fresh remote-call timing. No prompts, credentials or raw responses
are added to operational records.

The offline [measurement guide](../../services/research-api/latency-measurement.md)
documents exact per-operation p50/p95/max summaries, remote versus total attempt
durations, error separation, input bounds and missing queue/first-evidence signals.
Do not sum overlapping graph/node/attempt durations. Live completion optimization
still needs representative records; tests cannot establish provider speed.

## Rollout and rollback

Restart updated API processes to start the bridge; use the same configured Redis
service across replicas. Restrict Redis access and permit publish/subscribe only
for `research:event-wakeups:v1` (plus required client connection commands). Do not
expose Redis to browsers. The existing `REDIS_URL` remains private configuration.

No hosted configuration was changed by this patch. To disable Redis hints, set
`SSE_REDIS_WAKEUPS_ENABLED=false` and restart. Local commit wake-ups still work;
cross-process freshness returns to periodic PostgreSQL polling. Existing event
rows, cursors and run accounting are unchanged in either mode.

## Authorized live checks — 2026-10-16

Exactly three Focused checks used the configured real OpenAI/Tavily services,
with local PostgreSQL, Redis, object storage, durable dispatch and checkpoints.
Each retained the existing six-operation/source ceiling and 180-second active
limit. No hosted research records were created or changed. Isolated local
benchmark tenants, reports, evidence and ledger records remain for inspection.

| Check | Execution | First source from creation | Sources | Verified findings | Answer quality |
| --- | ---: | ---: | ---: | ---: | --- |
| Event delivery comparison | 21.32 s | 8.88 s | 5 | 2 | partial |
| Checkpoint/retry comparison | 30.48 s | 18.49 s | 6 | 0 | insufficient evidence |
| Evidence verification comparison | 16.07 s | 6.50 s | 6 | 0 | insufficient evidence |

All three executions completed; that is **not** three useful answers. The second
check had three 10-second pre-dispatch connection failures followed by safe
bounded retries. Its ledger still recorded six budgeted provider operations.
No verification rule, budget, reflection limit or timeout was loosened.
Ledger-estimated spend across the three runs was $0.147824, not verified billing.

Remote model-call medians by check were 5.07 s, 4.45 s and 3.36 s; the corresponding
enclosing attempt medians were 5.09 s, 4.48 s and 3.39 s. On local persistence,
accounting was therefore small relative to SDK/network time. These are three
calls per check, not stable model p95s. Do not generalize local persistence to
the production database, or claim a before/after speedup from historical logs.

A separate, read-only probe of the configured remote database observed a cold
tenant transaction plus `SELECT 1` at 2,972.53 ms, and five warm transactions at
766.69 ms median. That includes connection/pool, tenant setup, query and commit;
it is not pure network RTT or a measured region-placement diagnosis.

Collection setup now reuses one transaction for its budget/source/concurrency
reads instead of opening a second consecutive tenant scope. Queries, tenant
predicates, per-task cancellation checks and worker bounds are unchanged. A
read-only transaction-shape comparison (three pairs, same two `SELECT 1`s) measured
1,465.83 ms median with separate scopes versus 889.77 ms combined. This validates
the round-trip rationale, not the actual report's end-to-end gain. The worker
regression first failed with two setup transactions and passes with one for all
three modes. Paid checks were not repeated after this final consolidation.

Further work should investigate evidence yield and the configured API/database
connection path before changing model policy or claiming production speed. No
database relocation, deployment, new model, extra paid run or hosted setting was
authorized or performed by this patch.

The opt-in `scripts/benchmark_focused.py` harness refuses paid calls without
`--confirm-paid`, rejects non-loopback persistence/broker destinations (including
URL query overrides), and retains normal budgets. Review the explicit workload
and obtain approval before reusing it: the flag is not standing spending consent.
