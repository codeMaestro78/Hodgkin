# Evaluation

The quality benchmark that turns framework choices into measured
engineering decisions rather than résumé keywords. See
[testing.md](./testing.md) for how this fits into the broader test
strategy.

## Benchmark

At least **60 questions**, across:

- Technical documentation comparison
- Current-event research
- Product and company research
- Academic literature synthesis
- Conflicting evidence
- Questions intentionally lacking sufficient evidence

The last category exists specifically to test that the system correctly
returns `decision: "incomplete"` (see [reflection.md](./reflection.md))
rather than fabricating confident coverage.

## Metrics

| Metric | What it measures |
|---|---|
| Claim precision | Fraction of report claims that are actually supported by their cited evidence |
| Citation correctness | Fraction of citations that pass exact-span + semantic verification |
| Citation completeness | Fraction of factual statements in the report that carry a citation |
| Source authority and diversity | Distribution of `sourceClass`/`qualityScore` across cited sources |
| Contradiction recall | Fraction of known conflicting evidence pairs the system actually surfaces |
| Answer completeness | Coverage of the question's `successCriteria` in the final report |
| Unsupported-claim rate | Fraction of distilled claims that fail verification (lower isn't always better in isolation — pair with claim precision) |
| Mean and P95 latency | End-to-end run duration |
| Tokens and cost per completed report | From `usage.inputTokens`/`outputTokens`/`estimatedCostUsd` |
| Provider routing accuracy | Fraction of tasks routed to the provider that was actually optimal in hindsight |
| Recovery after injected worker/provider failures | Whether the run completes correctly despite injected faults (see [testing.md](./testing.md#failure-injection)) |
| SSE replay correctness | Whether a simulated disconnect/reconnect reproduces the same final event history |

## Ablations

| Ablation | Question answered |
|---|---|
| Supervisor-worker vs. sequential | Does the parallel topology actually improve latency/quality enough to justify its complexity? |
| Reflection disabled vs. one round vs. two rounds | What does bounded reflection actually buy, per round? |
| Serper-only vs. Tavily-only vs. routed providers | Does the routing policy outperform naive single-provider strategies? |
| Jev routing vs. deterministic routing | Does the typed-judgment layer improve routing accuracy enough to justify its cost/latency? |
| CrewAI worker vs. plain LangGraph worker | Does CrewAI's role/goal/backstory framing improve worker output quality? |
| Raw-source context vs. distilled-claim context (for the writer) | Does the evidence-first pipeline actually improve claim precision over naively summarizing raw pages? |

Each ablation should be run against the same 60-question benchmark with
the same metric set, so results are comparable across runs — see
[testing.md](./testing.md) for how these are wired into CI/eval tooling.

## Minimum viable benchmark

Per the blueprint's phased plan, the first credible release ships an
evaluation dashboard with **at least 20** benchmark questions (a subset of
the eventual 60), sufficient to catch regressions in claim precision and
citation correctness before the full benchmark is built out — see
[deployment.md](./deployment.md) and the twelve-week plan referenced
there.
