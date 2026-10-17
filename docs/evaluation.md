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

## Live cross-mode runner

`services/research-api/scripts/live_mode_evaluation.py` runs the real graph
(configured model + Tavily) for each `evaluation/modes/v1` case and explicit mode,
and writes `modes-observation-v1` records with `evidence_kind: live_observation`:

```sh
cd services/research-api
uv run python scripts/live_mode_evaluation.py --output /path/outside/repo --max-model-usd 3.00
uv run python scripts/evaluate_modes.py aggregate --input /path/outside/repo/observations.json
```

- It creates a disposable loopback database, migrates it to head, and drops it on exit.
  Hosted database URLs are never read. Only provider keys and model routing come from
  `.env`. Object storage must be the local LocalStack endpoint.
- Before each run it admits work only if settled model spend plus that mode's worst-case
  model cost fits `--max-model-usd`. Worst case is the run token ceilings at the
  configured pricing rate. Tavily credits are recorded per run but not priced.
- Receipts are appended per run, so a re-run resumes without repeating work or
  forgetting spend. Use `--cases` and `--modes` for smoke runs.
- Observations make no quality claims. Dimension states stay `unknown`, and rubric
  metrics and human scores stay null, until blinded human review adjudicates the draft
  gold labels.

## Academic retrieval evaluation

The retrieval benchmark is maintained separately from cross-mode report
evaluation in
[`services/research-api/evaluation/retrieval/v1`](../services/research-api/evaluation/retrieval/v1/manifest.json).
It currently contains 20 draft questions with explicit requirements and a
blinded-adjudication rubric, but no frozen candidate pools or human labels.
It is therefore not a release benchmark. See the
[OpenAlex exploratory results](./implementation/openalex-retrieval-evaluation-2026-10-17.md)
for the 12-question, single-reviewer diagnostic and its limitations. Keep
OpenAlex disabled until the independent, controlled-pool and end-to-end
usefulness gates pass.

The offline packet/scorer is available without provider access. Given a frozen
`retrieval-candidate-pool-v1` artifact containing one shared candidate union and
each method's rank list, create the reviewer packet and protected private map:

```sh
cd services/research-api
uv run python -m research_api.retrieval_review prepare \
  --pool /secure/eval/pool.json \
  --cases evaluation/retrieval/v1/cases.jsonl \
  --packet /secure/eval/reviewer-a.json \
  --private-map /secure/eval/private-map-a.json \
  --seed 31
uv run python -m research_api.retrieval_review prepare \
  --pool /secure/eval/pool.json \
  --cases evaluation/retrieval/v1/cases.jsonl \
  --packet /secure/eval/reviewer-b.json \
  --private-map /secure/eval/private-map-b.json \
  --seed 83
```

Assign exactly one packet to each reviewer. Candidate order is randomized
separately while blind IDs remain stable across the two packets. Their review
records must include the packet's `packetSha256` and follow this shape:

```json
[
  {
    "reviewerId": "reviewer-a",
    "packetSha256": "<packet hash copied from reviewer-a.json>",
    "cases": [
      {
        "caseId": "R01",
        "labels": [
          {
            "blindId": "R01-C<opaque-id>",
            "relevance": "direct",
            "reason": "Short evidence-based rationale.",
            "requirementMatches": {"population": "yes"},
            "requirementReasons": {"population": "The abstract matches the stated population."},
            "confidence": "high"
          }
        ]
      }
    ]
  }
]
```

Repeat a complete label for every candidate in every case. After both reviewers
complete every candidate and requirement, score the same frozen pool; provide a
third-reviewer adjudication artifact if any labels disagree:

```sh
uv run python -m research_api.retrieval_review score \
  --pool /secure/eval/pool.json \
  --private-map /secure/eval/private-map-a.json \
  --packets /secure/eval/reviewer-a.json /secure/eval/reviewer-b.json \
  --reviewers /secure/eval/reviews.json \
  --adjudication /secure/eval/adjudication.json \
  --cutoff 10 \
  --output /secure/eval/score.json
```

The tool writes files with mode `0600`, refuses to overwrite them, binds both
review packets and the private method mapping to the full pool's canonical
SHA-256, and reports
candidate-pool recall rather than corpus recall. The reviewer packet intentionally
omits provider, route, rank, URL, and internal candidate identities; title or
abstract text can still reveal a publisher. This capability does not itself
create a frozen pool, provide labels, make a provider request, or establish
end-to-end answer usefulness.
