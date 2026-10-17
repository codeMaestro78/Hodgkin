# Academic Retrieval Quality and Research Canvas — Implementation Plan

**Status:** Partially implemented in the local checkout; evaluation and release gates remain open. This plan records the target design and does not imply that local changes are committed, deployed, or enabled in production.

**Purpose:** Fix poor evidence retrieval before increasing source limits, then present the resulting work as a genuinely useful, long-form research document in a navigable canvas. This is a **domain-general research system**: it chooses source strategies from the user's question and plan, not from one example topic. The canvas must make evidence, uncertainty, and coverage inspectable; a longer answer is not automatically a better answer.

## 1. Executive recommendation

Implement this as two connected capabilities with a shared report contract:

1. **Retrieval quality:** route each planned research dimension to an appropriate source channel; add academic-index adapters; rank and deduplicate candidate works before spending on extraction; preserve auditable counts and exclusion reasons; keep snippets and metadata out of the evidence ledger.
2. **Research canvas:** render the immutable structured report as a long-form, sectioned document with an outline, citation-to-evidence navigation, a dedicated evidence/source inspector, coverage and limitation states, and a persistent research activity/status view. The canvas is a presentation of persisted report data—not an untracked second answer generated in the browser.

Do **not** raise source or operation limits as the first intervention. First establish a reproducible baseline and demonstrate that better routing and screening increase relevant evidence and requirement coverage at similar or explicitly measured cost.

## 2. User and product problem

The Kafka-versus-Temporal report below is one concrete failure example used to make the problem measurable. It must not determine the product's default source mix, report structure, terminology, or evaluation set. The implementation should work for questions in software and systems, natural and social sciences, health, public policy, business, history, and other fields, selecting relevant source channels and report sections per run.

### 2.1 Observed example: Kafka versus Temporal research run (one regression fixture)

The supplied Balanced-mode run took **4m 11s**, collected 10 of 12 sources, completed four collection questions, and published 10 verified findings. However:

- Only three of the ten sources appear to have contributed published findings; the other seven were unrelated or generic pages (including an ACCA audit-evidence guide, enterprise-architecture governance, data governance, FinOps resilience, and a workload-prediction paper).
- The central comparison requirement was **not assessed**. Performance evidence under comparable workloads remained unresolved; no direct head-to-head benchmark was established.
- The report says narrative composition was not applied because remaining time was insufficient, so it fell back to a list of verified sentences.
- A generic line says coverage repair returns to the planner, but this trace shows an approval gate and no repair task. The bounded-repair design excludes approval-required runs; the displayed copy must not imply a repair occurred.
- “10 sources collected” obscures the distinction between discovered candidates, extracted pages, relevant evidence, and sources actually cited.

This is a retrieval precision, coverage assessment, and report usability problem—not evidence that the system should scrape more URLs. The run is an observed example, not a statistically representative quality/latency benchmark.

### 2.2 Domain-general product requirements

- Accept open-ended questions without requiring a user to know which database, publisher, or source category to choose.
- Infer a small, inspectable **research strategy** from question type, requested evidence, field/topic, date/freshness constraints, user filters, and available integrations. The system may recommend a strategy but must preserve user overrides.
- Support academic indexes where scholarly evidence is appropriate; official standards, specifications, government or institutional records where authoritative rules/data are appropriate; primary documents and datasets where the question calls for them; and web sources for current practice, reporting, or explicitly requested gray literature.
- Do not force every topic through academic search. For example, a current product API behavior question should prioritize primary vendor documentation; a historical question may need archives and primary records; a literature review may require academic indexes. Provider availability and source policy can narrow these options.
- Keep source strategy modular: adding a provider should not change the report contract or make unrelated providers mandatory.

### 2.3 Product need

Users need to understand, at a glance:

- What the research found and what it did not establish.
- How the answer addresses the original question and its planned dimensions.
- Which factual statements have verified citations and how to inspect the exact evidence.
- Which sources were discovered, extracted, relevant, cited, excluded, or unavailable—and why.
- Whether the report is still being assembled, partially complete, complete with unresolved gaps, or failed.
- Where they are in a long report, without losing the evidence and run context.

The desired result is a **comprehensive, evidence-rich research document**, not a forced word count. When evidence is sparse, the product should explain the gap rather than manufacture length.

## 3. Current implementation inventory (checked 2026-10-17)

This is a local-checkout inventory, not a claim of hosted deployment or database rollout.

