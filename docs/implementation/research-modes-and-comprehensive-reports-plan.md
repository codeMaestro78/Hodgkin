# Explicit Research Modes and Comprehensive Reports — Implementation Plan

**Status:** Partially implemented locally; this remains the forward plan and acceptance contract. See the [implementation status and validation receipt](./research-modes-implementation-status.md) for the current checkout.
**Plan prepared:** 2026-10-16 · **Current-state review:** 2026-10-17
**Scope:** Focused, Balanced, and Deep research contracts, planning, evidence coverage, report composition, and quality evaluation.  
**Primary goal:** Make the three modes perform meaningfully different, server-enforced research strategies and produce reports whose depth follows the evidence—not merely a larger word count.

This plan is grounded in the checked-out code and the existing implementation notes linked below. It deliberately preserves the current evidence-admission and citation-verification gates. External references inform design choices; vendor-reported benchmark results are not product promises.

## 1. Executive decision

Implement explicit, versioned research modes on the existing LangGraph/PostgreSQL runtime. Keep one orchestrator, one existing run lifecycle, and one evidence-verification path. Add a persisted plan-coverage matrix and an independently evaluated report-quality result. Separate source ceilings from provider-operation ceilings. Compose reports only from verified evidence and visibly unresolved coverage.

Do **not** add CrewAI, a second workflow engine, an unconstrained “research until satisfied” loop, or a minimum word-count target. Consider LangGraph-native `Send` fan-out only after a matched benchmark shows that graph-level visibility or recovery is worth replacing the current persisted-subquestion/worker behavior.

The mode contract is not complete until all three properties are true:

1. The selected mode is explicit in the request and immutable run record; a smaller user budget never silently changes Deep into Focused.
2. The mode changes the planned coverage and bounded effort strategy—not just headings, token ceilings, or UI labels.
3. Matched evaluation demonstrates the intended quality/effort trade-offs while the existing exact-span and semantic evidence gates remain unchanged.

## 2. Current-state audit (verified 2026-10-17)

This section supersedes the original 2026-10-16 inventory. Implementation is local and uncommitted; it is not proof of hosted schema, deployment, or product behavior.

| Area | Current checkout | Remaining gate |
|---|---|---|
| Explicit mode and budgets | Focused/Balanced/Deep, server-owned policy, separate source and operation ceilings, tighten-only overrides, and mode-preserving retry/follow-up are implemented locally. | Hosted migration/deployment not verified; rerun full gates on the release commit. |
| Planning and coverage | Versioned coverage dimensions, criteria, requirement routing, edit validation, and persisted criterion assessments are implemented locally. | Assessments describe the verified ledger, not literature-wide completeness; `answered` remains unavailable. |
| Source identity | Observed DOI/content/publisher relationships are persisted with provenance and tenant-scoped keys, and exposed only when both endpoints are cited by the report. Unknown class/independence stays unknown. | Academic metadata adapters and source-lineage classification remain future work; observed edges do not prove independence. |
| Report contract | Immutable report v3 adds scoped provenance and potential conflict records; immutable report v4 adds an evidence-verified narrative projection. v1/v2/v3 readers remain intact. Conflict nominations require verified claims linked to reviewed criteria and remain unresolved. | Disposable migration/bootstrap and report readers are validated locally; hosted migration/deployment are not. V3/V4 do not adjudicate contradictions or certify completeness. |
| Report composition | Graph `research-v9-evidence-narrative` adds a mode-specific narrative pass (Phase 4): the model orders verified findings into answer/dimension/synthesis/trade-off/implication blocks and may propose new explanatory claims, which publish only after the existing exact-span and fully supportive semantic gate. Rendered text is exact claim text only; there is no free connective prose. | Narrative depth is bounded by verified evidence and remaining time; readability and Deep-mode usefulness are unmeasured until Phase 6. |
| Repair | Bounded one-round repair is implemented locally for eligible Balanced/Deep runs, with base-report fallback and tested admission/cancellation/replay behavior. | Live quality/cost/latency and broad browser acceptance remain open; see the status and repair design documents. |
| Evaluation | A 20-case fixture, rubric, schema, and 60 synthetic observations support offline harness checks. | No live matched 20 × 3 evaluation or blinded human adjudication; Phase 6 remains blocked. |
| Persistence and rollout | Repository migration head is `0019`; disposable PostgreSQL validation through `0018` exercised report snapshots, and `0019` reapplies brief/budget immutability guards on databases that had already run the older `0013`. | Migrations `0016`–`0019` are checkout-only here. Shared local DB status was last recorded at `0015`; target identity, backups, and deployed graph versions remain unverified. Do not run the current app against a database below `0018`; apply `0019` before relying on the strengthened guards. |

The exact validated local commands and receipts are in the [status document](./research-modes-implementation-status.md). Its synthetic benchmark is not live quality or latency evidence.

### 2.1 Original product semantics retained

The mode descriptions and product constraints below remain intended behavior, not evidence that a quality difference has been demonstrated. Budgets are ceilings, not promises of source counts, finding counts, report length, or completeness.

### 2.2 Remaining contract/behavior gaps

| Area | Current behavior | Required change |
|---|---|---|
| Report-level provenance | Implemented locally (Phase 3): report v3+ exposes observed relationships scoped to cited report sources; independence remains unknown. | Academic lineage classification remains future work; observed edges never upgrade independence. |
| Conflicts | Implemented locally (Phase 3): criterion review may nominate potential conflicts among verified claims; report v3+ publishes them as unresolved with both sides. | Adjudication is not implemented; conflicts are never presented as confirmed or resolved. |
| Narrative depth | Implemented locally (Phase 4): report v4 persists ordered narrative blocks whose every sentence references a published claim and its citations; new explanatory claims pass the existing gate. | Human readability and cross-mode usefulness are unproven until Phase 6. No word-count target. |
| Adaptive repair | One bounded round is implemented locally for eligible Balanced/Deep runs without plan approval; Focused, approval-required, and older jobs do not repair. The base report survives a no-gain round. | Validate live quality/cost/latency before wider release; keep concurrent admission, cancellation, and replay gates green. |
| Evaluation | Fixture/rubric and synthetic observations exist, but draft labels are not human gold and measurements are null. | Keep the live 20-question × 3-mode benchmark as a separately authorized, blinded, pre-registered release gate. |
| Product claims | Report depth, Deep superiority, independence, latency, and cost outcomes have not been established. | Do not promise these outcomes until Phase 6 evidence and entitlement checks pass. |

