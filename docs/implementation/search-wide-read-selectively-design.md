# Search-wide, read-selectively research design

Status: implementation in stages. This document audits the October 18 checkout and defines the remaining gates. The AnswerThis screenshot and [public guide](https://answerthis.io/blog/full-guide) are product references, not evidence of its private architecture or completion time.

## User outcome and measurement

The user should see useful, checked evidence sooner and receive a report that addresses each requested dimension with appropriate depth. Track time to the first *visible* verified finding, total active processing, approval wait, relevant unique works per dimension, extract success, verified citations, assessed coverage, report usefulness, and accounted cost. Discovered records, extracted sources, and cited sources are separate measures. No fixed source-count or word-count target establishes quality.

Current local matched Focused pair: 42.38–49.05 seconds to completion, 9.63–14.06 seconds to first source, and first verified finding recorded near completion. Writer remote calls were 25.62–27.52 seconds. This single pair is diagnostic only; it does not establish a production percentile or a pooling benefit. See [latency validation](research-quality-latency-validation.md).

## Audit of the seven proposed changes

| Proposed change | Present in checkout | Remaining work |
| --- | --- | --- |
| Coverage plan | Explicit-mode runs persist a versioned `CoveragePlan`, requirements, task criteria, dimension links, and per-question allocations in `mode_planning.py`. `source_classes` guide the selected provider. | Evaluate whether planned dimensions and source-class hints retrieve relevant evidence. A link is not completed coverage. |
| Parallel indexes | `graph/builder.py` runs question tasks concurrently with a per-run semaphore. Tavily is the web/extraction path; Serper is optional web discovery; OpenAlex is optional academic discovery and off by default. | Validate OpenAlex on representative, blinded judgments and extracted citation yield. Add a second index only when it provides relevant unique works for a real workload. |
| Deduplication and screening | `candidate_screening.py` ranks an OpenAlex result page by lexical overlap and records DOI/work/URL duplicate and exclusion decisions. `ingestion.py` saves the exact shortlist receipt before extraction. Web result URL identity and exact content deduplication also exist. | Lexical overlap is not relevance or independence. Evaluate candidate-pool size and ranking on a fixed pool before altering the pinned policy. Do not silently merge uncertain title/year matches. |
| Bounded extraction | Search and extract operations reserve budget before dispatch; extraction admission caps run and per-question sources. Artifacts and receipts support recovery. Concurrent question tasks use independent tenant sessions; no transaction crosses a provider call. | Measure per-dimension extract success and misses. Tune concurrency only from provider and database timings, preserving budgets and provider rate limits. |
| Verified report | Report V4 composes narrative from verified findings with immutable claim/citation links, coverage status, provenance, conflicts and limitations. Mode limits are versioned. | Evaluate completeness, readability and comparison-table quality with humans. A longer draft alone does not close an evidence gap. |
| Progressive delivery | Source arrivals and task activity appear live. Until this slice, the first verified-finding telemetry marker had no visible finding payload. | This slice adds a durable, bounded preview of checked claims before criterion review and narrative composition. Subsequent work can move verification to independently checkpointed question units if matched traces show useful latency gain. |
| Evidence canvas | The report has an outline, citation navigation, resizable source pane, search, sort, source details, save-to-library, coverage and retrieval accounting. | Validate on long reports and mobile. Expand bibliographic attributes only with provenance and a stable public contract; do not copy features suggested by a screenshot without data support. |

## Execution and ownership

The research run and its budget are the source of truth. A planner produces a versioned coverage plan with source-class requirements and an operation/source allocation. Each question searches its pinned provider route. Search results are *candidates*; the provider response and shortlist policy are stored in a tenant/run/fingerprint-bound receipt. Screening selects a small set to extract. Extracted artifacts, source rows and relationships become durable evidence. The writer proposes claims; exact-passage and semantic checks determine which claims can be published. Criterion review assesses coverage, then optional narrative composition organizes verified claims. The immutable report is the published answer.

Candidate metadata and abstracts never become cited passages by themselves. Different URLs, publishers or model reviews do not establish source independence. A comparative benchmark requires comparable measurements; otherwise the report names the missing comparison.

### Preview event introduced in this slice

After supported claims are audited, the assessment writes one `assessment.findings_verified` event with a deterministic ID derived from the assessment ID. It carries at most three complete, checked claims, up to four distinct source IDs each, and the total supported count. The event is committed before the separate criterion-review and narrative calls. The authenticated snapshot and SSE routes expose only a validated public projection. The canvas shows the preview while the report is pending; it disappears when the immutable report loads. This preview is a checked draft: publication and coverage assessment can still change which claims appear in the final report.

The run-row lock serializes competing event writes. The deterministic event ID and existence check make resume idempotent; the outbox remains the source of truth for reconnects. If the process stops after the event commits, the preview remains clearly labeled as a draft and the existing assessment replay continues without repeating paid calls. The preview-write duration and optional failure are recorded; failure does not block report publication.

### Canvas design choice

Keep the current editorial report surface: existing ink, muted, steel, copper and surface tokens; existing typefaces and reading width; the report on the left and evidence on the right at wide sizes. On small screens the report and evidence remain separate reachable views. The new preview is one quiet bordered reading block above activity, with complete claims and source actions. Its visual hierarchy distinguishes checked evidence from the still-running coverage review. It adds no automatic motion or new visual language; the underlying existing source panel handles long titles, source search/sort and inspection. Keyboard users can focus source actions, and the final report replaces the preview in the same reading area.

## Next implementation gates

1. **Validate preview:** public-projection unit tests, a disposable-Postgres concurrent/replay test, and an isolated mobile browser test of SSE arrival, reload recovery, source navigation and final report handoff now pass. Still measure visible first-finding time on matched live workloads and validate network reconnect behavior under a real API session. Keep the preview bounded and tenant-scoped.
2. **Fixed-pool retrieval evaluation:** use a representative question set with explicit dimensions. Blindly label a frozen, shared candidate pool; compare current lexical policy, provider order and any proposed reranker at the same extract cutoff. Report per-domain precision, recall, unique works, duplicate/version errors and coverage. Keep OpenAlex off until its end-to-end yield passes.
3. **End-to-end academic evaluation:** on a small authorized matched sample, compare extracted full text, exact and semantically supported citations, assessed dimensions, latency and cost. Record provider/search/extract attempts separately. The public [OpenAlex API](https://help.openalex.org/api/) and [Semantic Scholar API](https://api.semanticscholar.org/api-docs/) provide metadata discovery; they do not guarantee accessible full text.
4. **Candidate-pool expansion:** only after gate 2, consider a larger OpenAlex metadata page without raising the extracted-source cap. Pin page size and shortlist policy to a new graph/request version; old checkpoints must reconstruct their original fingerprint. Preserve request accounting, cancellation, and short database transactions.
5. **Earlier verification:** if the preview still arrives too late, split writer/review by bounded question units and checkpoint each unit. Define per-unit budget, unique event identity and deterministic report merge before adding concurrency. Do not broadcast unverified text.
6. **Canvas refinement:** review long reports and mobile with real source data, add only missing navigation or metadata fields, and test reduced-motion and keyboard paths. Do not replace the existing report/evidence workspace.

## Rollout and stop conditions

Keep current mode ceilings and the OpenAlex feature flag unchanged while collecting comparative evidence. Do not enable another index, raise extraction caps, or alter verification thresholds based on source volume alone. Stop rollout if relevant unique-source yield or citation support falls, if provider spend exceeds the recorded budget, if resume redispatches uncertain calls, or if a preview leaks across tenants. A failed writer or reviewer leaves evidence and the honest partial/unassessed state inspectable.
