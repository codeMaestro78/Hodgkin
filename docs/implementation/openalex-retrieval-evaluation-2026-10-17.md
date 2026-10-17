# OpenAlex discovery evaluation — 2026-10-17

## Decision

**Keep `OPENALEX_DISCOVERY_ENABLED=false` in production.** The current
`academic-lexical-topk-v1` shortlist is deterministic and auditable, but this
evaluation does not support treating its lexical score as a relevance judgment
or as evidence of source independence. On this exploratory workload it did not
improve over OpenAlex's unreranked ordering. OpenAlex's native `rerank=true`
ordering showed a much stronger first-pass match to query constraints, but it
is not yet validated enough to ship as an automatic selector.

Next, build a blinded, independently judged benchmark and compare:

1. OpenAlex default order;
2. the current lexical selector;
3. OpenAlex native reranking;
4. an independently evaluated, requirement-aware reranker if the first three
   leave measurable gaps.

Do not increase `per_page`, the candidate cap, or source ceilings on the basis
of this evaluation. Keep the exact-span and semantic evidence gates unchanged.

## Scope and method

- One actual recent user research question (Event-Driven Microservices vs
  Temporal for high-throughput fintech ledgers) plus 11 constructed,
  cross-domain research questions.
- Domains: clinical outcomes, CRISPR, battery recycling, multi-agent research,
  urban heat and mortality, adolescent social-media outcomes, cement carbon
  capture, remote-work causality, AI tutoring trials, antibiotic stewardship,
  and semiconductor supply chains.
- For each question, retrieved one OpenAlex page of 10 works. The current
  implementation's lexical selector chose up to four from that same page.
- Compared that with the provider's first four from the same ordinary result
  page and a separate OpenAlex `rerank=true` result page, also capped to 10
  before examining the top four. Thus default-vs-lexical holds the candidate
  pool constant; the rerank comparison does not isolate ranking from candidate
  pool changes.
- Metadata-only retrieval. No full-text extraction, model synthesis, Tavily
  calls, database writes, or production setting changes were used.
- 12 queries × 10 records = 120 candidates per ranking condition. Candidate
  pages and API counts are time-sensitive and may change as OpenAlex updates.