| Area | Current evidence | Consequence |
|---|---|---|
| Discovery providers | New jobs can pin Tavily/Serper plus an optional OpenAlex academic route. OpenAlex is selected only for tasks whose persisted source classes request academic material; Tavily remains the extraction path. The flag defaults off. | Existing/queued jobs retain their pinned route; OpenAlex does not replace web discovery globally. |
| Planned source classes | `PlannedQuestion.source_classes` accepts academic/official/etc. (`builder.py`); academic requests now select OpenAlex only on OpenAlex-capable job versions. | A planner hint is still not a source-quality or coverage guarantee. |
| Candidate selection | Serper retains its provider-order shortlist. OpenAlex now has deterministic lexical ranking, DOI/OpenAlex work deduplication, extract-URL deduplication, and bounded exclusion receipts under `academic-lexical-topk-v1`. | Scores are ordering features only; relevance precision/recall and source independence remain unvalidated. |
| Evidence admission | The documented invariant is that snippets and metadata are untrusted discovery data; only extracted, preserved text enters `Source` and citation verification. | Preserve this boundary for academic search results and abstracts. |
| Source metadata | `Source` stores publisher, provider, source class, publication time, quality score, discovery paths, and content hash (`db/models.py`). OpenAlex-selected extracted sources are persisted as `provider="openalex"`, `source_class="academic"`; web sources retain their prior mapping. | Academic class comes from the selected academic adapter, not from planner intent alone; DOI/work metadata remains in the private discovery receipt. |
| Work relationships | `source_identity.py` and source-relationship persistence are conservative. An observed DOI can identify a work; DOI alone does not establish peer review, independence, publisher, or support. | Extend identity mapping from verified adapter metadata without overstating independence. |
| Report contract | Immutable structured report versions, assessed requirements/dimensions, conflicts/provenance, and evidence-verified narrative composition exist locally; see `research-modes-implementation-status.md`. Narrative is time- and evidence-bounded, not guaranteed on every run. | The canvas should render persisted report versions and their status; it must not recreate report facts in the client. |
| Existing report UI | `app/(research)/research/[runId]/page.tsx` already renders report sections, citation interactions, coverage, and sources; `research-workspace.tsx` shows “Not quoted in the answer” versus cited/collected. | Evolve the existing workspace and evidence inspector, not a parallel report product. |
| Repair | Bounded repair has explicit eligibility and exclusions in `bounded-gap-repair-design.md`. | Report/UI language must distinguish “eligible,” “attempted,” “added evidence,” “no gain,” and “not eligible.” |

Key repository references:

- `services/research-api/src/research_api/graph/builder.py`
- `services/research-api/src/research_api/providers/tavily.py`
- `services/research-api/src/research_api/providers/serper.py`
- `services/research-api/src/research_api/ingestion.py`
- `services/research-api/src/research_api/source_identity.py`
- `services/research-api/src/research_api/db/models.py`
- `services/research-api/src/research_api/report_document_v4.py`
- `services/research-api/src/research_api/narrative_composer.py`
- `apps/web/app/(research)/research/[runId]/page.tsx`
- `apps/web/app/components/report-coverage.tsx`
- `apps/web/app/components/research-workspace.tsx`
- `docs/implementation/index-first-discovery-adapters.md`
- `docs/implementation/research-modes-and-comprehensive-reports-plan.md`
- `docs/implementation/research-modes-implementation-status.md`
- `docs/implementation/bounded-gap-repair-design.md`

## 4. Product and architecture principles

1. **Evidence first, prose second.** The verified claim/citation ledger remains the only authority for published factual statements.
2. **Metadata is not evidence.** Candidate titles, abstracts, snippets, search rank, and citation counts may help retrieve and screen. They are not exact source passages and must not be cited as if full text had been reviewed.
3. **A discovered item is not a useful source.** Maintain separate lifecycle counts and definitions.
4. **Coverage is assessed, not inferred from volume.** A dimension is covered only when its explicit criteria are assessed against verified claims. Links between sources, findings, and dimensions are not proof of coverage.
5. **Comparison requires comparable evidence.** Do not infer a winner from separate product feature claims. Mark missing head-to-head or comparable benchmark evidence explicitly.
6. **Long-form does not mean inflated.** Mode-specific depth changes research effort, coverage, report organization, and supported detail—not a target number of words.
7. **Durability and tenant boundaries remain authoritative.** Durable receipts/checkpoints and PostgreSQL remain the replay/source-of-truth mechanisms. Caches and UI state are disposable projections.
8. **No broad scraping or scraping around access controls.** Fetch full text only from supported/authorized open-access locations or authorized user-provided sources; respect provider, publisher, and repository terms.

## 5. Target retrieval flow

```text
Versioned research brief and coverage plan
            │
            ├── strategy selected from question/plan ── academic indexes when relevant
            ├── strategy selected from question/plan ── official/primary records when relevant
            ├── strategy selected from question/plan ── datasets/archives/domain sources when relevant
            └── strategy selected from question/plan ── general web when relevant
                         │
                normalized candidates
                         │
       metadata/relevance screen + work deduplication
          ├── rejected + reason (private audit receipt)
          └── bounded shortlist
                         │
              authorized text extraction
                         │
            preserved Source artifacts
                         │
      exact quote + semantic support verification
                         │
        assessed coverage and immutable report
                         │
                   research canvas
```

Provider calls stay behind existing reservation, attempt, quota, cancellation, and replay boundaries. Network calls must not hold database admission transactions open. Successful discovery receipts must be reusable after restart without redispatch or reranking.

## 6. Retrieval implementation phases

### Phase R0 — Baseline, labels, and report truth (first)

**Purpose:** Know whether the change improves useful evidence rather than merely returning more records.

**Work:**

- Preserve the supplied run as a redacted, offline evaluation fixture: original question, mode, frozen coverage dimensions, source metadata/URLs, extracted artifact references or approved fixture excerpts, published findings, assessment states, operation counts, cost estimates, and timing stages.
- Add a manual relevance label per `(candidate, dimension)` and source-type label with a short reason. Have a second reviewer adjudicate disagreements for the evaluation set.
- Define counters precisely: `discovered`, `screened_in`, `screened_out`, `extract_attempted`, `extracted`, `dimension_relevant`, `cited_in_verified_finding`, `unavailable`, and `duplicate_work`.
- Record stage timings separately: plan, discovery by provider/dimension, screening, extraction, verification, synthesis, and total wall time. Keep retries and approval wait separate from active provider time.
- Correct the repair/status projection so a report says whether repair was ineligible, skipped, attempted, added verified evidence, or produced no gain. Do not imply an attempt from generic help text.

