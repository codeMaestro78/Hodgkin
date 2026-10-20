# Modes benchmark v1: draft protocol

Status: phase-0 harness foundation only. All 20 gold expectations are DRAFT and await human adjudication. Evaluation owner: repository lead, pending named human acceptance. No reviewer names, reviews, approval, provider quality, or timings are asserted here.

## Scope and reproducibility

cases.jsonl is the fixed 20-question workload; categories cover comparison, factual explanation, current information, academic evidence, conflicting evidence, multiple requirements and insufficient evidence. Its labels are proposed dimensions/answerability, not gold facts. Synthetic receipts are newly authored toy text, contain no downloaded/private material, and need no third-party license. Privacy/licensing review of future real evidence remains pending.

schema.json is the generated offline case/observation schema from scripts/evaluate_modes.py, not an application contract. `legacy-policy.json` archives the values of the original `reports.py` policy at calls 6/12/20, including Deep's historical 8,192-token output ceiling and the original source-file SHA-256 for provenance. Current runtime policy changes do not rewrite these legacy observations. The archived values cover source/candidate/context/question/output ceilings only. They supply NO live quality, latency, cost, active-time or repair measurements. The archive's SHA-256 is recorded; schema/prompt/model/graph snapshot fields explicitly distinguish schemas from policies and unexecuted components.

The replay does not execute LangGraph or the application verifier. Its tiny quote-membership check and frozen authored semantic labels test receipt handling only; production exact-span and semantic gates are unchanged. All modes consume identical toy receipts; mode differences are static ceilings, not evidence of improved research. Synthetic operations count one authored search and one authored extraction, NOT paid calls. Source count is one toy source. An admitted toy statement yields one simulated finding and only partial coverage. No evidence association establishes a dimension. No answered state is available. Null requested mode means legacy-inferred; explicit Deep with small limits must remain Deep. No historical backfill.

## Human adjudication before quality use

1. Assign a named evaluation owner and two independent reviewers with relevant domain expertise. Obtain privacy/licensing approval for real reference evidence. Record conflicts of interest.
2. Before reviewing candidate results, freeze case IDs/questions/requirements, cutoff date, primary and counterevidence references with content hashes, expected core/tail dimensions, answerability, contradiction opportunities, lineage, acceptable uncertainty and per-dimension establishment rules. Create a new version for changed cases.
3. Reviewers independently label each reference and output, blinded to mode/model/provider and randomized in presentation. Record review ID, reviewer identity, timestamp, evidence spans, claim/dimension IDs, rationale and confidence in a separate immutable adjudication artifact. Do not overwrite these draft labels as if human-reviewed.
4. Compare independent labels; second reviewer adjudicates disagreements with explicit reasons. Escalate unresolved domain disputes to the owner; retain both labels and unresolved states. Only accepted, traceable adjudications become gold.
5. Review directness, decision usefulness and information density on anchored 1-5 scales (1: misleading/unusable, 3: useful but material gaps, 5: direct, actionable, supported with no avoidable padding). Match or control answer length, log word counts and compare within task strata. Unreviewed scores remain null.
6. Any LLM judge is supplementary: calibrate against held-out accepted human labels, report disagreement, and freeze judge model/prompt. Never treat it as a correctness oracle.

## Metrics and denominators

Observation ratios carry integer numerator/denominator and null for unmeasured. Zero denominator yields null, never a perfect score. Aggregate by micro counts; include measured-run counts. Partial/unknown/not-established dimensions are not established. Report core/tail coverage separately from quality and execution status.

- claim_precision: supported published factual claims / published factual claims.
- exact_citation_correctness: citations passing exact-span validation / evaluated citations.
- citation_completeness: published factual claims with appropriate citations / published factual claims.
- evidence_attribution: correctly attributed claim-citation links / evaluated links.
- provenance_completeness: sources with required provenance / admitted sources.
- independence_assessment: sources with adjudicated lineage assessment / admitted sources; unknown does not imply independence.
- primary_source_coverage and secondary_source_coverage: required dimensions with that source class / dimensions requiring that class. A larger source count alone is not quality.
- contradiction_recall: detected reference contradictions / reference contradictions.
- disagreement_preservation: material contradictions visibly retained / material contradictions detected.
- unsupported_assertion_rate: unsupported published factual claims / published factual claims (lower is better).
- abstention_calibration: correctly disclosed unanswerable requirements / reference unanswerable requirements.
- Core/tail coverage: independently established dimensions / required dimensions in each tier. Draft dimensions in this bundle are not accepted human gold.
- Failures, provider-operation totals, sources, verified findings, token totals and quality counts remain separate. Ratios must be supplied by traceable evaluators; the aggregator cannot verify self-reported judgments.
- Queue wait, first useful evidence and end-to-end milliseconds require sourced observations; p50/p95 use nearest-rank ceil(p*n), separately per mode. Missing samples stay null. No local CLI timing is provider latency.
- Estimated and settled USD costs stay separate; require billing/accounting references and actual dispatch uncertainty. Cost per established dimension/verified finding uses only observations with settled costs, with missing cost excluded from both numerator and denominator. Report sample counts and incomplete measurement.
- Synthetic exact-citation counters refer ONLY to toy attempted citations, including deliberately invalid input; other quality metrics are unmeasured.

## Release decision remains blocked

Freeze non-inferiority margins and improvement thresholds from an accepted baseline BEFORE inspecting candidate results. No thresholds are invented here. Require 20 matched cases x 3 modes under fixed model/provider/prompt/schema/graph/policy snapshots, accepted human gold and blinded output review, authorized capped live observations, sourced latency/cost, and safety/recovery/idempotency/tenant/cancellation evidence. Compare Balanced vs Focused core coverage on multidimension cases, Deep vs Balanced tail coverage/contradiction recall on relevant cases, and Focused median latency/cost on single-question cases; maintain citation precision and calibrated insufficiency.

This tool aggregates observations; it cannot approve phase 5. Release status is deliberately blocked even if external input claims human reviews/live measurements. Safety receipts, adjudication verification, pre-registration and matched comparisons need a separate reviewed phase-5 gate. --require-release exits 2 while blocked; malformed input exits 1. Default successful offline validation exits 0 and does not mean release approval.

## Commands (from services/research-api, no network)

- uv run --offline python scripts/evaluate_modes.py check
- uv run --offline python scripts/evaluate_modes.py baseline
- uv run --offline python scripts/evaluate_modes.py schema
- uv run --offline python scripts/evaluate_modes.py aggregate --input /absolute/path/observations.json
- uv run --offline python scripts/evaluate_modes.py check --require-release

Commands print JSON to stdout and never write artifacts. baseline.json stores the deterministic 60 synthetic observations and summary. manifest.json hashes cases, receipts, archived legacy policy, rubric, schema and baseline bytes. check recomputes baseline and verifies hashes. Intentional policy/fixture changes require review and explicit refreezing; there are no timestamps or random seeds. Graph execution, runtime replay and migration checks belong to the lead's separate phase gate.
