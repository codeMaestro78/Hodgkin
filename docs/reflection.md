# Bounded Reflection

See [agents.md](./agents.md#reflector) for the node contract and
[research-workflow.md](./research-workflow.md#budget-exhaustion) for how
this fits into the overall run lifecycle.

## Why reflection exists

Deep research usually cannot know every information gap before the first
search — some questions only reveal their true sub-structure once initial
evidence comes back. A reflection step lets the system target genuine
coverage gaps with a second, narrower research pass instead of either
stopping too early or asking the planner to guess everything up front.

## Why reflection must be bounded

An unconstrained "research until satisfied" loop is unsafe: it has no
guaranteed termination, no cost ceiling, and no protection against a model
that is never quite "satisfied." Reflection is therefore always
**subordinate to deterministic hard limits** — the LLM/reflector may
recommend continuing, but code makes the final call.

## Reflection inputs

The reflector sees only:
- The research plan (sub-questions and success criteria)
- The compact verified claim ledger
- The contradiction ledger
- Existing `gaps`
- The current `budget`/`usage` snapshot

It does **not** see raw pages or provider payloads — see
[evidence-system.md](./evidence-system.md).

## Reflection outputs

```typescript
const ReflectionDecisionSchema = z.object({
  decision: z.enum(["continue", "synthesize", "incomplete"]),
  coverageScore: z.number().min(0).max(1),
  materialGaps: z.array(ResearchGapSchema).max(4),
  expectedMarginalGain: z.number().min(0).max(1),
});
```

- `continue` — recommend another bounded research round.
- `synthesize` — coverage is sufficient; proceed to the writer.
- `incomplete` — coverage is insufficient but further research is not
  expected to help enough to justify continuing; proceed to the writer
  with gaps acknowledged.

## Coverage score, material gaps, marginal gain

- `coverageScore` — the reflector's estimate of how much of the plan's
  `successCriteria` are currently satisfied by verified claims.
- `materialGaps` — up to 4 `ResearchGap` records, each with a
  `description`, `severity`, and optional `suggestedQuery`.
- `expectedMarginalGain` — the reflector's estimate of how much
  additional verified coverage another round would realistically add.
  Continuing requires this to exceed a configured threshold — a low
  expected gain means further research is not worth its cost even if
  budget remains.

## Delta planning

If the decision is `continue` and hard limits allow it, `planner_delta`
receives the `materialGaps` and produces **up to 4** new `SubQuestion`
records specifically targeting them (not a fresh full re-plan). These are
dispatched through the same `dispatch_workers` fan-out as the initial
round — see [langgraph.md](./langgraph.md).

## Termination

Reflection terminates on **any** of:
- `decision != "continue"`
- `reflectionRound >= budget.maxReflectionRounds`
- Any hard budget limit exhausted (see below)
- `expectedMarginalGain` below the configured threshold

Termination always routes to the `writer`, never silently drops the run.

## Hard limits

| Limit | Default | Enforced by |
|---|---|---|
| `maxReflectionRounds` | 2 | Code, in `route_after_reflection` |
| `maxSubQuestions` (initial) | 8 | Code, in `planner` output validation |
| `maxSubQuestions` (delta) | 4 | Code, in `planner_delta` output validation |
| `maxSearchCalls` | 20 per run | Code, checked before every provider call |
| `maxBrowserSessions` | 2 | Code, checked before every browser session |
| `maxSourcesPerSubQuestion` | 6 | Code, enforced in `research_worker` |
| `maxWallClockMs` | Configurable | Code, checked at node boundaries |
| `maxEstimatedCostUsd` | Configurable | Code, checked against the usage ledger |
| No repeated normalized query within a run | — | Code, via request fingerprint dedup |
| Terminate when marginal coverage gain is below threshold | Configurable | Code, using `expectedMarginalGain` |

These correspond to `BudgetSchema` — see
[state-management.md](./state-management.md#budget).

## Why deterministic code ultimately decides

The reflector (LLM/Jev-assisted) can be miscalibrated — overconfident about
coverage, or stuck recommending "continue" indefinitely. Because
`route_after_reflection` applies `hard_stop` **before** honoring the
reflector's `decision`, the system's worst case is always bounded by
config, not by model behavior:

```python
def route_after_reflection(state):
    decision = state["reflection_decision"]
    hard_stop = (
        state["reflection_round"] >= state["budget"]["max_reflection_rounds"]
        or budget_exhausted(state)
    )
    if hard_stop or decision["decision"] in {"synthesize", "incomplete"}:
        return "writer"
    return "planner_delta"
```

This is the concrete enforcement point referenced by architecture
invariant #7 in [agent.md](./agent.md#2-architecture-invariants-non-negotiable).
