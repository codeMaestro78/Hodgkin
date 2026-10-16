# Bounded Reflection

Current runtime inspected 2026-10-17. See the
[baseline inventory](./implementation/research-mode-baseline-inventory.md) for
graph compatibility, migration history, and validation evidence.

## Observed current behavior

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

## Proposed behavior, gated separately

The [research-mode plan](./implementation/research-modes-and-comprehensive-reports-plan.md)
proposes bounded repair driven by uncovered plan dimensions or material
contradictions, with assessment basis and remaining operation/time/cost limits.
Those capabilities are not implemented by the current retry predicate.
Source links alone do not establish requirement satisfaction or independence.

Future changes must preserve one LangGraph engine and the existing exact-span
and semantic evidence gates. Null/absent mode means legacy; historical runs and
report bytes receive no mode backfill. Explicit Deep retains its identity under
a small budget. `answered` remains unavailable under `evidence-links-v1`.
This documentation change enables none of the proposed runtime behavior.
