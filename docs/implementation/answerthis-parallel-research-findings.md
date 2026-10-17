# AnswerThis investigation: observations, inventory and delivery gates

Updated 2026-10-16. Browser observations are not a backend architecture audit.
The original investigation reports one paid query and ten read-only reviewers;
that history is not a repeatable latency distribution.

## 1. Recorded observations, not independently replayed here

Original trace reference: .playwright-cli/traces/trace-1792162230136.*.

- One rerun was followed by ten attach requests sharing a query/startup identity,
  approximately 815 ms apart. Those attach retries are not ten research agents.
- Recorded sequence-numbered SSE exposed sources, a draft, then completion.
  Total 148 seconds; first sources around 38 seconds, draft around 113 seconds.
  Eighteen sidebar polls were separate from the progress stream.
- Four searches, 16 distinct cited sources and 70 citation markers were reported.
  Raw hits, citation markers and distinct sources are different counts.

## 2. Hypotheses and limits

The sequence is consistent with a coordinating harness; it does not establish
all backend concurrency, agent count, index internals or verification procedures.
A large scholarly index may explain breadth, but millisecond dense/hybrid
retrieval is not proven by the browser trace. Nor does it establish exact-span
or independent semantic verification. No comparative verification superiority
is established. Early source previews improve perceived progress, not actual
execution duration by themselves.

Selective extraction of a cited subset is a design recommendation for our
system, not a proven description of AnswerThis internals.

## 3. Current checkout inventory

These are source-level capabilities, not claims of deployment or production SLOs.

| Capability | Actual boundary |
| --- | --- |
| Runtime | PostgreSQL jobs, LangGraph checkpoints, fenced execution, replay guards |
| Reports | Markdown and structured documents; published-version immutability; exact-span and semantic-support checks |
| Controlled sharing | Create/list/revoke capabilities and shared reads in sharing_exports_api.py |
| Backend exports | Persisted version-bound Markdown/BibTeX artifacts and authenticated downloads; PDF/DOCX remain absent |
| Organization | Tenant/owner-authorized projects, saved library items and tags |
| Comparisons | Authorized projections over immutable reports; normalized overlap is not semantic equivalence or a persisted comparison |
| Progress | Watermarked 128-event outbox pages, commit wakeups and optional Redis hints |
| Discovery | Tavily default; experimental Serper route disabled by default and still using Tavily Extract |
| Academic adapters | OpenAlex/Semantic Scholar remain planned |

Refresh using current symbols, not historical line numbers or recalled inventories.

## 4. Measurements versus estimates

[Fresh validation](research-quality-latency-validation.md) records two live-provider,
local-persistence Focused checks: 40.21 and 44.02 seconds total, approximately five
seconds collection, and 22.79 / 25.44 seconds writer time. They produced 11 and
5 verified findings but both reports were partial. These are not CI measurements,
hosted end-to-end latency, or a stable p95.

The previous 25–40-second prediction and fourfold credit saving remain unvalidated
estimates. Discovery cannot eliminate a writer-dominated critical path.

## 5. Concurrency claims to reproduce before changing runtime

- Admission's with_for_update(key_share=True) compiles to FOR NO KEY UPDATE:
  the claimed KEY SHARE double-admit race is not established.
- Budget writes intentionally serialize per run, outside provider I/O.
  Pool starvation requires a workload reproduction, not blanket lock removal.
- SQLAlchemy currently permits five pooled plus ten overflow connections;
  the checkpoint pool has its own bound. Capacity adequacy is not established.
- Ordinary ingestion exceptions are caught. Task setup/finalization failures can
  still escape a TaskGroup; that narrower boundary needs fault injection.
- A sequential dispatcher did block a later tenant behind a held registry row;
  local PostgreSQL observed the wait through `pg_blocking_pids()`. The claim path
  now skips busy registry rows, and a forward-progress test covers the boundary.
- Backoff is already jittered and bounded. SSE releases its transaction before
  yielding/waiting; aggregate subscriber pressure is still unmeasured.

Do not label starvation, lock inversion or retry herds confirmed without a
reproduction of the actual boundary.

## 6. Delivery gates

1. Inventory was refreshed and dispatcher contention was reproduced before the
   narrow `SKIP LOCKED` fix; no pool sizes or enqueue locks changed.
2. Provider identity, durable candidate/shortlist receipts and attempt-aware
   accounting are specified in the [adapter contract](index-first-discovery-adapters.md).
3. A feature-flagged Serper adapter is implemented; Tavily remains the default.
4. One matched local pair measured latency, findings, coverage, host diversity,
   and estimated cost. The Serper arm failed during synthesis, so quality parity
   remains unmeasured; details are recorded in the adapter contract.
5. Add academic adapters or sharded synthesis only when measurements justify them.

The single paid local pair was run under the user's explicit authorization. No
hosted migration or rollout was performed.