- No API key was configured. The benchmark made 22 ordinary searches and 21
  reranked searches, including one rerank request whose response was received
  but not printed after a local harness error. Recorded batch costs total
  $0.062; that unprinted response is estimated at $0.002, for approximately
  **$0.064 total**. This is below OpenAlex's documented $0.10/day no-key
  allowance, assuming no unrelated calls shared that allowance. [OpenAlex
  pricing](https://help.openalex.org/access/example-costs/) documents $0.001
  per search and an additional $0.001 for reranking.

### Relevance rubric

The provisional label is **direct constraint match**: a selected record's
title and available indexed abstract visibly address a central population,
method, outcome, or comparator stated in the question. Mere domain overlap is
not enough. A source can be topically relevant but fail this label—for example,
a remote-work study without a causal design when the question explicitly asks
for causal evidence.

This is an exploratory, single-reviewer assessment, not a gold-standard
relevance judgment. The review was not blinded to ranking, and the reviewer did
not inspect full papers or independently verify study methods. Treat the
numbers below as diagnostic signals, not publishable model-quality metrics.

## Results

### Top-four direct constraint match

| Workload | OpenAlex default top 4 | Current lexical top 4 | OpenAlex native rerank top 4 |
| --- | ---: | ---: | ---: |
| Fintech ledger architecture | 0/4 | 0/4 | 0/4 |
| GLP-1 cardiovascular outcomes | 4/4 | 4/4 | 4/4 |
| CRISPR in primary human T cells | 1/4 | 0/4 | 4/4 |
| Lithium-ion battery recycling | 4/4 | 4/4 | 4/4 |
| Multi-agent scientific research | 0/4 | 0/4 | 4/4 |
| Urban heat, adaptation, mortality | 4/4 | 4/4 | 4/4 |
| Adolescent social-media outcomes | 1/4 | 1/4 | 3/4 |
| Cement carbon capture and LCA | 1/4 | 1/4 | 3/4 |
| Causal remote-work outcomes | 0/4 | 0/4 | 1/4 |
| Randomized generative-AI tutoring | 0/4 | 0/4 | 4/4 |
| Hospital antibiotic stewardship | 4/4 | 4/4 | 4/4 |
| Semiconductor supply-chain resilience | 3/4 | 2/4 | 4/4 |
| **Total provisional direct matches** | **22/48 (45.8%)** | **20/48 (41.7%)** | **39/48 (81.3%)** |

The native reranker had at least one direct-match candidate for 11 of 12
questions; the current lexical selector did for 7 of 12. The fintech
head-to-head question is an important shared failure: none of the three
top-four lists supplied a direct comparison of Temporal against event-driven
microservices in a ledger workload. The system must say this evidence gap is
unanswered, not fill it by combining unrelated vendor or architecture claims.

Examples that explain the difference:

- For the CRISPR question, lexical selection included a plant-editing paper and
  papers on adjacent human cell types. Native reranking put papers explicitly
  about off-target analysis and primary human T cells in its first four.
- For multi-agent research, lexical selection favored chemistry, software
  engineering, and generic autonomous-agent surveys. Native reranking surfaced
  an empirical systematic-literature-review agent paper, an empirical study of
  multi-agent automated research, and evaluations of autonomous research
  systems.
- For AI tutoring, the lexical top four had no clear randomized trial. Native
  reranking put randomized or field-experiment studies of generative-AI
  tutoring and student outcomes at the top.
- For remote work, lexical ranking matched productivity and satisfaction terms
  but missed experimental/causal design. Native reranking surfaced a field
  experiment and causal-effect studies; only one of its four was credited under
  the deliberately strict causal-evidence rubric.
- For semiconductor supply-chain research, lexical ranking displaced a direct
  semiconductor supply-chain result with more generic geopolitical/supply-chain
  overlap. Native reranking kept the first four focused on semiconductor
  resilience.

OpenAlex documents `rerank=true` as a model that reorders the top 100 using
title, venue, year, and type, with a `rerank_score`; reranking adds $0.001 per
search. That is a useful candidate-ordering feature, not an independent
relevance certification. The score must not be presented as factual confidence
or used to bypass evidence verification. [OpenAlex search and reranking
documentation](https://help.openalex.org/api/searching/).

### Useful-source coverage and what remains unmeasured

The top-four counts above test metadata-level constraint matching only. They do
**not** establish that a source is accessible, has extractable full text,
contains a passage supporting a claim, survives claim verification, or improves
the final report. In particular, current counts do not measure:

- useful extracted-source yield or exact-span coverage;
- claim-level citation precision/recall or answer quality;
- recall over the OpenAlex corpus (one page of ten cannot establish recall);
- performance against Tavily/Serper under equivalent extraction and budgets;
- source independence or publisher/journal quality;
- quality on a statistically sampled distribution of actual customer queries.

Therefore “useful-source coverage improved” remains **unproven end-to-end**.

### Diversity, duplicates, and independence

Venue labels were often varied within a shortlist, but venue count is not an
independence measure. The native top-four sets included a four-record arXiv
cluster for the multi-agent query, repeated Cochrane review titles for
antibiotic stewardship, and a same-title urban-heat work exposed through more
than one publication/location record. The lexical social-media shortlist also
contained two same-title records. These are concrete examples where source-row
count can overstate independent work count.

DOI/OpenAlex-ID deduplication did not collapse all same-title/version cases.
Before using source diversity as a quality signal, evaluate work-level
relationships with a conservative title/author/year/version clustering step;
retain versions and provenance, but avoid counting obvious manifestations of
the same work as independent corroboration. Do not automatically merge records
solely on title similarity.

The source set also included articles, preprints, dissertations, repository
records, and venues with widely varying apparent standing. OpenAlex metadata
alone does not validate peer review, methods, publisher identity, or factual
reliability. A separate source-type/quality policy needs explicit provenance
and must not silently exclude legitimate theses, preprints, or non-English
work.

### Latency and cost

| Measurement | Ordinary search + local lexical screen | Native rerank search |
| --- | ---: | ---: |
| Requests in measured batch | 12 | 12 |
| Median observed request+processing time | 1.05 s | 1.36 s |
| Observed range | 0.54–1.89 s | 1.03–2.14 s |
| Reported cost per request | $0.001 | $0.002 |

These are short serial API checks from one machine, not service SLOs or
end-to-end research latency. In this sample, native reranking cost an additional
$0.001 per request and had a median about 0.31 seconds slower; more repetitions
and concurrent workloads are needed before making a latency/cost trade-off
claim.

## Implementation findings

1. The current lexical feature is useful as an **auditable ordering signal**,
   not a relevance gate. A score above zero only means token overlap; this run
   shows that overlap does not imply the decisive method/population/comparator
   is covered.
2. Search one plan dimension at a time. Avoid scoring a compound root query as
   one bag of words. Persist each dimension's must-match entities, population,
   method/design, outcome, comparator, date bounds, and acceptable source
   classes.
3. Compare default and native reranking behind a separate experiment route.
   Persist both orderings and scores in the private receipt, while making the
   chosen ordering deterministic on replay. Do not change the production route
   until blinded adjudication and extracted-evidence outcomes pass gates.
4. Add candidate-level labels for `direct`, `partial`, and `off_topic`, plus
   separate fields for full-text availability, study design, work type, venue,
   and duplicate/version cluster. Never collapse these into one opaque score.
5. Preserve exclusion reasons. A hard no-overlap exclusion can discard
   synonyms and domain vocabulary; broaden candidate discovery or use concept
   expansion before discarding. A reranker should rank candidates, not decide
   claim support.
6. Track four source counts separately: indexed candidates returned, screened
   candidates, sources with accessible/extracted text, and sources cited by
   verified findings. Do not label all four as “sources found.”

## Next evaluation gate

Before enabling OpenAlex by default:

1. Build a frozen set of at least 50 de-identified, representative questions
   across at least six research domains, with 2–5 explicit requirements per
   question and hard/easy/ambiguous strata.
2. Retrieve and pin a common bounded candidate pool, then compare default and
   lexical ordering on that pool. Evaluate native reranking both on the common
   pool (if the API supports that protocol) and in its native retrieval mode;
   pin API request, timestamp, result IDs, versions, costs, and ordering. Do
   not compare different candidate pools as if only ranking changed.
3. Have two reviewers independently judge a blinded sample (ranking/provider
   hidden), resolve disagreements, and report agreement. Use `direct` /
   `partial` / `off_topic`, plus study-design, population, outcome, and
   comparator match.
4. Report macro and micro precision@4/10, nDCG@4, requirement coverage,
   duplicate/version rate, venue concentration, extracted-source yield,
   verified-claim support, latency p50/p95, and per-run cost. Report confidence
   intervals and per-domain breakdowns; do not average away a domain failure.
5. Use paired tests and preregistered gates. Suggested initial gate for
   discussion: no statistically meaningful drop in direct precision@4 versus
   default order, and a material uplift in requirement coverage and
   verified-source yield. Final thresholds require product/research-owner
   agreement before scoring.
6. Only then run a small, explicitly authorized live end-to-end canary. Keep
   the default disabled until the canary shows stable extraction, citation
   verification, cost, and latency with a rollback switch.

## References

- [OpenAlex Search, relevance scores, and reranking](https://help.openalex.org/api/searching/)
- [OpenAlex API authentication, budgets, and rate limits](https://help.openalex.org/api/authentication/)
- [OpenAlex example costs](https://help.openalex.org/access/example-costs/)
- [Local adapter and screening implementation](../../services/research-api/src/research_api/providers/openalex.py)
- [Local lexical candidate-screening policy](../../services/research-api/src/research_api/providers/candidate_screening.py)
- [Academic retrieval and research canvas plan](academic-retrieval-and-research-canvas-plan.md)