### 2.3 Documentation and compatibility rules

New explicit-mode jobs use v13 criterion-budget graphs with repair disabled by default. Setting `BOUNDED_GAP_REPAIR_ENABLED=true` pins new jobs to v14 repair-capable graphs. Existing explicit v7–v12 jobs retain their pinned graph semantics, including whether repair was available; legacy v3/v4/v5 behavior remains compatibility-sensitive. Repository migration head `0019` is not proof of a hosted revision. Before rollout, inspect the target database and deployed worker compatibility independently. Never edit stored graph versions or reinterpret historical runs to make documentation consistent.

Validation counts in the status document are dated local receipts, not a current test result. Re-run all applicable checks on the exact release commit.

## 3. Product semantics

Modes describe research intent, scope, and report contract. They are not a promise that every run reaches a target number of sources or words.

| Dimension | Focused | Balanced | Deep |
|---|---|---|---|
| User intent | Resolve one concrete question or decision quickly. | Cover the main dimensions of a comparison or explanatory question. | Investigate a broad, high-stakes, academic, or multi-constraint question systematically and transparently. |
| Plan shape | A small set of high-value dimensions; avoid tangents. | Core dimensions plus material risks, context, and counterevidence. | Explicit scope, dimensions, source strategy, uncertainty, and disagreement. |
| Evidence strategy | Efficient, relevant evidence; prioritize primary sources when practical. | Seek evidence across key dimensions and more than one independent evidence lineage when available. | Broader evidence-class coverage, corroboration, contradictory evidence, and explicit gaps. |
| Adaptive repair | At most one narrowly justified repair task/round, subject to remaining budget. | Bounded targeted repair for missing dimensions or material conflict. | More repair capacity, but bounded by server policy, remaining operation/time/cost budgets, and measured marginal value. |
| Report form | Direct answer/decision brief, key supporting findings, caveats, and sources. | Structured report with dimension-by-dimension analysis, comparison table when evidence supports it, trade-offs, implications, limitations, and references. | Full research report with scope/method, organized findings, comparative synthesis, source/independence notes, counterevidence, limitations, unresolved questions, and references. |
| Honest terminal state | State what is and is not established. | Same; unresolved dimensions remain visible. | Same; depth does not authorize stronger certainty or implied completeness. |

These are target semantics. Exact query counts, source targets, worker counts, and repair budgets remain provisional until workload evaluation. Existing ceilings (6/12/20 operation/source-related UI values; report candidate/context/token limits in the mode-specific report document) remain hard upper bounds until separately approved. Do not raise them during this project merely to make a report look longer.

### 3.1 Source independence definition

Different URLs or domains are not, by themselves, independent evidence. Model source relationships with evidence such as canonical URL, publisher/owner, DOI or other work identifier, cited/underlying work, syndication/republication, and dataset lineage when available. Persist relationship confidence and basis. Until sufficient metadata is available, show independence as `unknown` rather than a numeric score or “independent sources” badge. Do not make every Focused claim require two sources; choose corroboration thresholds by claim risk and mode only after evaluation.

### 3.2 What Deep is not

Deep is not an automatic systematic review, exhaustive literature search, PRISMA-conformant process, meta-analysis, peer review, or factual certification. If a dedicated systematic-review feature is offered, it needs its own protocol, databases, screening workflow, exclusions, and reporting compliance. A PRISMA-inspired activity summary must be labeled as a lightweight process record, not PRISMA compliance.

## 4. Target architecture and data contracts

The following sections define acceptance rules for the target system. Several are implemented locally; consult Section 2 and the linked status receipt before treating a requirement as outstanding or complete. They are not evidence of hosted rollout.

### 4.1 Request contract and server-owned policy

The local implementation adds `mode: "focused" | "balanced" | "deep"` to the create-run request in the TypeScript contract and generated Python/API models. New web clients send it. For compatibility, old clients may omit it for a bounded deprecation window; the server resolves those requests through a clearly named `legacy-inferred` policy and records that fact. Do not silently pretend an old run explicitly selected a mode. Retain the rules below as contract acceptance criteria.

The client must **not** select `modePolicyVersion` or specify server-owned repair/source-class/corroboration policy. The server resolves a policy version (e.g. `research-mode-policy-v1`) at admission and persists an immutable snapshot with the run. This avoids a client selecting a weaker/older policy while still making historical behavior reproducible.

#### Explicit mode versus the fast-explainer shortcut

The earlier implementation silently reduced some short evergreen questions to a two-operation fast-explainer budget. The current local explicit-mode contract preserves the selected mode, including Deep, and the status receipt records the relevant regression coverage. Treat any compact fast-answer path as a separate explicit product choice (or legacy-only behavior); never infer a smaller mode from question wording or budget. Re-run the Deep + evergreen end-to-end case on the release commit, checking stored mode, plan, report metadata, and UI labels.

Recommended request shape (illustrative; generated contracts remain authoritative):

```json
{
  "question": "...",
  "mode": "deep",
  "reportRequirements": ["..."],
  "budgetOverrides": {
    "maxProviderOperations": 14,
    "maxSources": 10,
    "maxWallClockMs": 420000
  },
  "requireApproval": true
}
```

Rules:

- The resolved mode remains `deep`; lower user limits reduce available effort but do not relabel the mode.
- Client overrides can only tighten the server/tier maximum. Reject invalid or over-limit values clearly; do not silently clamp a request upward or downward without reporting the resolved limits.
- The API is the authoritative validator for mode, policy ceilings, and budget units. The Next.js BFF may validate request shape for early feedback, but it must not become a second source of policy limits; its minimum contract is to forward valid mode and budget fields unchanged and have a regression test proving that behavior.
- Keep `max_search_calls` as a legacy persisted/API compatibility field during migration. Translate it deterministically to the legacy operation budget for old requests; never reinterpret it as “number of sources.”
- Expose the resolved mode, policy version, and effective ceilings in the run response/brief and report methodology. Do not expose secret model/provider details unless already permitted.
- Idempotency identity must include the explicit/resolved mode, policy version, requirements, approval setting, and all effective budget limits. Same key + same request replays; same key + changed mode/limits returns conflict.
- New run creation and policy snapshot persistence must remain one atomic, tenant-scoped admission operation; queue dispatch happens only after the committed run is visible under the existing durable-dispatch design.

