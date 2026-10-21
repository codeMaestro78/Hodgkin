# Reliability

## Current implementation

Read [durable runtime](./implementation/durable-runtime.md) for milestones 4–8,
exact guarantees, migration 0007, deployment requirements and limits. This is
local-tested implementation, not a production or live-provider certification.

## Implemented bounded slice (2026-10-13)

Follow-on implementation (2026-10-14): extraction URLs now pass transactional
admission before fetching, and a privileged accounting CLI exposes unresolved
reservations. See [extraction admission](./implementation/extraction-admission.md)
for exact semantics, migration 0006, validation and hosted-rollout requirements.
The earlier persistence-only extraction caveat below is superseded by that phase.

The sections below describe architectural targets unless explicitly confirmed
here or in the durable-runtime runbook. The API now drains durable PostgreSQL
jobs with leases and checkpoints. A global provider semaphore and circuit-breaker
rollout are still not implemented.

- OpenAI SDK retries are explicitly disabled. The model boundary owns at most
  three attempts (`PROVIDER_MAX_ATTEMPTS`, 1–3), retrying only 429 rejection or
  recognizable connect/pool failures before dispatch. Read/write timeouts and
  ambiguous 408/409/5xx outcomes are not automatically retried. Each OpenAI attempt
  has its own committed reservation and ProviderCall receipt. One model client is
  owned/closed by the parent run and inherited by graph child tasks.
- Tavily retries only recognizable pre-dispatch connect/pool failures, with
  bounded jitter. It does not retry HTTP failures or ambiguous dispatched calls.
  Its shared worker client has a finite timeout. A pre-dispatch retry stays in
  the same reservation because it did not execute another provider operation;
  transport attempt numbers are logged separately.
- Reservation admission locks budget/usage before duplicate detection. Existing
  attempts cannot authorize redispatch. This blocks repetition; it is not durable
  result replay or proof that a provider will never bill an ambiguous operation.
- Model token admission uses a UTF-8-length heuristic, not an exact tokenizer
  bound. Both larger and smaller actual usage are recorded. Usage exceeding the
  admitted budget is committed and then fails closed before further calls.
- Standard text pricing for the default GPT-4o-mini model is versioned in
  `pricing.py`; received token counts reconcile its estimate. Unknown models retain
  a labelled $0.10 policy estimate, and Tavily retains $0.008 operation estimates.
  These are not invoices: unsupported model prices, tier/tool fees, and purchased
  Tavily credit prices are not verified billing. There is no billing guarantee.
- Ambiguous calls retain reservations. `reconcile_from_receipt` can settle only
  from an existing tenant-scoped successful call receipt and is idempotent. There
  is no automatic stale-reservation refund or provider-receipt retrieval job.
- Successful Tavily calls settle before response-artifact I/O. Storage failure
  is logged and cannot hide spend. Invalid source URLs/individual evidence-artifact
  failures do not poison healthy sources. Database failures still fail closed.
- Existing graph allocations bound requested search/extract results. A retained
  run-row lock now also bounds persisted sources (6/12/20 presets; two for quick
  explainers), independently of overlapping ingestion. This persistence guard is
  not a cross-process extraction-slot allocator: overlapping invocations may
  fetch pages later rejected at persistence. Source and outbox locks remain.
- Cancellation is checked before search, between search/extraction, before source
  storage, before retry attempts, and under the source-persistence lock. Requested
  cancellation observed by a model node is terminalized at the graph boundary;
  already completed/failed runs are not regressed. Already dispatched calls may
  finish and remain accounted. A cancelled `to_thread` upload may still complete;
  orphan-artifact retention cleanup and durable cancellation are separate work.

Call outcome enums remain `pending/succeeded/failed/uncertain`; a known rejection
is a failed call with a released reservation. An invalid successful HTTP response
is a failed call with a consumed policy charge, not usable evidence.

File-level scope and acceptance gates: [core reliability slice](./implementation/core-reliability-slice.md).

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

## Inbound request limits

The research API uses an atomic Redis fixed-window counter shared by API
replicas. Authenticated BFF requests are bucketed by the verified account ID;
other requests use a hash of the bearer credential or the direct peer address.
Identity values and credentials are never stored in Redis keys or rate-limit
responses. Current defaults are 120 general requests/minute, 30 mutations/
minute, 4 research starts/retries/follow-ups/approvals per minute, and 300
Razorpay webhook deliveries/minute. Health probes and `OPTIONS`/`HEAD` are
exempt. `HTTP_RATE_LIMIT_*` settings can tune these ceilings.

Over-limit requests receive `429` with `Retry-After` and `RateLimit-*` headers.
If Redis is unavailable, safe reads fail open; state-changing requests,
research starts, billing checkouts, and Razorpay webhooks fail closed with `503`
so provider spend or account changes cannot bypass the limiter. Redis must be
reachable by every API instance. These request limits complement, but do not
replace, per-tenant queue caps, billing admission, provider-operation budgets,
or edge-level DDoS protection. The limits are starting defaults, not a measured
production capacity guarantee.

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
