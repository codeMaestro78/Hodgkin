# Agent / Node Roles

Per-node contracts for every LangGraph node. See
[langgraph.md](./langgraph.md) for how these are wired together and
[research-workers.md](./research-workers.md) for the specialized worker
roles a `research_worker` invocation may take on.

## Supervisor / Planner

```text
Name:            planner (initial) / planner_delta (bounded follow-up)
Purpose:         Decompose the normalized question into orthogonal, checkable sub-questions
Inputs:          normalizedQuestion, reportRequirements, (delta only) materialGaps
Outputs:         SubQuestion[] (schema-validated)
Responsibilities: Determine whether clarification is required; decompose into
                 3-8 (initial) / up to 4 (delta) non-overlapping sub-questions;
                 specify required source classes and freshness; set provider
                 hints without forcing a provider; prevent duplicate/overly
                 broad tasks
Tools:           Structured-output LLM call
State access:    Read: normalizedQuestion, gaps. Write: subQuestions (append-only, new IDs)
Allowed side effects: None outside its own output
Failure modes:   Structured-output parsing failure
Retry policy:    Retry once with validation error appended, then fail run safely
Budget:          maxSubQuestions = 8 initial, 4 per delta round
Security:        None (no external content yet)
```

## Provider Router

```text
Name:            provider_router
Purpose:         Choose the cheapest suitable provider for a sub-question
Inputs:          SubQuestion, remaining budget, permissions
Outputs:         Provider choice (serper | tavily | parallel | browser)
Responsibilities: Apply deterministic routing rules first; call Jev in one
                 batched call for ambiguous judgments (Choice: provider;
                 Score: expected complexity; Noul: fresh-news required;
                 Noul: multi-hop synthesis required; Noul: known URLs need
                 browser rendering); apply budget/permission constraints last
Tools:           TypeSafe AI Jev (batched), deterministic rule table
State access:    Read only
Allowed side effects: None
Failure modes:   Low-confidence Jev output
Retry policy:    Fall back to Tavily or a deterministic rule, not another LLM loop
Budget:          Counted against maxSearchCalls once a provider is actually called
Security:        None
```

Full routing table: [provider-routing.md](./provider-routing.md).

## Research Workers

```text
Name:            research_worker
Purpose:         Discover and fetch sources for exactly one sub-question
Inputs:          SubQuestion, run_id, remaining local budget, provider adapter
Outputs:         WorkerResult { sources[], rawContentRefs[] }
Responsibilities: Call the routed provider adapter; store raw responses in
                 object storage (never in graph state); return typed results
Tools:           One provider adapter per invocation
State access:    No direct write access to ResearchState; returns typed
                 result merged by a reducer
Allowed side effects: Object storage writes (raw content); provider API calls
Failure modes:   Provider timeout, empty results, malformed content
Retry policy:    Bounded retry with backoff at the adapter layer, then
                 circuit-break/escalate per routing table
Budget:          maxSourcesPerSubQuestion = 6; local slice of maxSearchCalls
                 and maxBrowserSessions
Security:        Treats all fetched content as untrusted (see prompt-injection.md)
```

A `research_worker` invocation receives **only its own sub-question and a
limited run context** — not the full accumulated conversation. See
[research-workers.md](./research-workers.md) for specialized role
definitions (official-source, recent-news, technical-documentation,
academic, contrarian) and dynamic-creation rules.

A CrewAI-backed worker may define a role/goal/backstory/tools/structured
task output internally, but from the parent graph's perspective it is
still exactly one LangGraph node, returns exactly one typed `WorkerResult`,
and cannot directly mutate global state.

## Distiller

```text
Name:            distiller (part of distill_and_verify)
Purpose:         Convert raw source content into atomic evidence candidates
Inputs:          One source chunk, or a small batch of related chunks
Outputs:         EvidenceClaim candidates with evidence spans (unverified)
Responsibilities: Canonicalize, classify, normalize, deduplicate, chunk,
                 extract atomic claims with spans and source locators
Tools:           LLM extraction call
State access:    Read: normalized source content. Write: candidate claims (unverified)
Allowed side effects: None
Failure modes:   Malformed extraction, missing span offsets
Retry policy:    Retry once with validation error, then mark source as
                 "distillation failed" for audit
Budget:          Bounded by chunk size / token limits per call
Security:        Content is untrusted; distiller must not follow embedded
                 instructions in source text
```

