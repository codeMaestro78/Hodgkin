# Retrieval candidate adjudication rubric — draft v1

This rubric and the accompanying 20 cases are a workload proposal, not human-
adjudicated truth. The benchmark is **not ready for release scoring** until a
frozen candidate pool is reviewed independently by at least two reviewers and
disagreements are adjudicated.

## Candidate relevance

Reviewers receive the question, its explicit requirements, and the candidate's
title, abstract/description, year, and document type. Hide provider, retrieval
method, rank, score, URL, and internal candidate ID. Randomize candidate order
separately for each reviewer. Candidate text may itself identify a publisher;
record that this residual unblinding is possible.

For each candidate, provide an overall relevance label, a short overall reason,
and confidence (`low`, `medium`, `high`). For every requirement, provide a
separate `yes`, `partial`, `no`, or `unclear` label and a short requirement-
specific reason. The offline packet/scorer in
`research_api.retrieval_review` validates that every candidate and requirement
is labeled; do not omit unclear items. Overall labels are:

- `direct`: candidate directly addresses at least one stated requirement with
  enough metadata/abstract evidence to justify inclusion for full-text review;
- `partial`: adjacent or useful context, but does not meet a central constraint;
- `not_relevant`: topical words overlap but the candidate misses the population,
  method, comparator, outcome, date, or other decisive constraint;
- `unclear`: metadata is insufficient to decide.

Do not infer that a paper is methodologically sound, accessible, independent,
or supportive of a final claim from title/abstract relevance.

## Independent review and scoring

Two reviewers label the same deduplicated union candidate pool without seeing
method membership. Report raw agreement for overall labels and each requirement.
Disagreements are adjudicated by a third reviewer; retain the two original
labels and adjudication reason. The scorer requires an independent adjudicator
for each disputed candidate and does not overwrite the original reviews. Never
convert `unclear` into `direct` by majority vote without a recorded rationale.

Compare methods only by replaying their recorded rank lists over that same
candidate pool and same adjudicated labels. Report per case/domain and macro
averages for:

- precision@K (`direct` candidates / retrieved candidates; report `partial`
  separately);
- candidate-pool recall@K (relevant candidates retrieved in top K / all
  adjudicated direct candidates in the frozen pool; not corpus recall);
- requirement coverage@K (requirements with at least one `direct` candidate in
  top K / applicable requirements);
- work-level duplicate and version-repeat rates after K, using verified DOI or
  conservative reviewed identity clusters;
- inter-reviewer agreement and adjudication rate.

Keep candidate accessibility/extraction success, exact-span evidence, verified
citation yield, answer usefulness, latency, provider cost, and total model cost
as separate later stages. Do not call a metadata match an evidence-backed answer.
Do not merge records solely on title similarity. A preprint and its published
version are related versions, not two independent works.

## Freeze and release gates

Before retrieval, freeze the case set, requirements, provider queries, candidate
pool, policy versions, operation/source ceilings, and cost cap. Preserve a hash
of each source receipt and the method-to-rank mapping in a private evaluator
artifact. The reviewer packet must not contain that mapping. Record candidate
pool changes and exclude them from a paired ranking comparison.

The implementation emits a reviewer packet and a separate private map with a
canonical SHA-256 of the full candidate pool. The scorer refuses a pool whose
hash differs from the reviewed version. Generate separate packets with distinct
recorded seeds if reviewer order should differ. Store the private map and raw
reviews outside the repository under access controls; the checked-in fixture
contains no candidate pool or human labels. Raw reviewer disagreements remain
available in their input files, while the score output contains agreement,
adjudicated aggregate metrics, and the frozen pool hash.

Do not enable OpenAlex or add Semantic Scholar to production unless the
independently reviewed evaluation shows improved applicable-domain relevance
and requirement coverage, with citation quality no worse, and cost/latency
within a separately approved margin. A live paid evaluation requires explicit
authorization; this draft authorizes no provider calls.