#### Lifecycle propagation

Mode and policy must be present in create responses/run projections and preserved through every derived-run path, not just initial submission. Update the run read projection in `services/research-api/src/research_api/api.py`, shared projection contracts, and the web run-status/report types. A retry inherits the original mode, policy version, report requirements, and effective limits unless the user explicitly requests a new mode under a new idempotency identity. A follow-up defaults to the parent run’s mode/policy and records that parent relationship; changing mode must be explicit and reflected in the request fingerprint. The retry action and deadline display in `apps/web/app/(research)/research/[runId]/page.tsx`, `apps/web/lib/run-status.ts`, and follow-up client/API paths must use persisted mode/policy—not infer them again from `maxSearchCalls`.

The UI’s saved composer draft previously stored capitalized values (`Focused`, `Balanced`, `Deep`) under draft schema v1. The local implementation includes a compatibility migration; retain this acceptance case and verify it on the release commit so existing drafts are not discarded by the lowercase API enum.

### 4.2 Budget model

Use distinct, persisted limits and usage counters for:

1. Provider operations (search, extract, browser, academic lookup—each operation type defined precisely).
2. Unique admitted sources (deduplicated source identity, with a documented identity key).
3. Wall-clock deadline / active time.
4. Model input/output tokens and estimated cost, including uncertain dispatched-call accounting.
5. Repair tasks/rounds, separately from initial planning and collection.

Do not count cached candidate discovery as new evidence or a paid provider operation unless the adapter actually incurs one. Do not let discovery caches bypass source admission, extraction, citation verification, or tenant boundaries. All model/provider calls and repair paths reserve from the same authoritative ledger and hard limits; display caches never make admission decisions.

### 4.3 Immutable run brief / policy snapshot

Persist enough to reproduce the selected research contract:

```text
mode
mode_policy_version
original_question + normalized question (existing fields remain authoritative)
report_requirements (existing field)
resolved operation/source/time/token/cost ceilings
resolved repair limits and source-class strategy
report document/schema version expected by this run
planner/report prompt or graph protocol version already supported by the runtime
```

The local schema now persists explicit mode/policy and independent provider-operation/source limits through additive migrations `0013`–`0015` (report v3/v4 acceptance is added by `0016`/`0017`; immutable retrieval-accounting snapshots by `0018`; forward brief/budget guards by `0019`); the checked-out Alembic head is `0019`. These migrations are not thereby applied to Supabase or any deployment. Keep Budget/UsageLedger authoritative for admission/accounting, do not duplicate ceilings in an opaque brief, and verify the exact target revision before hosted rollout.

Old runs retain their original interpretation and report bytes. No backfill may claim a historical run selected a mode it never recorded. If a legacy display label is derived from the old budget, mark it as inferred/legacy.

### 4.4 Coverage plan and evidence mapping

Extend the planner artifact from a flat question list into a bounded plan with:

- `planVersion`, parent plan reference, mode/policy version;
- explicit dimensions (stable ID, short label, user-facing rationale, priority, mandatory/optional);
- requirement mapping (original question and each user requirement mapped to one or more dimensions);
- subquestions mapped to dimensions, with testable success criteria and allowed source classes;
- limits and planned operation allocation per task (never exceeding server admission);
- a record of which dimensions cannot be separately researched and why.

Each persisted evidence/claim assessment may reference one or more plan dimensions, but a link alone does not mean coverage. Dimension status should use a closed vocabulary such as `not_started`, `searching`, `evidence_found`, `verified_covered`, `unresolved`, `blocked`, with `assessment_basis`, linked verified claim/source IDs, and a short reason. Only `verified_covered` requires a deterministic/validated criterion backed by verified claims; models may suggest mappings, but deterministic validation and the existing citation gate decide what can be published.

Do not use keyword overlap as proof of coverage. Do not let the writer self-certify requirement satisfaction based only on its own prose. Preserve the question-level distinction between execution state, evidence volume, and answer-quality state.

### 4.5 Report document evolution

Keep report document v1 and every published version readable and immutable. Local report v2 currently carries assessed dimensions, criterion-backed requirement outcomes, and claim-linked comparisons. If v2 artifacts have been persisted in any target environment, do not add conflict or relationship fields by changing v2 in place; introduce the next report version (currently expected to be v3) and retain v1/v2 readers. Confirm persisted versions before choosing the version number.

The next report version (v3 if v2 has been persisted) should contain stable IDs and explicit references, not display indices alone:

- run/mode/policy/report version provenance;
- original question and requirement outcomes: `established`, `partially_established`, `not_established`, `not_assessed` (with reasons and supporting claim IDs);
- planned dimensions and final coverage assessment;
- findings whose every factual statement is linked to published, fully verified claim/citation IDs;
- comparison rows with explicit dimensions, alternatives, evidence cells, and “not found/not comparable” states;
- source metadata plus source-relationship/independence status and confidence/basis;
- contradictions and how they affect conclusions;
- limitations and unresolved questions;
- methodology: actual query/task/source counts and relevant search dates, not generated or inferred counts;
- answer-quality status kept separate from execution `completed`.

No report sentence should claim “comprehensive,” “answered,” “independent,” “current,” or “systematic” unless a specific versioned check supports that label. `answered` remains unavailable until a separate, tested acceptance policy is implemented. “No unresolved gaps” means none were recorded, not that completeness is proven.

#### Required report-level source relationships and conflict records

Persisted `same_content`, `same_work`, and `same_publisher` observations are provenance edges, not independence decisions. The report version must link edges to its stable source IDs and retain the edge kind, observed basis, and categorical confidence. Keep `sourceIndependence.status = unknown` until a separately validated lineage method supports a stronger result; never infer independence from different URLs, domains, publishers, or DOI values alone. Missing metadata remains explicitly unknown.

Conflict records must be anchored to at least two already verified claim IDs and their citation/source references. Record the affected dimension/criteria, whether the disagreement remains unresolved, the assessment basis/version, and a concise non-factual status reason. A model may nominate a conflict for review; nomination alone is not a confirmed conflict. Do not delete either supported side to make the report appear consistent, and do not generate a resolution not present in the evidence. If there are no assessed conflict records, say none were recorded rather than “no conflicts found.”

