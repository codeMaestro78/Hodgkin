# Bounded Reflection

Current runtime inspected 2026-10-17. See the
[baseline inventory](./implementation/research-mode-baseline-inventory.md) for
graph compatibility, migration history, and validation evidence.

## Legacy behavior (null mode)

The implementation is in
[`graph/builder.py`](../services/research-api/src/research_api/graph/builder.py),
inside `build_graph`: `reflector`, `planner_delta`, and the graph edges.
Reflection runs after collection and before `verifier` and `synthesizer`.
It is a deterministic failed-subquestion retry decision; it makes no model call.

`reflector` reads tenant/run-scoped budget and usage rows, the failed subquestion
count, and preserved source count. It returns only `expand`. Expansion requires:

- Budget and usage rows exist, with at least one failed subquestion.
- `quick_mode` is false.
- `reflection_round < min(1, budget.max_reflection_rounds)`.
- At least two provider operations remain after used and reserved calls.
- Source count is below `source_limit(budget.max_search_calls, False)`.

The persisted budget default is **one** reflection round; code caps expansion
at one even with a larger budget. `max_search_calls` counts provider operations
(search and extraction); the source ceiling is derived from that same field.
These are ceilings, not promised results.

`planner_delta` locks the run and selects the earliest-created failed question.
It creates one child plan and one pending repair question by appending “Focus on
original publications and directly quoted evidence.” (truncated to 1,000
characters). The payload records `repairOf`; checkpointed replay reuses an
existing repair for that question. It increments `reflection_round`. If the run
or failed question is absent, it returns no work.

Expansion routes through `planner_delta`, then `approval_gate` with a
checkpointer, otherwise directly to `research_worker`. When expansion is false,
routing proceeds to `verifier`, then `synthesizer`. Collection uses persisted subquestions and an
internal `asyncio.TaskGroup`, without a `dispatch_workers` node. Initial and
repair work use the same LangGraph engine.

`verifier` checks that preserved sources exist; zero sources raises an error.
Claim publication subsequently requires exact-span and semantic support checks
in synthesis. Reflection does not inspect verified claims, assess contradictions,
or certify coverage. The outer `run_graph` deadline and existing budget,
cancellation, and accounting paths still apply; the reflector predicate itself
does not test every time, token, or cost limit.

## Explicit modes: assessed ledger and bounded repair

New explicit-mode jobs use a v13 graph by default (with separately pinned
Serper and opt-in OpenAlex variants), with automatic bounded repair disabled.
Setting `BOUNDED_GAP_REPAIR_ENABLED=true` pins newly created jobs to the v14
repair-capable variant. Existing v7–v12 explicit jobs keep their original graph
semantics, including whether a repair round is available. Older explicit v6
jobs are rejected rather than silently resuming against a different graph.
Existing legacy v3/v4/v5 compatibility is preserved. See the
[`bounded repair design`](./implementation/bounded-gap-repair-design.md) for
eligibility, reservations, and replay boundaries.

Before paid writing, a tenant/run/plan-bound assessment pins the selected source
identities/hashes, context, writer request, model routes, and coverage plan.
Successful model receipts are replayed through existing accounting; uncertain
dispatches are not retried blindly. The assessment result is write-once.
Publication reuses its admitted findings instead of calling the writer again.
Coverage reviews can establish individual criteria but never an `answered`
report. Optional criterion-review failures preserve verified findings and leave
coverage unassessed; cancellation and lease loss still propagate.

For eligible Balanced and Deep runs without plan approval, the current graph
reserves part of the initial operation/source budget and may run **one** targeted
repair round after base assessment. It searches unresolved gaps, assesses only
new evidence, and preserves the base report if no new verified findings result.
Focused, approval-required, and older jobs do not take this path. The round is
time-bounded and uses the existing reservation/replay rules; uncertain paid
calls are not blindly repeated. Local concurrency, cancellation, and replay
tests have passed on a disposable database, but live quality, cost, and latency
remain unmeasured. Do not present repair as a completeness guarantee.

## Contract shape versus runtime

[`ReflectionDecisionSchema`](../packages/contracts/src/research.ts) declares
`schemaVersion`, `decision` (`continue`, `synthesize`, `incomplete`), `rationale`,
up to four `materialGaps`, and `expectedMarginalGain`. It has no `coverageScore`.
That schema is not the return shape consumed by the current reflector edge.
The generated Python schema likewise does not prove runtime use.

The prior description of verified-ledger inputs, a marginal-gain threshold,
up to four delta questions, a default of two rounds, and
`route_after_reflection` routing to `writer` described intended architecture,
not this implementation. It must not be used as an operational guarantee.

## Release and further-work gates

The [research-mode plan](./implementation/research-modes-and-comprehensive-reports-plan.md)
requires bounded repair driven by uncovered plan dimensions, with assessment
basis and remaining operation/time/cost limits. The current explicit-mode path
implements one eligible round; the legacy failed-task retry remains separate.
Repair of adjudicated contradictions and proof of improved outcomes remain open.
Source links alone do not establish requirement satisfaction or independence.

Future changes must preserve one LangGraph engine and the existing exact-span
and semantic evidence gates. Null/absent mode means legacy; historical runs and
report bytes receive no mode backfill. Explicit Deep retains its identity under
a small budget. `answered` remains unavailable under `evidence-links-v1`.
See the [implementation status](./implementation/research-modes-implementation-status.md)
for local validation and remaining rollout gates. Repository state is not proof
of deployed behavior.
