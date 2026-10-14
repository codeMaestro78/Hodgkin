# Mode-specific research reports — 2026-10-14

## Verified problem

The supplied logs show the Focused run `41e55c1e-0fed-4c5e-9498-b0233f068091`
completed with eight candidate claims and four verified findings. Its linked
follow-up completed with eight candidates and three findings. These are live
successful-run observations, not evidence that all recovery/race/latency gates
have been exercised. A full-graph regression reproduced the short-report issue:
publication discarded draft structure and persisted only findings/limitations.

## Implemented policy

| Mode | Planned questions, maximum | Source extracts, maximum | Candidate findings, maximum | Evidence character allowance | Draft output-token allowance |
| --- | --- | --- | --- | --- | --- |
| Focused | 3 | 6 | 12 | 12,000 | 4,096 |
| Balanced | 4 | 12 | 24 | 18,000 | 6,144 |
| Deep | 6 | 20 | 40 | 24,000 | 8,192 |

These are capacity ceilings, not a minimum word count, guaranteed source count,
or guaranteed published-claim count. Custom lower provider-call budgets still
bound planning/source selection. Run-level token, cost, source and active-time
caps are unchanged. The private model boundary now honors an explicit bounded
output allowance up to 8,192; unspecified calls retain 4,096. Reservations and
settlement use that allowance, so deeper drafting cannot bypass usage admission.

Research modes use one structured candidate-drafting call, followed by exact
source quotation filtering and semantic review. Each candidate has a required,
enumerated section role; candidates themselves are not factual certification.
Quick explanation calls retain their prior draft/audit path.

Only fully supported findings are composed into the report. Sections contain
literal verified claim text and citations, not unchecked prose or an additional
model rewrite. Standard headings cover executive summary, mechanisms/analysis,
comparison, risks/trade-offs, implications, limitations, methodology and sources.
Deep adds scope/evidence boundaries and more detailed section labels. Missing
section evidence is explicitly incomplete; no unsupported recommendation or
fabricated benchmark is inserted merely to make a report longer. Empty reports
remain explicitly limited. Claim provenance records the actual published section.

Evidence selection uses bounded, query-ranked overlapping literal passages, not
the first 3,500 characters of every page. Separate passages have explicit
separators; a fabricated quote bridging them fails the existing full-content
exact-span check. Full source material remains private/local to synthesis, not
LangGraph state. Exact-content deduplication does not prove source independence.

## Compatibility and rollout

Existing completed reports remain immutable; this applies to new runs. No hosted
migration or paid run was started. Update/restart the API and frontend after active
runs have finished. Graph version is now `research-v3`: old pending/recovering v2
jobs fail closed with `graph_version_incompatible`, preserving their evidence
rather than redispatching model calls under a changed report contract. Fresh
attempts use v3. This is deliberately not silent recovery across prompt/schema
changes. The existing incompatibility regression remains part of validation.

## Advanced automation boundary

This report-quality slice does not implement plan editing, browser-action
approval, CSV batch import, timezone/calendar schedules, report diffs or
notifications. Basic approve/reject, line-based batches and interval schedules
already exist. Next slices should be plan revision/editing, CSV validation/import,
timezone/calendar scheduling, then immutable report diffs and in-app notifications.
Browser-action approval requires a real browser provider and constrained action
policy. External email delivery additionally needs configured transport and
notification consent; it must not be simulated by a button.

## Validation

Regression coverage includes mode-specific strict schemas/output admission,
relevant evidence beyond 3,500 characters, 6/12/20-source bundles, published
section structure, durable and legacy graphs for all modes, exclusion of
contradicted assertions, batched FK-safe persistence, receipt replay and budgets.
Frontend section navigation already derives from real Markdown headings; the
composer now explains the different report formats. No unverified word-count
or live latency promise is made.

Validation passed: 383 backend tests, 59 web tests, Ruff, Python and TypeScript
type checks, production web build, and `git diff --check`. The new mode contracts
have not been exercised against paid live providers in this turn.