Acceptance checks: dangling/cross-run source or claim IDs reject publication; relationship bases are preserved byte-for-byte in the immutable document; unresolved conflict sides both remain visible; unassessed conflict status cannot become resolved; v1/v2 readers remain unchanged; tenant authorization and report-version pinning apply to every referenced record.

## 5. Research execution behavior by mode

### 5.1 Planning and decomposition

Use one planner to produce the bounded coverage plan. Apply deterministic validation for dimension count, user requirement mapping, source-class values, task count, and budget allocations. Reject or repair malformed plans without dispatching extra unbudgeted work. A simple deterministic baseline planner/template for known query classes is an option to compare, not a second mandatory planner.

Mode-specific plan objective:

- **Focused:** choose the few dimensions that directly answer the requested decision/question; state explicitly which adjacent dimensions are out of scope.
- **Balanced:** include each core comparison/causal/context dimension and a risk/counterevidence dimension when relevant.
- **Deep:** enumerate the main question dimensions, evidence classes, potential disagreements, methodological constraints, and unresolved risks. Include user requirements, not only model-generated themes.

No planner may enlarge source, operation, token, time, or cost limits. If requirements exceed the selected mode’s feasible ceiling, surface a preflight warning/selection prompt or mark constraints; do not silently drop requirements.

### 5.2 Collection and independence

Dispatch planned subquestions using current durable task/worker records and existing per-provider limits. Every task has stable identity, attempt, plan version, dimensions, operation reservation, and failure state. Preserve partial successful tasks if siblings fail. Distinguish provider operations, discovered URLs, extracted pages, unique sources, and verified evidence in UI and methodology.

For Balanced/Deep, try to cover requested source classes and obtain corroboration where useful/available. Failure to find a class is an explicit coverage limitation, not a reason to fabricate sources or classify unknown sources based on domain guesswork. Source-independence relationships are represented as `unknown` until supported by metadata or validated relationships.

### 5.3 Bounded repair (implemented locally; live evaluation pending)

Bounded gap repair is implemented for new explicit Balanced and Deep jobs that do not require plan approval, only when the job is pinned to the opt-in v14 graph. New explicit jobs use v13 and do not repair by default. Previously pinned v10–v12 jobs retain their original graph semantics; Focused and approval-required jobs do not repair. Repair runs at most one delta round; planning reserves its allowance, and admission rechecks operation, source, time, token, and cost budgets. Delta claims pass the same exact-span and semantic evidence gate; the base assessment remains the fallback, and uncertain paid calls are not blindly replayed. Concurrent admission, cancellation, replay, fallback, and legacy-graph behavior have local integration coverage.

This is a local implementation status, not evidence that repair improves answer quality or is safe/fast enough for production. Live latency, cost, and quality remain unmeasured; broader browser/mobile/accessibility validation also remains open. Keep automatic repair off in production until the separately authorized evaluation passes. See the [bounded repair design](./bounded-gap-repair-design.md) and [implementation status](./research-modes-implementation-status.md) for mechanics and validation receipts.

### 5.4 Composition and report depth

The report layer turns the verified claim ledger, assessed coverage, source relationships, and reviewed conflicts into a coherent report. It may group, compare, prioritize, and explain relationships only when every factual statement is supported by linked verified findings and a deterministic alignment check confirms claim/citation integrity. A simple sentence reorder is not enough for a useful report, and free-form unchecked narrative is not acceptable. The evidence-verified narrative protocol and its tests are specified in Phase 4 below; no minimum word count is a quality gate.

Report acceptance is completeness of supported dimensions and usefulness, not length. If evidence is thin, return a compact partial/insufficient-evidence report with clear gaps. Do not render empty headings or repeat generic limitation text merely to resemble a long report.

Required report patterns:

- **Focused:** one direct answer/decision framing; strongest supported findings; important trade-offs/caveats; source links; clear unresolved aspects.
- **Balanced:** short executive answer; method/scope; findings by core dimension; comparative table when alternatives share comparable criteria; trade-offs; limitations; references.
- **Deep:** scope and research questions; method/evidence coverage; detailed findings per dimension; cross-source synthesis and contradictions; comparison matrices where justified; implications; source independence/authority limitations; unresolved questions; full references.

Tables are generated only when there are at least two comparable alternatives and evidence for the cells. Missing evidence is an explicit “not established” cell, not model-completed prose. Report requirement outcomes must be visible and trace back to citations.

## 6. Implementation order and file-level work

### Phase 0 — Baseline and consistency (partially complete; no new behavior)

1. Confirm git root/status; preserve unrelated user changes.
2. Pin the checked-out migration head (`0019` in this checkout) and graph compatibility (new explicit jobs use v13 by default; v14 repair requires explicit opt-in; pinned v7–v12 explicit jobs and legacy v3/v4/v5 retain their respective semantics). Verify target database and deployed worker versions separately; repository state is not proof of hosted state.
3. A versioned 20-case fixture, rubric, schema, and authored synthetic receipts now exist under `services/research-api/evaluation/modes/v1/`. They provide offline harness/reproducibility checks only. They are not provider-receipt replay, application execution, human labels, or a measured quality/latency/cost baseline.
4. Preserve live-provider measurements as a separate, explicitly approved and budgeted experiment. Before a quality comparison, name the evaluation owner, adjudicate reference dimensions/answerability, approve evidence privacy/licensing, freeze snapshots and thresholds, and record receipt hashes, mode limits, coverage, quality, latency, and settled cost.

**Exit gate:** graph/migration compatibility checks are reproducible and the offline harness verifies its fixtures and hashes. The stronger measured baseline remains open until there are real, fixed-snapshot observations; synthetic baseline output cannot satisfy it. Re-run all checks on the final implementation commit. Inspect any target DB independently before migration. Live-provider work remains outside this documentation update.

### Phase 1 — Explicit mode and independent budget semantics (implemented locally; release gates remain)

Likely files (verify generated-code workflow before editing):