The distiller cannot write prose for the final answer — its only output is
structured evidence candidates.

## Verifier

```text
Name:            verifier (part of distill_and_verify)
Purpose:         Decide which candidate claims may enter the writer's context
Inputs:          EvidenceClaim candidates, normalized source text, source metadata
Outputs:         EvidenceClaim records with support classification and Citation records
Responsibilities: Exact-span check; domain/source-identity check; semantic
                 support classification; freshness check; contradiction
                 detection; source-quality scoring
Tools:           Deterministic span matcher + semantic-entailment model/Jev
State access:    Read: candidates, sources. Write: evidenceClaimIds, gaps (partial)
Allowed side effects: None
Failure modes:   False negative (rejects a valid claim), false positive
                 (accepts an unsupported claim)
Retry policy:    N/A — deterministic + single-pass semantic check; failures
                 route the claim to "insufficient" support, not a retry loop
Budget:          N/A (bounded by upstream claim volume)
Security:        Enforces that unverified claims never reach the writer
```

Full detail: [citation-verification.md](./citation-verification.md).

## Reflector

```text
Name:            reflector
Purpose:         Decide whether more research is needed
Inputs:          Plan, compact claim ledger, contradiction ledger, gaps, budget
                 (NOT raw pages)
Outputs:         ReflectionDecision { decision, coverageScore, materialGaps[],
                 expectedMarginalGain }
Responsibilities: Measure coverage against the research plan; identify up to
                 4 material gaps; recommend continue / synthesize / incomplete
Tools:           LLM/Jev judgment over the compact ledger
State access:    Read only (ledger, gaps, budget)
Allowed side effects: None
Failure modes:   Overconfident "synthesize" on thin evidence; runaway "continue"
Retry policy:    N/A
Budget:          Its own recommendation is always subordinate to deterministic
                 hard limits (see reflection.md)
Security:        None (operates on internal ledger, not raw content)
```

Full detail: [reflection.md](./reflection.md).

## Writer

```text
Name:            writer
Purpose:         Produce the citation-grounded report
Inputs:          Report outline, verified EvidenceClaim records + Citation metadata
Outputs:         Draft report (markdown), with every factual paragraph
                 referencing claim IDs
Responsibilities: Synthesize prose strictly from verified evidence; never
                 fetch sources itself; acknowledge conflicting evidence and
                 unresolved gaps
Tools:           LLM generation call
State access:    Read: evidenceClaimIds (verified only), gaps
Allowed side effects: None (a deterministic post-processor converts claim
                 IDs to citation markers)
Failure modes:   Citing an unknown/unverified claim ID, omitting required sections
Retry policy:    Bounded retry on quality_gate rejection (see quality_gate)
Budget:          maxOutputTokens
Security:        Cannot execute tools; operates on already-sanitized evidence
```

## Quality Gate

```text
Name:            quality_gate
Purpose:         Final enforcement before a run is marked completed
Inputs:          Draft report, evidence ledger, citation ledger
Outputs:         Pass -> final report; Fail -> retry writer (bounded) or fail run
Responsibilities: Every citation resolves to a stored source; every cited
                 claim is verified; no search-result snippet presented as a
                 primary source; conflicting evidence acknowledged; required
                 sections exist; no unsupported confidence claimed; markdown
                 is safe to render
Tools:           Deterministic checks + citation-ID resolver
State access:    Read: draft report, evidence/citation ledger. Write:
                 finalReportArtifactRef, status
Allowed side effects: Persist final report (versioned compare-and-swap)
Failure modes:   Repeated writer failures against the same gate check
Retry policy:    Bounded writer retry, then fail run with errorCode
Budget:          Counts against overall run budget
Security:        Last line of defense against citation hallucination
```

## Dynamic worker creation rules

- Worker roles are created **only** when required by the plan — do not
  instantiate all specialized roles for every run.
- Creation is plan-driven: the `planner`/`planner_delta` decides which
  `sourceClasses` a sub-question needs, and the dispatcher maps that to a
  worker role (see [research-workers.md](./research-workers.md)).
- Total sub-questions (and therefore total workers per round) is bounded
  by `maxSubQuestions`; nothing may create workers outside this bound.
