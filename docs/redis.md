# Redis

Redis provides **ephemeral coordination only**. See
[database.md](./database.md) for the durable state store it deliberately
does not replace.

## What Redis is used for

Implemented: optional cross-process **event wake-up hints** in
`services/research-api/src/research_api/events/wakeups.py`. They publish only
after PostgreSQL commit and contain tenant/run UUIDs, not research content.
One shared publisher/subscriber pair per API process uses at most two connections
and a 1,024-entry coalescing queue; no Redis operation is awaited by a database
writer. PostgreSQL replay and periodic polling remain sufficient for correctness.
Disable the bridge with `SSE_REDIS_WAKEUPS_ENABLED=false` if necessary.

The following table describes broader architecture targets, not confirmation
that every Redis coordination mechanism is implemented:

| Use | Detail |
|---|---|
| Rate limiting | Per-tenant and global-per-provider request counters (see [provider-routing.md](./provider-routing.md#rate-limits)) |
| Locks | Mutual exclusion for operations that must not race (e.g., report publish compare-and-swap coordination) |
| Semaphores | Per-run worker concurrency limits, global per-provider concurrency limits (see [langgraph.md](./langgraph.md#concurrency)) |
| Stream cursors | SSE publisher offsets/cursors for fan-out to connected clients |
| Cache | Short-lived caching of cheap-to-recompute, non-authoritative data (e.g., provider health/circuit-breaker state) |
| Coordination | General pub/sub or coordination primitives between backend processes |

## What Redis must NOT be used for

- **The source of truth for run state.** `ResearchState`, `status`,
  `budget`/`usage`, and everything in
  [state-management.md](./state-management.md) is durable in PostgreSQL.
  A Redis restart or eviction must never lose information needed to
  correctly resume or audit a run.
- **The only copy of the event log.** Events are persisted to PostgreSQL
  (via the transactional outbox) before publication; Redis pub/sub, if
  used, is a delivery mechanism on top of that durable log, not a
  replacement for it — see [events-and-sse.md](./events-and-sse.md).
- **Idempotency ledgers that must survive a cache flush.** Request
  fingerprints used for billing/idempotency guarantees belong in
  PostgreSQL; Redis may cache a fast-path check on top, but the durable
  check must not depend on the cache being warm.
- **Long-term user preferences or reusable research memory.** These use
  normal application tables or a LangGraph `store` — see
  [database.md](./database.md#checkpointer-storage).

## Why this split matters

Treating Redis as durable is the single most common way ephemeral-store
architectures silently lose correctness under load or during
infrastructure incidents: an eviction, a failover, or a `FLUSHALL` in a
misconfigured environment must degrade *performance* (more provider calls,
slower rate-limit checks) — it must never corrupt or lose a run's actual
state. This is why architecture invariant #9 in
[agent.md](./agent.md#2-architecture-invariants-non-negotiable) exists.

The Redis container, `REDIS_URL`, and the optional event hint bridge are confirmed.
Other coordination code remains `PLANNED` and cannot become business truth.