- `apps/web/app/(research)/research/page.tsx` — map UI selection to stable lowercase mode enum; send it explicitly; resolve the quick-explainer decision; explain source and operation ceilings separately.
- `apps/web/lib/research-draft.ts` and `apps/web/tests/research-draft.test.ts` — persist lowercase mode in a new draft version, safely read/migrate existing capitalized v1 drafts, and test invalid/stale values.
- `apps/web/lib/research-submission.ts` already reuses the same body/key for an unchanged submission. Keep that behavior; add the mode to the serialized body in the composer caller and test mode inclusion/body stability there.
- `apps/web/app/api/research/runs/route.ts`, `apps/web/lib/research-proxy.ts`, and proxy tests — preserve the BFF’s intentional pass-through boundary and prove mode/limits arrive unchanged at the API. Put policy and ceiling enforcement in the API, not duplicated BFF configuration.
- `packages/contracts/src/research.ts`, `packages/contracts/schema/CreateResearchRunRequestSchema.json`, `packages/contracts/schema/ResearchRunProjectionSchema.json`, fixtures, and `packages/contracts/schema/manifest.json` — add request/response enums and compatibility rules.
- Generation/check chain: update canonical Zod contracts; run `packages/contracts/scripts/generate-json-schema.ts` (including manifest); run `packages/contracts/scripts/check-generated.ts`; update the explicit mapping in `services/research-api/scripts/generate-pydantic.sh`; regenerate `create_research_run_request.py` and projection models; verify generated diffs are clean and schemas parse. Never hand-edit generated output only.
- `services/research-api/src/research_api/api.py` — resolve mode policy, enforce only-tighten overrides, serialize mode/policy/source/operation totals in run reads, and carry the snapshot through retry/follow-up creation.
- `services/research-api/src/research_api/db/models.py`, `repositories/runs.py`, and the additive Alembic migrations — this contract is implemented locally by `0013`–`0015`; any future schema change must branch from the then-current verified head. Keep Budget/UsageLedger authoritative for admission/accounting.
- `apps/web/lib/run-status.ts`, `apps/web/app/(research)/research/[runId]/page.tsx`, and follow-up client/UI paths — render persisted mode and use it for retry/deadline behavior; do not infer mode from old call-count thresholds for new runs.
- `services/research-api/src/research_api/research_limits.py` and budget schemas — introduce explicit units and legacy translation; keep old fields until all clients/workers are migrated.

**Exit gate — each item has a named automated case:**

- `Deep + evergreen short question` remains Deep end-to-end; any fast explainer is a separate explicit choice (or legacy-only behavior), never a hidden downgrade.
- `Deep + maxProviderOperations: 2` (the current API’s minimum valid operation budget) remains mode `deep` while the run accurately reports it could not complete the normal Deep plan; no relabel or silent extra spend.
- Legacy request omitting mode resolves to and persists `legacy-inferred`; old run/report/checkpoint behavior remains unchanged.
- An over-ceiling but schema-valid request (for example Focused with `maxSearchCalls: 20`, while the temporary schema permits it) is rejected with a stable 422 code; schema-invalid values above 50 are a separate contract test. Limits are not silently clamped.
- Same idempotency key and unchanged request replays the same run; changed mode, policy, requirement, approval, or effective budget conflicts.
- Mode survives API read/projection, approval pause/resume, worker kill/restart, retry, and follow-up. Retry and follow-up inherit the parent snapshot unless explicitly changed.
- Existing capitalized draft values restore correctly after enum migration; the BFF forwards mode unchanged; source and provider-operation counts are distinct in payload, methodology, and UI.
- Contract generation is reproducible: Zod → JSON Schema + manifest → generated Pydantic has no uncommitted generated diff after the check pass.

### Phase 2 — Persisted coverage plan and truthful source metadata (implemented locally; report projection completed in Phase 3)

Likely files:

- `services/research-api/src/research_api/graph/builder.py` — typed plan dimensions, mappings, policy-constrained planner output and deterministic validation.
- `services/research-api/src/research_api/db/models.py` and repositories — persist immutable plan versions/dimension records or bounded JSON in the existing versioned plan artifact; do not duplicate source truth.
- `services/research-api/src/research_api/ingestion.py`, source adapters, `repositories/sources.py`, and provider schemas — set source class only from trustworthy metadata/adapter evidence; otherwise `unknown`; preserve publisher/DOI/canonical identity and relationship basis.
- `packages/contracts/src/research.ts`, evidence/source contracts, report document schemas and generated models — versioned plan/coverage/source-relationship structures.
- migration(s), RLS, repository tests — tenant keys and policy constraints for every new row/relationship; uniqueness/idempotency for stable IDs.
- graph fixtures and planner/ingestion tests — requirement coverage, no budgets exceeded, unknown source handling.

**Exit gate:** every planned requirement/dimension has persisted identity and state; evidence links are provenance only until the assessment gate; cross-tenant reads/writes are denied; source-class unknown is never silently upgraded.

### Phase 3 — Report-level source provenance and conflicts (implemented locally)

Implemented locally as report v3 on graph v8 with migration `0016`; see the [status document](./research-modes-implementation-status.md) for receipts. The original scope is retained below for audit.

Likely files:

- `services/research-api/src/research_api/coverage.py`, `criterion_review.py`, and `graph/builder.py` — nominate possible disagreements only among verified findings, validate claim/criterion/dimension references, and preserve unresolved/unknown states. Avoid classifying a conflict from opposite sentiment alone.
- `services/research-api/src/research_api/db/source_relationships.py`, `repositories/source_relationships.py`, and assessment persistence — load relationships only within the report’s tenant/run/source set; preserve first-observed basis and stable IDs.
- `services/research-api/src/research_api/report_document_v2.py` and `packages/contracts/src/report.ts` — add report-level conflict and relationship projection in a new immutable report schema version if any v2 has been published/persisted in the target. Keep independence unknown unless a versioned, evidence-backed method supports a stronger status.
- `packages/contracts` generated schemas/Pydantic, `apps/web/lib/report-document.ts`, report UI, Markdown/export/share/comparison readers — retain old-version rendering and expose lineage/conflict evidence links without making unsupported claims.
- tests for dangling IDs, cross-run/tenant references, replay, source deletion/retention, conflicting supported claims, unknown metadata, unresolved disagreement, and historical v1/v2 reads.

**Exit gate:** every relationship/conflict row is version-bound and references only authorized report sources and verified claims; both sides of material unresolved disagreement remain visible; unknown is not upgraded; old report versions remain unchanged; readers show the assessment basis and underlying evidence.

### Phase 4 — Evidence-verified narrative composition (implemented locally)

Implemented locally as report v4 on graph v9 with migration `0017`; migration `0018` adds a separate immutable retrieval-accounting snapshot without changing the v4 document contract. See the [status document](./research-modes-implementation-status.md) for the protocol and receipts. The original scope is retained below for audit. Before Phase 4, the composer copied exact verified findings into generic sections. Add enough evidence-grounded explanation to make reports useful while preserving the claim ledger as the only factual publication authority.