**Persistence:** Reuse the run’s existing immutable brief/plan, provider receipts, source records, claim checks, coverage assessment, and report version wherever they already represent the fact. Candidate-level exclusion reasons belong in a bounded private receipt tied to tenant/run/provider request fingerprint and policy version. Do not add a candidate table solely to show a count.

**Exit gate:** The supplied run reproduces the observed low relevance and unresolved dimensions, and the baseline set also includes materially different domains and source needs before any routing policy is declared generally useful. Every count has a documented denominator. Evaluation artifacts contain no credentials or unnecessary private source text.

### Phase R1 — Versioned query routing and first domain-appropriate adapter

**Target files:**

- Add the first adapter selected by the strategy matrix. For the observed regression case, that is `services/research-api/src/research_api/providers/openalex.py`; do not hard-code OpenAlex as the global or default route for all questions.
- Add provider contract/normalization types under `providers/` (only if the current shared request/receipt contract cannot express provider metadata without contaminating Tavily/Serper behavior).
- Extend `config.py` with explicit enablement, API key, timeout/rate settings, and no-secret logging rules.
- Extend `graph/builder.py` to route dimension-specific strategies. Do not choose a provider solely from free-form LLM text; validate a closed strategy enum in the persisted plan.
- Extend `ingestion.py` and repository mapping to persist metadata basis and observed identity conservatively.
- Update `research_limits.py` only if a distinct academic-operation class is needed; preserve total operation and source ceilings.
- Add provider unit tests, receipt replay integration tests, and contract snapshots.

**Candidate fields (bounded contract):** adapter and adapter schema version; provider work ID; DOI (normalized); title; authors; year/date; venue/source; work type; abstract (metadata only); citation count with observation timestamp; OpenAlex/S2 IDs; open-access status; separate landing-page and PDF URLs; query/dimension ID; raw provider rank/score; normalized metadata basis; and candidate rejection reason. Bound string lengths, arrays, page size, and total candidate count.

**OpenAlex behavior for academic strategies:** use `/works` search/filter/select with small result pages and explicit fields. Support an API key through a secret header or provider-approved mechanism, capture documented usage/cost metadata, bound request rate, and handle 429 with bounded backoff. Do not assume that a free starting tier means unlimited access. Resolve text locations in this order: readable `best_oa_location` landing page, other `locations[].landing_page_url`, then a permitted PDF URL; DOI resolver is metadata/navigation, not automatically an extractable full-text URL. Keep landing page and downloadable PDF as separate values. These behaviors apply only when the plan routes a dimension to scholarly works.

**Query routing:** a question’s `source_classes` become validated routing requirements, not appended phrases only. Use a small, extensible strategy vocabulary selected by a versioned planner policy; validate the result and allow user-specified source constraints. Example strategies (not a mandatory set for every run):

- `academic_index`: OpenAlex for the first scholarly adapter; Semantic Scholar later/parallel only under measured value and budget.
- `official_primary`: official documentation, standards, laws/regulations, government publications, or other primary records appropriate to the topic.
- `dataset_or_archive`: domain-specific datasets or archives, only where an identified question requires them and terms/access are supported.
- `general_web`: Serper/Tavily for current practice, reporting, or gray literature, visibly categorized and not silently substituted for a requested source class.

The strategy set and adapter versions are frozen in the run brief/checkpoint so resume, approval, and replay cannot silently change retrieval semantics.

**Exit gate:** mocked provider behavior covers auth secrecy, malformed results, missing metadata, pagination cap, 429, timeout/uncertain dispatch, retries, duplicate DOI, DOI conflict, and open-access URL mapping. A crash after search reuses the same shortlist receipt and does not spend another search call. No candidate snippet is admitted to citation verification.

### Phase R2 — Semantic Scholar adapter and controlled source expansion

Add `providers/semantic_scholar.py` with explicit requested fields (including `citationCount` only if ranking consumes it), API-key/rate-limit behavior, provider receipt identity, and the same normalized candidate contract. Keep each provider adapter independently feature-flagged and independently metered. Academic providers are optional strategy modules, not a dependency for non-academic research.

Do not execute both academic providers for every dimension by default. Use matched offline evaluation to decide whether S2 adds useful unique works or coverage beyond OpenAlex at acceptable cost/latency. Any later source adapter (e.g., PubMed/Europe PMC for biomedical work, official government-data adapter for public statistics, or archive adapter for historical records) must be justified by observed user demand and a measurable retrieval gap, not added as generic plumbing.

**Exit gate:** same questions and budgets compare OpenAlex-only vs. OpenAlex+S2; additional adapter is retained only if it improves relevant unique works/coverage or another agreed user outcome without a material unacceptable cost/latency regression.

### Current implementation status (local checkout)

