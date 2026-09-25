# Reliability

Concurrency, retries, idempotency, and failure handling. See
[langgraph.md](./langgraph.md#concurrency) for the execution-engine side of
this and [observability.md](./observability.md) for how failures are
traced.

## Concurrency

- A **per-run semaphore** bounds concurrent `research_worker` invocations
  within one run (`concurrency_limit`).
- A **global provider semaphore** bounds total concurrent calls to a given
  provider across all runs, protecting shared rate limits (see
  [provider-routing.md](./provider-routing.md#rate-limits)).
- Parallel workers are independently retryable — one worker's failure does
  not cancel or block sibling workers in the same fan-out.
- Use `Promise.allSettled` (or bounded `asyncio.gather(..., return_exceptions=True)`)
  wherever partial results are acceptable. `Promise.all`/unguarded
  `gather` is acceptable only when every task already has independent
  failure capture upstream.
- In the Python LangGraph runtime, prefer graph-native fan-out and
  reducers over hiding concurrency inside one opaque node.

## Retries

- **Structured-output nodes** (`planner`, `distiller`, `writer`,
  `reflector`): retry once with the validation error appended to the
  prompt, then fail the run safely with a typed `errorCode`.
- **Provider adapters**: bounded retry with backoff, then circuit-break
  and escalate per the routing table in
  [provider-routing.md](./provider-routing.md).
- **Node crash**: resume from the last LangGraph checkpoint rather than
  restarting the whole run.

## Circuit breakers

Each provider adapter tracks recent failure rate/latency. On breach, the
adapter opens its circuit (short-circuits further calls to that provider
for a cooldown window) and the router escalates to the next provider in
the routing table rather than repeatedly hitting a failing service.

## Idempotency

| Mechanism | Guarantees |
|---|---|
| Client/server idempotency key on run creation | No duplicate run created on client retry |
| Provider call request fingerprints | No duplicate billed provider call on retry |
| `(run_id, node_id, attempt, output_hash)` uniqueness on node writes | No duplicate/conflicting node output persisted |
| Monotonic run-local event sequence numbers | Safe replay via `Last-Event-ID` |
| Idempotent cancellation | Repeated cancel calls are no-ops once cancellation is in flight |
| Versioned compare-and-swap on report publication | No lost update if two writer attempts race |

## Checkpointing and leases

- LangGraph's checkpointer persists thread-scoped snapshots to PostgreSQL
  (see [database.md](./database.md#checkpointer-storage)).
- A worker lease with expiry detects a crashed worker (missing heartbeat)
  and allows safe reassignment/resume without double-processing.

## Cancellation

Cancellation is idempotent and checked at node boundaries rather than
force-killing in-flight work mid-write, to avoid partial/corrupt evidence
records — see [research-workflow.md](./research-workflow.md#cancellation).

## Worker crashes

Detected via missing heartbeat/checkpoint. Recovery resumes from the last
persistent checkpoint; the reflector treats any sub-questions left
`"running"` past a lease expiry as candidates for retry or as a coverage
gap, not as silently lost work.

## Provider timeouts

Deadline telemetry per provider call feeds both the circuit breaker and
the routing table's escalation path. A provider timeout must never hang
the graph — it always resolves to a typed failure within the configured
deadline.

## SSE replay

See [events-and-sse.md](./events-and-sse.md#reconnect-behavior). Event
sequence gaps are detected via the monotonic sequence number; the client
reconciles via the durable run projection plus `Last-Event-ID` replay.

## Duplicate work prevention

- Provider calls are deduplicated within a run by normalized query
  fingerprint (see [reflection.md](./reflection.md#hard-limits) — "no
  repeated normalized query").
- Source ingestion deduplicates by canonical URL and content hash (see
  [evidence-system.md](./evidence-system.md#distillation-pipeline)).

## State merge conflicts

Reducers merge by stable ID (see
[state-management.md](./state-management.md#reducers)). On a genuine
conflicting write to the same ID from two branches, the merge policy is
last-write-wins by `updatedAt`, and the conflict is logged for review —
this should be rare given that sub-question ownership assigns each ID to
exactly one worker.

## Failure-mode matrix

| Failure | Detection | Mitigation |
|---|---|---|
| Infinite reflection | Round and budget counters | Hard cap plus marginal-gain threshold |
| Context bloat | State-size and token telemetry | External raw artifacts, compact claim ledger, per-worker local state |
| Duplicate queries | Normalized query fingerprint | Reject or merge duplicate work |
| Exponential agent delegation | Child-count and depth limits | Parent-only dispatch; workers cannot spawn without policy |
| Citation hallucination | Citation ID lookup and exact-span check | Reject unknown or unsupported citations |
| Search snippet treated as evidence | Source-type validation | Fetch original page before claim verification |
| Conflicting sources hidden | Contradiction clustering | Present disagreement and source quality |
| Schema-valid nonsense | Semantic/evidence verification | Zod/Pydantic plus verifier and evals |
| Parallel merge overwrites state | Reducer tests | Merge by stable ID with deterministic conflict policy |
| Provider timeout | Deadline telemetry | Circuit breaker, bounded retry, alternate provider |
| Retry duplicates cost | Request fingerprints | Idempotent provider-call ledger |
| SSE disconnect loses progress | Event sequence gap | Persistent event log and Last-Event-ID replay |
| Worker crash loses run | Missing heartbeat/checkpoint | Persistent checkpointer and lease expiry |
| Browser prompt injection | Security classifier and policy logs | Treat web text as data; restricted browser sandbox |
| Stale facts | Publication/retrieval timestamps | Freshness requirements and recency routing |
| CrewAI and LangGraph state drift | Contract tests | Crew adapter returns one typed result; no shared mutable state |