Likely files:

- `services/research-api/src/research_api/graph/builder.py` and `grounding.py` — generate bounded candidate factual sentences/paragraph blocks from preserved source passages and the existing verified ledger. Each new factual proposition must become a claim with exact source spans, semantic review, and stable citations through the existing gate; do not treat a prose-level alignment heuristic as proof of support.
- `services/research-api/src/research_api/report_document_v2.py` or the next immutable version and `mode_composer.py` — persist ordered narrative blocks with claim/citation IDs, covered dimension, section role, and explicit supported transitions. Reject every factual sentence without accepted claim references.
- `model_budget.py`, assessment manifest/repositories, and publication transaction — reserve/account for added model work using existing ledger rules; pin inputs before dispatch; replay only validated receipts; keep uncertain calls recovery-needed rather than redispatching blindly.
- contracts, Pydantic generation, report API/export/share/comparison readers, and `apps/web/app/components/report-coverage.tsx` — render the richer report and its citations while keeping legacy reports intact.
- tests for partial/empty evidence, contradictions, table cells, generated prose with unsupported additions, citations, replay after crash, output bounds, reduced/human readability review, and all three mode structures.

**Exit gate:** every factual sentence maps to one or more fully verified claim/citation IDs; unsupported connective facts cannot publish; mode differences change report organization and evidence detail rather than only headings; no word-count target overrides evidence; failed/empty runs remain concise and honest; added model cost and latency are visible and accounted.

### Phase 5 — Design and implement bounded repair

This phase is implemented locally after Phases 3 and 4, as documented in [bounded-gap-repair-design.md](./bounded-gap-repair-design.md). It admits at most one bounded round for eligible Balanced/Deep runs without approval. The original report is the fallback; live quality, latency, and cost are still unmeasured. The design requirements below remain the release acceptance contract.

Likely files:

- `services/research-api/src/research_api/graph/builder.py`, `coverage.py`, and `mode_planning.py` — choose only eligible unresolved dimensions/conflicts and construct bounded delta tasks without regenerating the whole report.
- Budget/admission repositories, `model_budget.py`, `ingestion.py`, job/checkpoint/version handling, and assessment persistence — atomically reserve every required operation/source/time/token/cost unit, preserve accounting uncertainty, and make the decision/request/result replay-compatible.
- API/events/UI and `docs/reflection.md` — distinguish repair proposed/admitted/running/completed/rejected, explain stop reasons, and preserve collected evidence through cancellation/failure.
- concurrency, migration, transaction, crash-injection, replay, cancellation, approval, and worker-restart tests.

**Exit gate:** failure injection at decision → reservation → dispatch → provider result → persistence → checkpoint proves no over-budget work, duplicate uncertain dispatch, dropped prior evidence, or false completion; cancellation/approval remain correct; source-level and tenant authorization hold.

### Phase 6 — Cross-mode evaluation, then product claims (separately gated)

Use at least 20 fixed benchmark questions × 3 modes (60 evaluated outputs) for the first live/human gate; expand toward the 60-question repository ambition after process is stable. This is a separate authorization and release gate, not an automatic continuation of Phases 3–5. Use fixed model/provider/prompt/schema/graph snapshots and record deviations. Benchmark outputs may involve paid providers; schedule only after explicit approval, provider spend caps, accepted gold labels, blinded review, and preregistered margins. The synthetic offline harness does not count toward these 60 outputs.

Compare modes on:

- requirement/dimension coverage and intentionally missing-evidence calibration;
- claim precision, exact citation correctness, citation completeness, and evidence-to-claim attribution;
- source provenance and independence assessment; primary/secondary coverage;
- contradiction detection/recall and whether disagreement reaches the report;
- answer directness, decision usefulness, and information density with answer length controlled in human/judge comparisons;
- unsupported assertion rate (including abstention behavior);
- queue wait, first useful evidence, end-to-end p50/p95, failures, provider operations, tokens, and cost per verified covered dimension/useful finding.

Use deterministic metrics plus blinded human review. An LLM judge is supplementary and must be calibrated on human labels; it is not a correctness oracle. RAGAS faithfulness can be an auxiliary contextual-consistency metric, not a substitute for exact-span verification, completeness, source independence, or domain review.

**Proposed release gates (thresholds must be set from baseline before looking at candidate results):**

1. No reduction in citation precision/support versus baseline beyond the pre-registered non-inferiority margin.
2. No regressions in tenant isolation, exact-span checks, spend ceilings, idempotency, checkpoint recovery, or cancellation race suite.
3. Deep improves tail-dimension coverage and contradiction recall over Balanced on cases designed to need those dimensions, while maintaining citation precision; merely returning more words/sources does not pass.
4. Balanced improves broad core-dimension coverage over Focused on multi-dimension questions; Focused retains lower median latency/cost on single-question tasks.
5. In insufficient-evidence cases, modes remain calibrated and disclose unresolved requirements rather than hallucinating coverage.
6. Latency and cost are reported alongside quality, with p50/p95 and workload conditions; no vendor numbers or local fixture timings become product promises.

After gates pass, update mode UI explanations and pricing/marketing claims to reflect server-enforced capabilities. Pricing/Stripe/entitlement implementation is outside this plan; the existing [pricing-entitlements-billing.md](./pricing-entitlements-billing.md) file is pre-existing user work and must be reviewed separately, not overwritten. Current pricing copy must not promise access, quotas, export formats, or flat per-run economics unless backend enforcement and billing behavior support them.

## 7. Data, migrations, tenancy, and lifecycle requirements

- All new tables/columns remain tenant-scoped and use the existing RLS/grant model. New relationships must validate tenant equality on both sides, preferably using composite tenant-aware foreign keys where compatible with schema conventions.
- A migration is additive and restart-safe; schema generation and OpenAPI/contract snapshots update together. Test upgrade from current head and recovery from a partially applied migration in disposable PostgreSQL.
- Verify target project/database and current Alembic revision before any hosted migration. Local validation does not authorize Supabase changes.
- Immutable report version and run-plan snapshots are never overwritten. A new policy/report version produces new artifacts; old run/job graph versions either continue on the compatible implementation or fail closed with a clear recoverable state.
- Deletion/export/retention paths must include new plan/coverage/source relationship records without leaving cross-tenant references or breaking immutable artifacts.
- Keep large source bodies out of LangGraph state and report JSON; persist IDs and bounded assessments, as current architecture intends.
- Migration/app rollback keeps additive schema in place. Runtime feature flags may disable new-mode admission or report-v2 publication, but must preserve old report reads and must not silently re-dispatch paid work.