- Implemented locally: opt-in `OPENALEX_DISCOVERY_ENABLED` and optional `OPENALEX_API_KEY`; new jobs pin an OpenAlex-capable graph version; academic-planned tasks use OpenAlex while other tasks retain the job's Tavily/Serper route.
- Implemented locally: bounded metadata normalization, lexical top-k policy `academic-lexical-topk-v1`, DOI/OpenAlex identity deduplication, canonical extract-URL deduplication, reason-coded candidate receipts, capped API page size, and no use of abstracts as source evidence.
- Implemented locally: the candidate catalogue and shortlist are written to the existing tenant/run/request-fingerprint-bound provider response artifact; restart replay uses that receipt without another search dispatch. OpenAlex-reported `meta.cost_usd` is recorded as settlement cost; absent cost metadata uses the conservative reservation estimate. Transport attempts are recorded, known pre-dispatch failures may retry, and post-dispatch uncertainty is retained.
- Implemented locally: selected extracted rows are marked with the adapter-backed `openalex` provider and `academic` source class. Shared schema enums are updated; no database migration was added.
- Exploratory metadata evaluation: [OpenAlex retrieval evaluation (2026-10-17)](./openalex-retrieval-evaluation-2026-10-17.md) reviewed 12 queries with one unblinded reviewer. It found 20/48 provisional direct constraint matches for the lexical shortlist, 22/48 for OpenAlex default ordering, and 39/48 for native reranking. The reranked result page was a different candidate pool, so this does not isolate ranking, and these labels are not a gold-standard quality result.
- Not yet established: representative adjudicated relevance precision/recall, dimension coverage improvement, useful extracted-source yield, verified citation/answer quality, source independence, or an end-to-end latency/cost benefit. The feature flag remains off by default. The metadata evaluation did not use model synthesis or text extraction and does not validate the final research outcome.
- Validation: unit tests cover request bounds, normalization, rank/dedup receipts, cancellation/retry outcomes, and route pinning; a disposable PostgreSQL integration test covers receipt persistence, restart replay, tenant scoping, source metadata, and reported-cost settlement. This is not a hosted rollout or a representative, independently judged quality evaluation.

### Phase R3 — Screening, ranking, and auditable exclusion

Build a deterministic first-pass screener before extraction:

- Match candidate title/abstract to a specific plan dimension, not just the root prompt.
- Use normalized lexical relevance and structured source metadata first. A learned reranker may be evaluated later; do not introduce vector storage or a new model call before a measured need.
- Apply explicit topical exclusions and source-type policy. Keep preprints, official documentation, academic articles, vendor material, and general web sources as distinct categories.
- Deduplicate by normalized DOI/work identity, then canonical URL/content hash; title/year fuzzy matching may nominate duplicates but must not silently merge uncertain records.
- Diversify the shortlist across unique works and useful source classes without claiming that publisher/domain difference proves independent evidence.
- Store candidate rank, features used, selection policy version, and one or more bounded rejection reasons in the private durable receipt. Do not expose raw snippets as report evidence.

**Exit gate:** on adjudicated labels, screening improves relevance precision at the extraction cutoff without materially reducing recall of relevant works or coverage of mandatory dimensions. Report exact precision/recall and label counts; do not present an unvalidated rank score as probability or source quality.

### Phase R4 — Extract, verify, assess, publish

- Extract only the selected candidates, using an allowed accessible full-text URL; abstract-only records can support discovery/metadata but must be clearly marked as abstract-only if admitted under a future explicitly designed evidence policy.
- Persist extracted text in existing private artifact storage and source rows; persist DOI/work/venue/authors/year and metadata provenance without treating these as claim support.
- Link extracted sources and verified claims to stable plan dimension IDs. Use current exact-span and fully supportive semantic checks unchanged.
- Assessment should state `verified_covered`, `evidence_found_unresolved`, `not_assessed`, `blocked`, or `unresolved` with basis and linked claim/source IDs; never infer coverage from source links or collection completion.
- For comparisons, require direct comparable evidence for benchmark claims. Otherwise report the evidence gap plainly and distinguish primary documentation from independent measurement.

**Exit gate:** all published claims still pass existing gates; report answer-quality status remains honest when dimensions lack evidence; no evidence from a search snippet or metadata-only abstract is presented as a reviewed passage.

## 7. Research Canvas experience

### 7.1 Design intent

Build an editorial research workspace, not a chat transcript and not a generic dashboard. The report is the primary surface; evidence and execution are inspectable companion panes. Long-form text should remain calm and readable while citations, source details, and the table of contents make navigation immediate.

### 7.2 AnswerThis reference: documented workflow and design lessons

