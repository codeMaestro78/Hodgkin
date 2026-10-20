# Technical research quality: theorem-scoped evidence and mathematical reports

Status: **local opt-in Phase 2 and initial Phase 3 implementation; not production-enabled or quality-validated**. This plan extends the [search-wide/read-selectively design](search-wide-read-selectively-design.md) and [academic retrieval/canvas plan](academic-retrieval-and-research-canvas-plan.md). It applies to mathematical and other theorem-heavy questions across domains; the Markov-chain run below is a regression case, not a hard-coded topic strategy.

### Local implementation checkpoint (October 19, 2026)

- `TECHNICAL_RESULTS_ENABLED=false` by default. New explicit-mode jobs with this flag and bounded repair disabled pin the `research-v15-technical-results` family; old jobs keep their writer and review fingerprints. A repair-enabled job still uses the existing v14 path and publishes V4.
- The v15 writer can propose up to 2/4/6 typed technical records for Focused/Balanced/Deep, respectively, linked to a claim/citation index. This bounds additional structured output within each mode's existing writer token ceiling. The existing exact-span and semantic claim gate remains mandatory; the v15 reviewer additionally checks theorem scope. The deterministic field gate requires literal title, assumptions, notation, source expression and location in the cited passage, and assumptions in the supported claim. Rejected proposals and reasons persist in `ResearchAssessment.result.technical_results` but are not published.
- Report V5 projects admitted cards onto verified claim, citation and source IDs with the source artifact hash. `0029` only widens the immutable report-version constraint. The report Markdown preserves literal expressions; the web canvas shows responsive result cards, renders source-literal LaTeX with KaTeX's `trust: false`, and opens the linked source.
- This is **not** theorem proof checking or original-PDF equation verification. An exact match against extracted text may still inherit extraction errors, and the model can omit an essential qualifier from both its claim and proposal. No claim of higher technical accuracy is justified yet. Phase 0 frozen expert labels, Phase 1 math-aware extraction/primary-work yield, a stronger independent qualifier review, compatible-result comparison cells, and Phase 4 matched live evaluation remain open.
- Focused unit and web tests, an opt-in V5 publication/replay integration test, and migrations through `0029` passed on a named disposable local PostgreSQL database. The shared local database and hosted database were not migrated by this checkpoint.
- The four previously failing Python unit checks were reconciled locally: the entitlement projection expectation includes catalog-authorized modes; the live-evaluation cost guard uses the current Deep policy's 40,000-token ceiling while retaining an archived-policy check; and the synthetic modes-v1 baseline reads an immutable archived legacy policy rather than hashing mutable runtime `reports.py`. This does not turn synthetic receipts into a live quality evaluation.

### Typed measurement and comparison slice (October 20, 2026)

- Added an opt-in V6 report projection for source-linked measurements and comparisons. Each admitted row retains the exact value string, exact reviewed passage, citation/source/artifact identity, and nullable unit, population, period, method, definition, and source location. A supplied unit must be adjacent to the value in the cited passage. Same-metric rows receive an explicit “Comparable” or “Not established” status; missing or incompatible scope is never guessed or silently normalized.
- Measurement proposals pass through the existing supported-claim and exact-citation gate. Plot coordinates are derived only from a single source-stated numeric literal; ranges and other non-scalar values remain readable but are not plotted. A chart is emitted only for at least two distinct subjects with exact matches across metric, unit, population, period, method, and definition. Ordinary Markdown numeric tables no longer trigger automatic charts.
- V6 is behind `SOURCE_MEASUREMENTS_ENABLED=false` by default and uses new graph/report versions. Migration `0031` extends the report-version allowlist; it has not been applied to a database in this checkpoint. Focused unit, contract, web tests and a web production build pass locally; disposable-PostgreSQL migration/replay validation, browser validation, and matched live quality/cost evaluation remain pending. This slice does not establish that source measurements are scientifically correct beyond the existing claim review and exact-passage checks.
- This is not yet a general comparison ledger for arbitrary findings, nor a benchmarked improvement in research breadth or quality. The expert-labeled corpus, primary-source/math-aware extraction, independent qualifier/formula fidelity review, source-location verification, and Phase 4 matched evaluation remain open.

## Why the current report is insufficient

The supplied October 19 Balanced report on spectral gaps, cutoff, MCMC and Ising dynamics published 15 verified prose findings from 12 extracted sources; only seven sources were cited. Its answer before the source appendix is about 750 words and contains no display or inline math delimiters. Criterion review was unassessed and narrative composition was skipped for insufficient active time. The resulting document lists short claims by planned dimension but does not derive or compare the requested mathematical results.

The problem is deeper than rendering. The web report view already includes `remark-math`, KaTeX and overflow handling. The explicit-mode writer in `graph/builder.py` emits atomic `SectionedAssertion.claim` strings and citations. The evidence gate verifies exact passages and asks a general semantic reviewer if each passage supports its sentence. `mode_composer.py` then copies admitted sentences verbatim; it cannot insert an equation, definition, proof idea, or comparison that was never admitted as a finding. Adding unverified prose after this gate would break the product's evidence invariant.