## 8. Observability and user experience

Persist concise, structured events/counters for mode and policy version, plan creation, dimension state transition, source class/identity basis, repair decision and bound, operation reservation/settlement, report quality, and stage latency. Use run ID/request ID/trace ID for correlation. Do not log raw private source contents, full user questions by default, tokens, credentials, or unrestricted prompts.

Run status, evidence collected, dimensions covered, and report quality are separate UI concepts. The user should see:

- chosen mode and resolved ceilings before submission;
- plan/dimensions and approval opportunity when enabled;
- live progress by dimension and provider operation, not only generic “thinking” messages;
- distinction between “sources found,” “sources read,” “verified findings,” and “requirements established”;
- prominent terminal states: complete/answer established, complete/partial, complete/insufficient evidence, failed, cancelled, waiting for approval;
- no-progress/wait-time and retry/resume guidance without claiming work that has not persisted;
- reduced-motion, keyboard, screen-reader, and narrow viewport support.

Avoid flashy animation during long research. Motion must clarify stage transitions and newly persisted evidence; respect `prefers-reduced-motion`; never animate a failed state out of view or replace the persistent status label with a transient toast.

## 9. Test and fault-injection matrix

### Contract and policy

- All three enum values parse through web → BFF → API → persisted run → job/checkpoint → report.
- Missing mode follows explicit legacy policy only; invalid mode rejects.
- Deep with a smaller budget remains Deep; server max cannot be raised by request.
- Source ceiling and operation ceiling are independently enforced under concurrency.
- Idempotency same body replays; changed mode, policy, requirements, or effective limit conflicts.
- Draft recovery preserves mode and remains account-scoped.

### Planning and coverage

- Requirement mapping for one and many requirements; duplicates, long text, ambiguous/overlapping dimensions, zero usable dimensions, and planner schema failure.
- Planner cannot exceed count/token/operation/source limits; every generated task maps to a dimension or records why not.
- Source classes unknown/partial metadata remain unknown; aliases/canonical duplicates/syndication don't inflate independence.
- Evidence association alone never marks a requirement established.

### Research and repair

- Independent tasks run concurrently within provider/database limits; failed task does not erase completed evidence.
- No eligible gaps, exhausted reserve, low evidence yield, contradictions, and budget boundary cases stop deterministically.
- Repair dispatch crash/restart, uncertain provider call, result persisted before checkpoint, checkpoint before result, cancellation during dispatch, approval pause/resume, and duplicate resume.
- Run status and report state remain coherent with partial evidence.

### Reports and evaluation

- v1 historical reports remain readable; v2 validates IDs, references, state transitions, section membership, and size limit.
- Unsupported model-added facts, non-exact citations, semantically rejected claims, invented numbers, empty tables, conflict erasure, empty headings, zero findings, and long reports with no supported content are rejected/represented honestly.
- Requirement outcome ties to verified claim IDs; comparison rows represent unknown/incomparable values explicitly.
- Reproducible fixed workload, human-label adjudication, calibration and regression test for quality/latency/cost dashboard.

### Persistence/security and frontend

- Disposable PostgreSQL tests for migration upgrade/downgrade policy, RLS/grants, FK tenant mismatch, idempotency races, immutable report behavior, and job replay.
- Request/response authorization and report access remain user/tenant scoped.
- UI: mobile overflow, keyboard-only mode selection, visible selected value, focus return, reduced motion, screen-reader labels, failed/partial terminal state, reconnect/replay, and stale-client/legacy response handling.

## 10. Rollout and rollback

1. Ship schema/contracts and backward-compatible reads first; do not dispatch new explicit-mode jobs yet.
2. Deploy API/worker code that understands old and new briefs, then web code that submits explicit mode. Verify graph-version compatibility across all workers before queueing new jobs.
3. Enable explicit mode for internal/test tenants or a feature-flag cohort with strict existing budgets. Do not silently run all users on a new policy.
4. Compare the same benchmark and a small, authorized live sample; measure useful evidence, report quality, latency, and cost. Live provider tests require explicit spend approval.
5. Enable adaptive repair/report v2 only after migration, replay, quality, and fault-injection gates pass.
6. Update customer-facing feature/pricing claims only after tier entitlements exist and have been tested.
7. Roll back app/worker flags without deleting additive schema or rewriting historical runs. Stop new admissions before rolling back workers; keep readers for already-published v2 reports or provide a compatible reader release.

No hosted migration, live provider call, production deployment, merge, or PR publication is authorized by this plan.

## 11. Key design decisions and unresolved product choices

1. **Who can run each mode?** Pricing page currently appears to include Focused and Balanced on Free and Deep on paid tiers, while a separate pricing proposal may suggest Free=Focused only. Choose one product contract and enforce it server-side before advertising it. This document does not decide or implement billing.
2. **What is a “source”?** Choose a stable identity (canonical URL/work ID plus provider identity where appropriate) and distinguish discovery result, extracted document, exact-content duplicate, and independent work.
3. **What coverage qualifies as established?** Define per requirement/dimension validation rules and reviewer policy. Do not use a single generic percentage until calibration shows it is meaningful.
4. **How much extra effort does each mode receive?** Start from existing ceilings, benchmark repair-task/operation reserves, then set versioned policy values. Do not base this solely on vendor token ratios.
5. **Do we need LangGraph `Send`?** Only if graph-native worker visibility, tracing, or checkpoint semantics materially improve the current persisted-task architecture in a matched test; it is not a prerequisite for mode differentiation.
6. **Which claims can use corroboration requirements?** Risk-based claim classes may justify more evidence; defining them needs product/domain review and should not cause unsupported universal “two sources” promises.

## 12. Repository file map (implementation targets, not all guaranteed changes)