The [AnswerThis full guide](https://answerthis.io/blog/full-guide) (published November 4, 2025; reviewed for this plan on October 17, 2026) describes a connected academic-research workflow. This is a **first-party product guide**, not an independent usability study or technical architecture disclosure. Treat described capabilities as the vendor's published account; validate the live product separately before copying any behavior or claiming feature parity.

#### What the guide documents

| Workflow / surface | Guide-described behavior | Transferable UX lesson for our product |
|---|---|---|
| Choose the work type | Quick Q&A for fast, source-aware answers; Full Review for a structured literature synthesis; separate Search Papers workflow for building/curating a corpus. | Make the user's intended outcome explicit. Distinguish a fast answer from a deeper report and from source collection; do not let a UI mode silently change because of a small budget. |
| Scope retrieval | More Filters selects databases and web/patent scope, publication/date bounds, journal quality and citation thresholds; examples include OpenAlex, Semantic Scholar, PubMed and arXiv. | Offer understandable, optional scope controls and sensible recommendations based on question/domain. Explain trade-offs; do not make one academic database or web search universal. |
| Review a long result | Citation style and Notebook controls sit near the review; citations navigate into source details; tables can be saved into the writing workspace. | Keep the report readable and connect citations to evidence without losing the user's reading position. Make report actions available in context. |
| Inspect source rows | The guide describes author/year/venue-quality/DOI/citation metadata, abstract text highlighted against the query, and user-added columns such as methods, findings, gaps, metrics, datasets, benchmarks and limitations. | Make source evidence scannable and let users inspect structured attributes relevant to the question. Show metadata provenance and distinguish abstract-level context from full-text evidence. |
| Curate sources | Users can sort/filter, select multiple papers, save to Library, create a filtered table, and export structured source lists. | Support progressive curation: search result → selected shortlist → saved project collection. Keep source organization actions separate from the report's verified evidence status. |
| Continue research | Follow-up questions can be launched from a report subsection with source filters and their own source table; the guide describes sending useful passages/tables into Notebook. | Preserve context and let a user deepen one section without losing the parent report. Each follow-up must remain a separately versioned investigation linked to—not silently overwriting—the original report. |
| Write with sources nearby | Notebook/Full Notebook places writing beside Review, Sources, Analysis and Library; selected text can be saved with source metadata, and citations are inserted into a bibliography. | A canvas can support both reading and drafting, but keep generated research immutable and distinguish it from user-authored draft text. Source-linked saved blocks should retain stable claim/citation references. |
| Collaborate and reuse | The guide describes invitations/sharing, project libraries, uploaded PDFs/reference-manager imports, paper chat, and library reuse in later syntheses. | Design for persistent projects and reuse, with explicit permissions. Uploads and sharing need their own authorization, retention and evidence provenance; they are not implied by a visual panel. |

#### What not to infer or copy blindly

- The guide's marketing language about comprehensiveness, accuracy, or reading thousands of papers is not an independently verified quality guarantee. Our report must show measured coverage and limitations instead of adopting those promises.
- The guide does not reveal AnswerThis's internal retrieval ranking, full-text licensing, persistence model, model prompts, verification rate, latency, or actual backend architecture. We should not state that it uses a particular algorithm based on UI descriptions.
- Journal quartiles, citation counts, abstract highlights and provider rank can aid discovery or screening but do not prove that a source supports a claim, is independent, or is suitable for every field. Preserve our existing exact-passage and semantic-support gates.
- AnswerThis is positioned around academic research. Our product is domain-general: use its connected reading/curation/writing workflow as inspiration, but select sources, analytical structures, metadata fields and sections from each user's question and evidence needs.
- Do not reproduce its brand, colors, exact layout, copy, or proprietary interactions. The reference is workflow-level inspiration, not a visual clone specification.

#### Product implications

1. Add a clear task-intent choice/summary (quick answer, deep report, find/curate sources, continue an existing investigation) while preserving explicit mode and budget semantics already specified in the research-modes plan.
2. Put scope controls in an optional, plain-language panel: date range, source channels, include/exclude domains or collections, and field-specific filters only when the selected adapter supports them. Show which filters actually ran.
3. Treat the report and evidence as a linked workspace: report outline and long-form reading in the center; citation-linked evidence/source detail on demand; persistent source organization and follow-up entry points.
4. Let users save verified report passages, evidence references, and selected sources into projects/library without copying ungrounded text or losing original report/version attribution.
5. Make structured extraction configurable by task (e.g. methods/results/limitations for research papers; version/guarantee/date for software docs; dataset/measure/period for statistics). Persist extraction schema/version and exact source location; render “not available” instead of fabricating a cell.
6. Keep editable user drafting separate from immutable report content. If a future editor can rewrite research prose, every changed factual statement must re-enter the same claim/citation verification path before it is labeled evidence-backed.

### 7.3 Desktop layout

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Workspace / report title       status · mode · saved     Export / Share  │
├───────────────┬──────────────────────────────────┬───────────────────────┤
│ Outline       │ Research document                │ Evidence inspector    │
│               │                                  │                       │
│ Summary       │ Executive answer                 │ Selected citation     │
│ Findings      │ Coverage and key conclusion      │ Exact passage         │
│ Comparison    │                                  │ Source metadata        │
│ By dimension  │ Findings with inline citations   │ Work / DOI identity    │
│ Limitations   │ Tables and synthesis             │ Related sources       │
│ Method        │                                  │                       │
│ References    │ Long-form sections               │                       │
├───────────────┴──────────────────────────────────┴───────────────────────┤
│ Collapsible activity/status strip: plan → collect → assess → compose     │
└──────────────────────────────────────────────────────────────────────────┘
```

**Layout rules:**

- Retain the existing research workspace shell and its independent scroll behavior where appropriate. Keep report text in a centered, measure-limited reading column; do not stretch paragraphs across a full desktop monitor.
- Left outline can collapse. The center document owns the primary scroll. The evidence inspector can be independently scrolled and should keep its selected citation visible.
- Execution activity is a collapsible/status surface; it must not force users to scroll to discover failure or completion. On terminal failure/partial completion, show a persistent, accessible summary near the title and a route to inspect details.
- Citation click selects/highlights the matching passage in the inspector and keeps reading position. Back/forward navigation returns to the report location.
- Tables compare only evidence-backed cells; missing comparisons display “Not established from collected evidence.” Long tables scroll horizontally within their region, not the entire page.

### 7.4 Mobile layout

- Use natural document scrolling, not nested fixed-height panes.
- Replace simultaneous outline/evidence columns with accessible drawers or tabs: **Report**, **Outline**, **Evidence**. Opening evidence should preserve the report anchor and allow return to it.
- Keep citations as large enough touch targets; do not rely on hover. Tables become stacked comparisons or have an explicit horizontally scrollable region with a visible cue.
- Preserve failure/partial status and key coverage summary without a sideways overflow.

### 7.5 Long-form document structure

Render sections conditionally from the persisted structured report; do not create empty headings merely to make a report look complete. The schema should express reusable section roles and evidence/coverage relationships; the UI must not assume every field has the same domain-specific vocabulary or require a Kafka/Temporal comparison table. A comparison section appears only when the user's question is comparative and the evidence supports comparable rows/cells.

1. **Executive answer** — direct, bounded answer and confidence/coverage status, with citations on factual statements.
2. **Evidence-backed synthesis** — organized by the question's actual dimensions (for example, findings, causal explanation, chronology, policy options, or comparative criteria).
3. **Optional analytical structures** — comparison tables, timelines, methods/effect summaries, datasets, case studies, or other structures only when relevant to the requested task and supported by evidence.
4. **Conflicts and source relationships** — show assessed disagreement and provenance; “none recorded” is not equivalent to “no conflict exists.”
5. **Limitations and open questions** — include missing benchmark, recency, source-type, data, or coverage limitations relevant to the topic.
6. **Method and evidence accounting** — mode and policy version, source-stage counts, providers/databases queried, search date, filters, repair outcome, and verification limits.
7. **References and evidence** — applicable bibliographic/source metadata, stable identifiers when available, original links, exact cited passages, and extraction/source status.

The displayed detail should follow mode policy and evidence availability. Focused should be concise and answer-first; Balanced should cover the planned dimensions and meaningful trade-offs; Deep should spend more effort on breadth, conflicting evidence, limitations, and detailed dimensional synthesis. Deep must not be promised to be “comprehensive” until cross-mode evaluation demonstrates better coverage at citation-quality parity.

### 7.6 Canvas states and interactions

- **Streaming report:** sections appear only after their persisted report version/state is available. Mark draft/live content and final immutable version distinctly. Never show generated prose as final before verification.
- **Partial/low evidence:** use a clear “Evidence is incomplete” banner, state what was established, show unanswered dimensions and why, and offer a scoped follow-up. Do not fill whitespace with generic filler.
- **Completed with gaps:** “Research finished; these requirements remain unresolved.” Counts and section outline reflect actual content.
- **Failed:** persistent error summary, last completed stage, preserved-evidence link, retry/fresh-attempt action with cost warning where relevant. Do not bury failure below execution details.
- **Repair:** show “not eligible,” “not attempted,” “attempted—no new verified evidence,” or “added N verified findings”; do not imply repair from a generic lifecycle description.
- **No sources / no verified claims:** use a short recovery-oriented empty state; keep collected records available if they exist.
- **Citation interaction:** citation focus, exact passage, source metadata, and report claim shown together; keyboard users can open/close inspector and return to origin.
- **Copy/export:** export only the persisted report version and include citations/method/limitations consistent with the selected format.

### 7.7 Visual and motion system

- Reuse landing-page brand tokens and existing report colors; do not introduce a competitor’s palette or a second visual language.
- Use typographic hierarchy and whitespace to distinguish document title, section headings, findings, citations, and metadata. Keep body line length around 65–80 characters and comfortable line-height.
- Prefer stable panel transitions and selected-citation highlighting over ambient animation. Motion should explain an action (open inspector, jump to evidence, reveal progress); respect `prefers-reduced-motion` and avoid animating large report content during streaming.
- Preserve visible keyboard focus, semantic headings, landmarks, list/table semantics, and non-color status indicators.

## 8. Persistence and contract design

### Source of truth

- **Run brief/coverage plan:** frozen user intent, dimensions, query strategies, and policy version.
- **Provider reservations/calls and private receipts:** provider request identity, attempt accounting, candidate catalogue, shortlist, rejection reasons, and replay input.
- **Source and artifact records:** extracted/preserved content and normalized bibliographic metadata with provenance.
- **Verified claims/citations and assessments:** factual publication authority and requirement outcomes.
- **Immutable report document:** rendered report version, section order, claim/citation links, method/count snapshot, and repair outcome.
- **UI state:** selected section, open panel, search/filter; local/user preference only, never evidence truth.

### Schema changes

First map candidate and report data to existing records before proposing a migration. If new persistence is required, prefer a single bounded tenant/run-scoped candidate receipt/artifact contract rather than a general-purpose source-index database. Any table or artifact reference must define tenant/run authorization, RLS/grants if table-backed, retention/deletion, maximum size/count, schema version, encryption/access boundaries, and replay behavior. A migration is a separate reviewed deliverable; no hosted migration is part of this plan.

### Replay invariants

- Pinned run plan/provider/policy version controls resume; changing a feature flag affects new runs only.
- Successful search receipt replay reuses candidate ordering and screen decision without another provider charge.
- If a receipt is missing, corrupt, cross-tenant, or schema-incompatible, do not silently redispatch, refund, or use snippets. Move to a clear recovery-needed outcome.
- Extraction and model calls keep existing attempt-aware uncertainty and accounting behavior.
- Every report document and export is bound to an immutable report version/content hash.

## 9. Measurement and acceptance gates

### Quality measures

- Candidate relevance precision at the extraction cutoff, with adjudicated labels and sample size.
- Relevant-work recall on the labeled candidate pool; unique works after DOI/canonical dedup.
- Mandatory-dimension coverage and requirement assessment status.
- Verified citation precision/support and citation completeness; no weakening of existing exact-span or semantic gates.
- Source-class distribution and provenance completeness; independence remains unknown unless explicitly supported by observed relationships.
- Direct-comparison evidence count for benchmark claims; missing benchmark must remain a visible gap.
- Useful report coverage and human usefulness ratings—not word count alone.

### Latency and cost measures

Measure p50/p95 on a fixed workload and separate cold/warm, approval waiting, provider time, queue delay, database time, and client-visible time. Record per-provider calls, retries, estimated/returned provider cost, model usage, extraction operations, and total run cost. Do not call two matched runs a p95 estimate or a generic provider price an invoice.

### Required tests before any live rollout

- Adapter request/response schema, API-key secrecy, rate limiting, retry and timeout uncertainty, malformed/missing fields, URL normalization, work deduplication, metadata sanitization.
- Candidate screening determinism, versioned policy behavior, rejected-reason bounds, no snippet/abstract entering citation evidence.
- Cross-tenant receipt isolation; artifact deletion and retention; replay after crash before/after shortlist binding; duplicate worker/admission races; cancellation during discovery/extraction.
- Provider outage/429/empty index results: graceful fallback only when allowed by the pinned route and visibly recorded; no silent provider substitution.
- Report contract: counts reconcile, source categories do not overclaim, unresolved status matches run, repair wording matches recorded outcome.
- Canvas: long title, 50+ sections/findings, wide comparison table, missing citations, 0/1 source, long references, partial/failure states, keyboard-only citation navigation, mobile overflow, reduced-motion preference, screen-reader labels.
- Regression gate: all published factual statements still map to verified claim/citation IDs; existing reports and old report versions remain readable.

### Offline then live sequence

1. Reproduce the pasted Kafka/Temporal run from a fixed fixture as **one** regression case.
2. Build a balanced evaluation set across distinct question types and source needs: academic literature, current technical/product facts, official rules/policy, quantitative/data questions, historical/contextual questions, and comparative synthesis. Include both questions where academic search is appropriate and where it should not dominate.
3. Compare each question's existing route against the strategy selected for it, holding question, plan, mode, operation/source ceilings, model routes, and evidence gate constant.
4. Blind human review of candidate relevance and answer usefulness; reviewers must not know which route produced the candidate set.
5. Only after fixture and regression gates pass, request explicit authorization for a small paid live validation. Do not change provider limits or run budgets to make the new route appear better.
6. Expand only if relevance/coverage improves across applicable domains without unacceptable citation-quality, latency, cost, or source-access regressions.

## 10. Delivery order and dependencies

| Order | Deliverable | Exit gate |
|---|---|---|
| 1 | Domain-diverse fixtures, adjudication protocol, and stage-count definitions | Exploratory 12-query run is retained as diagnostic only; representative questions, blinded labels, and reviewer adjudication are still required |
| 2 | Versioned OpenAlex routing behind the disabled-by-default flag | Implemented locally; tenant/replay/unit coverage exists. Production remains gated on independently judged quality and end-to-end usefulness |
| 3 | Candidate screening, DOI/work dedup, durable rejection receipt | Implemented locally, but the current lexical selector did not beat provider default in the exploratory sample; do not call its relevance gate validated |
| 4 | Semantic Scholar adapter, independently flagged | Not implemented. Add and evaluate only as an experiment to test unique relevant-work yield against OpenAlex, after defining an authorized matched workload and cost cap |
| 5 | Report/API source-accounting projection and method snapshot | RunInsights retains live run-scoped activity. A separate nullable report-row snapshot is captured before publication, returned with the selected report version, shown as frozen in the canvas, and included in the report integrity hash. Legacy reports remain null; unknown relevance/usefulness/independence remain unassessed. Migration `0018` is new and still requires disposable-Postgres validation before local app use |
| 6 | Desktop/mobile canvas over the immutable report contract | Existing workspace includes report outline, evidence inspector, citation navigation, coverage, run-level retrieval accounting, and repair outcome. Component tests cover repair state/accessibility; full browser long-report, mobile, and screen-reader acceptance remains open |
| 7 | End-to-end matched evaluation and limited authorized live validation | Not passed. Keep OpenAlex disabled until relevance, extracted-source yield, verified citation quality, cost, and latency gates meet agreed thresholds |

Retrieval phases 1–5 can proceed before the full canvas redesign. The canvas should begin with its state and component contract while adapter work proceeds, but it must not invent candidate statuses until backend/API accounting exists.

### Current implementation checklist (2026-10-17)

- [x] Preserve the 12-question OpenAlex metadata evaluation as exploratory evidence only; keep the production flag disabled.
- [x] Persist count-only retrieval receipts and expose a conservative run-level accounting projection. Per-provider extracted and cited counts use persisted source/citation records; missing discovery data stays `null`, not zero.
- [x] Add a Methodology panel that explains the distinction between recorded activity and quality, and says relevance/independence are not assessed.
- [x] Extend the run-level funnel to separate recorded extraction outcomes and exact-span/semantic citation checks; keep answer usefulness explicitly unassessed.
- [x] Add publication-time retrieval accounting to immutable report rows; include the snapshot in the integrity hash and expose it as the selected report version's accounting. Historical reports remain null rather than receiving inferred retrospective counts.
- [x] Include a deterministic, count-only retrieval-accounting section in newly published report Markdown and exports; explicitly mark usefulness, relevance, and independence as unassessed.
- [x] Validate concurrent repair admission and cancellation/restart behavior on a disposable PostgreSQL database; render stopped/repaired outcomes with a polite live region.
- [x] Draft a 20-case, domain-diverse retrieval workload with explicit requirements, academic-search applicability, and a blinded-review rubric (`services/research-api/evaluation/retrieval/v1`).
- [x] Add an offline blind-packet and same-candidate-pool scorer with frozen-pool SHA-256 validation, required per-candidate/per-requirement labels, raw agreement, third-reviewer adjudication, and per-domain/macro metrics (`research_api.retrieval_review`). The scorer is tooling only; no candidate pool has been frozen or human labels collected.
- [ ] Freeze one controlled candidate pool per case and obtain independent blinded labels. The 20 cases are draft questions, not a gold set.
- [ ] Conduct blinded independent candidate adjudication and score relevance precision/recall, requirement coverage, duplicate/version rates, and reviewer agreement.
- [ ] Measure the complete path: discovered → shortlisted → extract attempted/succeeded → source persisted → exact/semantic checks → cited verified finding → answer usefulness, with latency and cost.
- [x] Validate migration `0018` on disposable PostgreSQL, including published snapshot insertion/readback and trigger rejection of snapshot mutation; validate graph publication, API readback, replay stability, and integrity hash coverage on the same isolated database.
- [ ] Apply migration `0018` to any shared or hosted database only after target identification and separate authorization; no shared local or Supabase migration was performed.
- [ ] Complete browser-level long-report/mobile/accessibility/failure-state checks; unit rendering alone does not prove scroll containment or responsive behavior.
- [ ] Decide on Semantic Scholar only after blinded matched-pool evidence demonstrates incremental unique relevant-work yield at acceptable cost and latency.
- [ ] Keep OpenAlex disabled until the quality and end-to-end usefulness gates pass. No live provider evaluation was run in this implementation slice.

## 11. Explicit non-goals for this slice

- Increasing source count, operation count, wall-clock budgets, or paid model spend as a substitute for relevance.
- Building a crawler, scraping paywalled/full text without authorization, or indexing every candidate permanently.
- Treating abstracts, snippets, citation counts, journal ranking, or search rank as claim evidence.
- Claiming source independence based on different URLs/domains/publishers alone.
- Introducing a vector database, generic autonomous multi-agent framework, or new queue because it is fashionable.
- Guaranteeing a minimum word count or promising that Deep is superior before evaluation.
- Replacing citation verification, requirement assessment, or immutable report persistence with client-side generation.
- Applying a migration, changing Supabase, deploying, or running paid live searches without separate authorization.

## 12. External references

### Academic retrieval

- OpenAlex, [API reference](https://help.openalex.org/api/) — work search, filters, selected fields, paging, response metadata/cost.
- OpenAlex, [Authentication and rate limits](https://help.openalex.org/api/authentication/) — API-key behavior, budgets, request limits, 429 handling, and usage fields.
- OpenAlex, [Filtering](https://help.openalex.org/api/filtering/) — work type, dates, open access, citation-count and related filters.
- Semantic Scholar, [Academic Graph API](https://api.semanticscholar.org/api-docs/) — paper search, field selection, pagination, and graph metadata. Verify current quotas/auth at implementation time.

### Research workflow reference

- AnswerThis, [Full guide: AI Research Assistant for Academic Research](https://answerthis.io/blog/full-guide), Ryan McCarroll, November 4, 2025 — first-party descriptions of Quick Q&A vs. Full Review, filters, paper/source tables, citations, Notebook, follow-ups, libraries, exports, collaboration, and paper chat. Reviewed October 17, 2026. Vendor workflow descriptions only; not an independent performance or quality evaluation.
- AnswerThis, [Academic search engine feature page](https://answerthis.io/home/features/academic-search-engine-ai) — vendor claims about corpus size and features are marketing claims; counts vary across its own pages and are not used here as verified dataset facts.

### Long-document loading and accessibility

- Next.js, [Linking and navigating: streaming](https://nextjs.org/docs/app/getting-started/linking-and-navigating) — route-level loading UI, streaming, and client transitions.
- Next.js, [Fetching data](https://nextjs.org/docs/app/getting-started/fetching-data) — component-level Suspense/streaming patterns and their blocking boundaries.
- W3C, [WCAG 2.2](https://www.w3.org/TR/WCAG22/) — applicable requirements for focus, keyboard interaction, reflow, semantics, and motion-related accessibility.

## 13. Decision record

**Recommendation:** keep the locally implemented OpenAlex adapter feature-flagged off until the adjudicated, domain-diverse relevance and coverage evaluation passes. Design the research canvas against existing immutable report contracts in parallel. Do not increase source or operation ceilings to compensate for weak candidate yield.

**Confidence:** high that the supplied run demonstrates low relevance and unresolved coverage; medium that question-driven, domain-appropriate routing and pre-extraction screening can address the observed class of failure; low on which adapter mix will work best across domains and on expected latency/cost improvement until measured.

**Decision-changing evidence:** if labeled offline evaluation shows OpenAlex/Semantic Scholar candidates are not more relevant or do not improve dimensions covered at acceptable cost, retain index support as a user-selectable option and improve official/web query routing instead. If the canvas’s current structured report cannot represent required section/status detail without breaking immutable readers, define a new additive report schema version before UI implementation.