Two concrete scientific risks in this run:

- The cited Cheeger inequality is stated for a reversible **discrete-time transition kernel** `P`. The user asked about a continuous-time generator `Q`. A valid report must define the normalization or uniformization connecting them; it cannot silently reuse constants across conventions. The [Markov-chain text](https://pages.uoregon.edu/dlevin/MARKOV/markovmixing.pdf) is a primary reference for these definitions.
- The [random-regular-graph Ising paper](https://arxiv.org/abs/1912.07798) separates annealed and quenched results and specifies inverse temperature, field and graph model. The published sentence says only “For Ising models on random regular graphs...” and therefore loses a theorem qualifier. A passage match plus a generic `supports` verdict did not detect this overgeneralization.

The two LMC URLs (a working-paper catalog record and its PDF) appear to describe one work, not two independent studies. The report cited a video abstract for the 2D Ising bound even though a [primary paper](https://arxiv.org/abs/1012.1271) exists. The [birth-and-death cutoff paper](https://arxiv.org/abs/0801.2625) states a sharper condition and window than the report conveyed. These examples motivate better retrieval and theorem-scoped verification; they do not authorize silently rewriting historical reports.

## User-facing outcome

For a technical question, the report should give a direct answer followed by evidence-linked result cards. Each result card should expose:

1. **Definition or theorem, with its source and location.** Name the result, paper, theorem/section/page when available, and distinguish a primary result from a survey's summary.
2. **Hypotheses and conventions.** State object class, regularity, reversibility, graph/measure/boundary conditions, continuous versus discrete time, parameter regime, normalization and metric. Show “not recorded” when source extraction cannot establish one.
3. **Exact mathematical statement.** Preserve source equation bytes/MathML/LaTeX and variable definitions where legally available. Show a display equation only after its notation, constants, quantifiers and assumptions have been checked against the source; an attractive rendering is not evidence.
4. **Interpretation and limits.** Say what the theorem proves, what it does not, and when comparisons are incommensurate. Distinguish a source's result from the report's inference.
5. **Open questions and comparison.** Compare results only on matched objects, metrics, assumptions and regimes. A table cell may say “not established”; missing head-to-head evidence is a finding about the search, not proof of equivalence.

Do not promise a formula, graph, diagram or proof for every question. A diagram may illustrate a verified relationship; an empirical graph requires underlying attributable data. Neither may invent a theorem, rate or measurement.

## Data and verification contract

Introduce a versioned technical-result proposal **alongside** the existing claim ledger. Do not put unchecked equations directly into `Report.markdown` or infer completeness from the number of citations. The proposal should contain a result kind (`definition`, `theorem`, `bound`, `algorithm`, `comparison`, `open_problem`), atomic conclusion, ordered assumptions, mathematical expression with source representation and notation, source/work identity, section/page or HTML anchor, exact cited spans, and confidence/status for each field. Keep the rendered LaTeX separate from the literal source expression and record any transformation. Preserve the original artifact and the extraction method/version.

Admission rules for a published technical result:

- Every factual sentence and equation links to one or more verified claim IDs and citation IDs. Existing exact-span and semantic checks remain mandatory.
- Check theorem **scope**, not just topic similarity: quantifier, object/target class, metric, parameter regime, boundary/initial conditions, time convention, and rate/constant must survive from source to published result. A missing essential qualifier yields `partially_supported` or `not_assessed`, never `supported`.
- Formula text needs a stronger gate than LaTeX compilation. Compare the source expression/MathML with the proposed expression and variable map. If extraction is lossy or equivalence cannot be established, show the cited source passage and an explicit “formula not independently checked” state; do not render a reconstructed formula as established. General symbolic equivalence is not a deterministic promise.
- Mathematical comparisons require compatible definitions. If source A reports Wasserstein error and source B total variation, label the metrics separately; do not rank rates without a justified conversion. Keep work-level deduplication distinct from publisher independence.
- Technical review output and failures must be persisted with the run's versioned request/receipt. An ambiguous paid attempt must not be silently redialed on replay. Old report versions and old in-flight checkpoints keep their original schemas and request fingerprints.

## Retrieval and extraction path

Use the existing dimension coverage plan to express the evidence needed: original theorem, definitions/conventions, comparison results and known counterexamples or open bounds. For scholarly dimensions, search original papers and authoritative texts in addition to web discovery. OpenAlex can discover searchable works and selected metadata, but [its API](https://help.openalex.org/api/) does **not** guarantee readable full text or theorem-level extraction. Keep its production flag off until the existing matched retrieval gate passes.

Within the current operation/source ceilings, rank a broader metadata candidate pool before extraction. Prefer unique primary works with accessible theorem-bearing text over repeated catalog pages and video descriptions when the question asks for formal results. Record excluded candidates and reasons; preserve source type as observed metadata, not a quality verdict. This changes a pinned shortlist policy, so use a new graph/request version rather than reinterpreting old receipts.

The extraction layer needs to preserve mathematical structure: section/theorem identifiers, displayed equation plus adjacent assumptions, PDF page or HTML anchor, and raw representation. PDF text alone can mangle `≤`, exponents, subscripts and Greek letters. Compare permitted HTML/math representations with PDF extraction on a frozen corpus before selecting a parser; never reconstruct missing symbols from a search snippet. Respect source access and publisher terms.

## Report and canvas

Compose the direct answer from admitted technical results and ordinary verified claims. Put definitions and notation before theorem applications; organize by research dimension rather than a fixed universal template. Present a compact result comparison table with columns such as setting, hypotheses, metric, bound/window, source and limitation **only when the cells have admitted evidence**. Preserve the existing report-to-source citation navigation and unknown-coverage warning.

KaTeX in `apps/web/app/(research)/research/[runId]/page.tsx` is a rendering layer. Test inline/display formulas, escaped Markdown, mobile overflow, copy/export, screen-reader text and hostile LaTeX with `trust: false`. A chart/diagram must be generated from admitted structured values/relationships; if no compatible values exist, show prose and a gap instead of a decorative plot. Keep publication possible when optional narrative or diagram generation times out.

## Implementation sequence and acceptance gates

| Phase | Work | Gate |
| --- | --- | --- |
| 0. Frozen failure corpus | Save this report's source/work identities and a privacy-reviewed, domain-general set of theorem-heavy questions. Human reviewers annotate essential hypotheses, equations, missing primary works, false equivalences and incommensurate metrics. | Baseline records theorem-scope error rate, equation fidelity, relevant unique works, answer usefulness, time and cost. Reviewers are blind to retrieval route. |
| 1. Retrieval/extraction | Version scholarly candidate screening; evaluate primary-work yield and equation/assumption preservation on accessible text. Keep current source caps. | More unique relevant full texts and intact theorem context at matched cost/latency; no replay fingerprint changes for old runs. |
| 2. Typed technical ledger | Add versioned proposals, explicit qualifier and formula review, persisted per-field outcomes, and a fail-closed projection into claim/citation IDs. | Deliberately missing `annealed`, `continuous-time`, metric, warm-start or boundary qualifiers are rejected in adversarial fixtures; incorrect equations never publish. |
| 3. Composition and UI | Add result cards, honest comparison, verified display equations, source-location navigation and responsive math layout. | Every factual sentence/table cell/formula has a verified source path; accessibility and export tests pass; optional composition failure still publishes the verified core. |
| 4. Matched live validation | Run the same questions through old and new pinned versions with bounded paid budgets and expert-blinded review. | Improve theorem-scope accuracy and answer usefulness without lowering citation precision or exceeding agreed cost/latency; publish no superiority claim before this gate. |

Likely code seams: `graph/builder.py` (planner/writer/reviewer and version routing), `grounding.py` (passage context), `providers/candidate_screening.py`, `ingestion.py`, source artifact/identity models, `report_document_v4.py` or a new report version, `mode_composer.py`, the report schema/contracts, and the report canvas. A new public report field or constraint requires contract generation and a migration; neither should be improvised against the hosted database. Tests need disposable PostgreSQL for replay/publication and browser coverage for math, tables and long documents.

## References and limits

- [Levin, Peres and Wilmer, *Markov Chains and Mixing Times*, second edition](https://pages.uoregon.edu/dlevin/MARKOV/markovmixing.pdf): primary textbook for definitions, spectral and conductance conventions.
- [Ding, Lubetzky and Peres, *Total-variation cutoff in birth-and-death chains*](https://arxiv.org/abs/0801.2625): primary cutoff criterion, location and window under its assumptions.
- [Dalalyan and Karagulyan, *User-friendly guarantees for the Langevin Monte Carlo with inaccurate gradient*](https://arxiv.org/abs/1710.00095): primary LMC guarantee with its metric and assumptions.
- [Brosse et al., *Sampling from a log-concave distribution with compact support with proximal Langevin Monte Carlo*](https://arxiv.org/abs/1705.08964): primary proximal result in a different target setting; not a head-to-head universal comparison.
- [Can, van der Hofstad and Kumagai, *Glauber dynamics for Ising models on random regular graphs*](https://arxiv.org/abs/1912.07798) and [Lubetzky et al., *Quasi-polynomial mixing of the 2D stochastic Ising model with plus boundary*](https://arxiv.org/abs/1012.1271): primary examples of graph, measure and boundary-condition qualifiers.
- [OpenAlex API reference](https://help.openalex.org/api/): academic-work discovery/metadata, not a full-text or theorem-verification service.

These references illustrate the required source fidelity. Their mathematical claims are not automatically imported into any user report by this document.