| Concern | Primary files |
|---|---|
| Composer/mode selection | `apps/web/app/(research)/research/page.tsx`, `apps/web/lib/research-draft.ts`, `apps/web/lib/research-submission.ts`, relevant component and browser tests |
| Shared request contract | `packages/contracts/src/research.ts`, generated JSON schemas, fixtures, schema-generation scripts |
| API validation/admission | `services/research-api/src/research_api/api.py`, request schemas, `research_limits.py`, `repositories/runs.py` |
| Run/budget persistence | `services/research-api/src/research_api/db/models.py`, Alembic migration(s), Budget/run repositories, RLS/grant/integration tests |
| Planning/coverage/repair | `services/research-api/src/research_api/graph/builder.py`, plan/subquestion repositories, graph version compatibility, `docs/reflection.md` after behavior is final |
| Sources and independence | `services/research-api/src/research_api/ingestion.py`, `repositories/sources.py`, provider adapters, generated source contracts, source identity/relationship migrations |
| Report v2 | `services/research-api/src/research_api/report_document.py`, generated report schemas, `reports.py`, publication repositories, serializers and report UI |
| Run UI / progress | `apps/web/app/components/research-workspace.tsx`, workspace/report components, run-status and event contracts, `apps/web/app/research-workspace.css` and focused component styles |
| Evaluation | `docs/evaluation.md`, `services/research-api/scripts/` benchmark tooling, evaluation fixtures/results, CI gates; add no paid CI calls |
| Product claims | `apps/web/app/pricing/page.tsx`, pricing plan components, signup/entitlement paths, billing plan (separate scope) |

Before each phase, re-run `git status --short` and inspect the precise diff. Do not overwrite or stage unrelated dirty files. The existing untracked pricing plan document is explicitly outside this one-file plan change.

## 13. Acceptance definition

This work is ready to call complete only when:

- requests explicitly select a mode and the server persists a versioned policy snapshot;
- low budgets tighten work without relabeling mode, and separate source/operation counters hold under concurrency;
- each mode produces a distinct, validated plan and report structure appropriate to its intent;
- requirement/dimension coverage is evidence-linked and independently assessed, with honest unresolved states;
- repair is bounded, replay-safe, and driven by verified gaps/conflicts, not only failed tasks;
- the report contains no factual prose outside the verified/validated evidence contract;
- old runs, checkpoints, and report versions retain their original behavior/readability;
- security, migration, crash/replay, budget, and UI accessibility gates pass;
- cross-mode benchmark shows the intended quality/cost/latency distinctions without weakening citation precision;
- pricing and product claims match actual entitlement enforcement.

Until the final benchmark passes, describe the behavior as “mode-specific research policies under evaluation,” not as guaranteed comprehensive research.

## 14. References

### Repository sources inspected

- [`mode-specific-research-reports.md`](./mode-specific-research-reports.md) — existing mode-specific evidence/report ceilings and implementation details.
- [`phase1-quality-foundations.md`](./phase1-quality-foundations.md) — structured report v1, requirement semantics, run continuity, migration/validation boundary.
- [`docs/reflection.md`](../reflection.md) — current intended reflection architecture; must be reconciled against actual code.
- [`docs/evaluation.md`](../evaluation.md) — quality metrics, ablations, and benchmark ambitions; not proof of completed benchmark execution.
- [`packages/contracts/src/research.ts`](../../packages/contracts/src/research.ts) — current shared request, plan, state, and projection schemas.
- [`apps/web/lib/research-draft.ts`](../../apps/web/lib/research-draft.ts), [`research-submission.ts`](../../apps/web/lib/research-submission.ts), and [`research-proxy.ts`](../../apps/web/lib/research-proxy.ts) — saved draft casing/version, idempotent request body reuse, and BFF pass-through behavior.
- [`research/page.tsx`](../../apps/web/app/%28research%29/research/page.tsx) — current composer mode labels and submitted limits.
- [`run-status.ts`](../../apps/web/lib/run-status.ts) and [`research run page`](../../apps/web/app/%28research%29/research/%5BrunId%5D/page.tsx) — current call-count-derived retry deadline and run UI lifecycle actions.
- [`api.py`](../../services/research-api/src/research_api/api.py), [`reports.py`](../../services/research-api/src/research_api/reports.py), [`research_limits.py`](../../services/research-api/src/research_api/research_limits.py), [`builder.py`](../../services/research-api/src/research_api/graph/builder.py), and [`runs.py`](../../services/research-api/src/research_api/repositories/runs.py) — current admission, mode inference, limits, graph behavior, and persistence.
- [`jobs.py`](../../services/research-api/src/research_api/jobs.py) and the migration directory `services/research-api/src/research_api/db/migrations/versions/` — checked-out graph compatibility and migration chain (head `0019` in this checkout; target deployment state must be verified separately).
- Contract generation: `packages/contracts/scripts/generate-json-schema.ts`, `packages/contracts/scripts/check-generated.ts`, and `services/research-api/scripts/generate-pydantic.sh`.
- [`pricing page`](../../apps/web/app/pricing/page.tsx) — current public tier/mode/export claims; verify against server enforcement before release.

### External primary/official references

- Anthropic, [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) — planner/worker parallel research, synthesis, separate citation pass, and token/cost trade-offs. Its reported benchmark improvements are Anthropic-specific and are not acceptance targets for this product.
- OpenAI, [Deep research in the API](https://developers.openai.com/api/docs/guides/deep-research) — bounded tool-call controls, background execution, approval handling, and optional prompt clarification/rewrite. This is an architectural reference, not a recommendation to replace the current graph/runtime.
- LangChain, [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api) and [orchestrator-worker workflows](https://docs.langchain.com/oss/python/langgraph/workflows-agents) — graph-native dynamic `Send` workers and shared-state aggregation; evaluate against current persisted task design before migration.
- RAGAS, [metrics overview](https://docs.ragas.io/en/stable/concepts/metrics/overview/) and [faithfulness metric](https://docs.ragas.io/en/v0.2.5/concepts/metrics/available_metrics/faithfulness/) — supplementary context-consistency evaluation; LLM-based metrics are not deterministic ground truth and do not replace exact-span or citation verification.
- PRISMA, [PRISMA 2020](https://www.prisma-statement.org/prisma-2020) and [flow diagram](https://www.prisma-statement.org/prisma-2020-flow-diagram) — systematic-review reporting guidance and record flow. Use only for a separately scoped review workflow; do not imply this general Deep mode is PRISMA-compliant.
- User-provided product reference: [AnswerThis application](https://app.answerthis.io/ask-answerthis?tab=library) and the screenshots in the conversation. These are qualitative workflow/UI references, not technical guarantees or permission to copy their visual identity.

