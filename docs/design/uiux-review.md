# HogsKin frontend review and UX proposal

Reviewed 12 October 2026. Deliverable: frontend analysis and an editable design proposal, not application implementation.

[Open the Figma file](https://www.figma.com/design/FnyINIXHxlyo5gvocZ9Q20)

## Design screens

| Screen | Figma | Export |
| --- | --- | --- |
| Landing | [Desktop](https://www.figma.com/design/FnyINIXHxlyo5gvocZ9Q20?node-id=2-20) | [Preview](landing.png) |
| New research | [Desktop](https://www.figma.com/design/FnyINIXHxlyo5gvocZ9Q20?node-id=2-21) | [Preview](new-research.png) |
| Research report | [Desktop](https://www.figma.com/design/FnyINIXHxlyo5gvocZ9Q20?node-id=2-22) | [Preview](report-desktop.png) |
| Research report | [Mobile](https://www.figma.com/design/FnyINIXHxlyo5gvocZ9Q20?node-id=2-23) | [Preview](report-mobile.png) |

All screen text is editable. Examples and source excerpts in these concepts are illustrative, not actual retrieved evidence. The file contains scoped color variables, Geist text styles, auto-layout containers, and a reusable primary action component. These are static design concepts; navigation, scrolling, citation selection, and motion below are implementation specifications, not wired Figma interactions.

## Findings from the current code

| Before | After | Why |
| --- | --- | --- |
| Composer uses `.research-rail`; report uses a separate `.run-sidebar`, each with different navigation and history presentation. | One shared workspace shell with the same history, new research action, active run, and mobile drawer. | Moving between creation and reading should preserve orientation. |
| Sources and research plan live below the report in `.run-detail-grid`. | A persistent Sources / Methodology panel beside the report. | Use the spare width for evidence while preserving a readable answer column. |
| Every numeric citation in `InlineText` points to `#sources`. | Select the exact source, reveal its details, and highlight its supporting passage where available. | A citation should lead to evidence for that claim, not the beginning of a list. |
| `AnswerMarkdown` recognizes headings, simple unordered lists, bold text, and numeric citations only. | A safe Markdown renderer with tables, ordered lists, links, code, quotations, and robust heading structure. | Comparative research often needs tables; unsupported syntax creates clutter. |
| The composer mixes the question, protocol explanation, evidence ledger, and workflow explanation in competing panels. | Question first; scope alongside it; examples and recent work underneath. | Reduce the effort required to start a run. |
| UI copy includes “Foundation online”, storage readiness, “durable research run”, and backend details on the landing preview. | Explain research actions and actual progress in ordinary language. | Infrastructure details do not help most readers make a research decision. |
| Font stacks depend on locally available Aptos, Segoe UI, Iowan, and Georgia. | A deliberate Geist family with defined sizes and weights. | Predictable rendering and clearer hierarchy across devices. |
| `styles.css` repeatedly redefines `.run-desk`, `.run-canvas`, headings, and responsive rules. | Semantic tokens and scoped styles owned by the workspace, report, and marketing components. | Makes responsive behavior easier to reason about and change. |
| Existing independent desktop scrolling is defined late in CSS. | Make scroll ownership part of the shared shell contract. | Preserve the existing fix and prevent later layout changes from undoing it. |

The current app already includes useful foundations: keyboard focus styles, skip links, labeled controls, live status text, real history requests, disabled submission during requests, source counts, and reduced-motion handling. Preserve those behaviors.

## Visual direction

Use a white report surface and a quiet silver navigation/evidence surround. Indigo marks actions and selection; green marks completed research. Evidence and supporting passages provide the visual identity. Avoid decorative imagery, invented testimonials, fake partner logos, and moving text around a document being read.

| Token | Value | Purpose |
| --- | --- | --- |
| Canvas | `#F5F6FA` | History and evidence background |
| Surface | `#FFFFFF` | Report and input surfaces |
| Ink | `#202538` | Primary text |
| Muted | `#626B80` | Supporting text |
| Accent | `#4549B8` | Actions, links, selected source |
| Success | `#287A64` | Completed state |
| Selection | `#EBECFA` | Summary and selected history item |
| Separator | `#E2E5EF` | Structural separation when needed |

Geist Regular carries report text; Medium carries controls; SemiBold carries headings. Desktop body text: 16px with 26px line height. Report title: 32px with 44px line height. Workspace title: 36px. Landing display: 64px, reducing responsively. Keep report lines near 65–75 characters. Use 4/8/12/16/24/32/48px spacing; larger 80–128px spacing belongs to marketing sections, not research controls.

The selected skills disagree on motion density, uppercase labels, and decorative layouts. The resolution follows the product brief: restrained workspace interaction from Emil and frontend-design; stronger typography and surface hierarchy from high-end-visual-design; wide headline exploration from gpt-taste. The Figma motion skill requires an actual animated Figma node to implement authored motion; none was supplied. Do not claim the proposed timings were extracted from Figma.

## Layout and scrolling contract

At 1440px, the desktop report layout uses 232px history, 808px report, and 400px evidence. These columns fill the available width. The report uses internal padding rather than stretching prose across the entire column.

```text
History                 Fixed workspace toolbar
                        Report                    Sources / Methodology
Recent runs             Summary                   Selected source
                        Findings                  Supporting passage
                        Limitations               Other sources
```

Above 1200px: viewport-height shell using `100dvh`, `overflow: hidden`, and `min-height: 0` on shrinking grid/flex ancestors. History, report, and evidence each own `overflow-y: auto`. Header and panel tabs remain outside their scrolling bodies. Use `overscroll-behavior: contain` and stable scrollbar gutters. Preserve each pane's scroll position when switching the evidence tab or selecting a citation. Do not automatically scroll the report when new events arrive.

Between 768px and 1199px: collapse history into an accessible drawer; show evidence in a toggled side panel only when there is sufficient reading width, otherwise use a sheet. Below 768px: normal document scrolling for the report, with compact Report / Sources / Methodology navigation. Sources open in a sheet with its own scrollable body. Closing a sheet restores the triggering citation's focus and the report position. The mobile export depicts citation-detail content, not a fully implemented overlay.

## Interaction specifications

### Starting research

An example fills the textarea and places focus there; it never submits automatically. Focused, Balanced, and Deep remain native radio choices with the existing 6/12/20 search limits. Preserve the current fast-explainer behavior and explain its two-source-check limit in context. Do not imply that “Deep” adds browser sessions or a different time budget unless backend capabilities support those promises.

During submission, show “Starting research…” and disable only the action that would duplicate the request. On failure, preserve the question and scope, present the returned error with an actionable retry, and allow another attempt. Distinguish history loading, empty history, and failed history fetch; a count of zero while loading must not look like confirmed empty history. “Saved” in a final toolbar must reflect actual persistence; omit it from an unsaved draft.

### Reading a report

Present the research question once, followed by completion state, evidence count, summary, findings, and limitations when these exist in the output. Do not manufacture a recommendation or summary from arbitrary report headings. Comparisons use accessible tables with contained horizontal overflow on narrow screens. Retain Markdown escaping and avoid arbitrary raw HTML execution.

Selecting `[n]` resolves the citation through the report's citation mapping, rather than assuming its number equals an index into all collected sources. If a source cannot be resolved, show “Source details unavailable” and keep the report usable. A selected source can show title, domain, URL, source type when known, collection time when known, preserved excerpt when available, and related claim. Distinguish “collected” from “supports this claim”; source presence alone is not verification.

Methodology contains planned subquestions, stage outcomes, search queries actually recorded, and a disclosure for the activity trail. If the backend exposes only event labels, display those labels rather than inventing missing queries. Cancellation, failure, and incomplete research remain visible states rather than turning into a “Complete” badge.

### Motion and accessibility

| Interaction | Proposed behavior |
| --- | --- |
| Pointer press on primary action | Scale to 0.98 over 120ms, custom ease-out |
| Citation selection | Immediate selection; optional 140ms highlight color transition |
| Evidence tab switch | Immediate content replacement; optional 120ms opacity transition |
| History drawer / source sheet | 220ms transform + opacity, `cubic-bezier(0.32, 0.72, 0, 1)` |
| Loading | Static skeleton with concise status; avoid endless decorative orbiting |
| Marketing preview | Optional one-time reveal; never delay access to the action |

Keyboard actions remain immediate. Gate hover effects with `(hover: hover) and (pointer: fine)`. Reduced motion removes spatial movement. Drawers and sheets require dialog semantics, focus containment, Escape dismissal, a visible close action, background inertness, and focus restoration. Touch targets are at least 44px. Source selection must have a visible non-color cue. Do not announce the entire report on every streamed event; announce meaningful stage changes briefly.

## Implementation sequence

1. Extract shared navigation/history into a workspace shell used by both research routes. Preserve existing fetch and run actions. Make desktop scroll ownership structural.
2. Add report/evidence split with source selection state and Sources / Methodology tabs. Validate the citation mapping against actual API output before wiring number-to-source resolution.
3. Replace the limited Markdown parser with a safe renderer supporting the formats the backend actually emits. Add table overflow and long-link handling.
4. Simplify the composer around question, scope, examples, and real recent work. Remove unsupported capability and infrastructure copy.
5. Consolidate CSS into tokens and scoped component styles; load the chosen font deliberately. Implement reduced-motion-aware drawer/sheet interactions.
6. Align the landing page with the same visual system and a truthful product preview.

Primary code locations:

- `apps/web/app/page.tsx`: landing structure and copy.
- `apps/web/app/(research)/research/page.tsx`: composer, scope, examples, history.
- `apps/web/app/(research)/research/[runId]/page.tsx`: report parser, citation interaction, evidence, methodology, progress.
- `apps/web/app/styles.css`: shared shell, typography, pane sizing, responsive behavior, motion.
- `apps/web/app/layout.tsx`: font loading and common document structure.

## Acceptance checks for implementation

- At 1440px and 1920px, scrolling a long report leaves history and evidence at their own positions and does not scroll the document.
- At 390px and 768px, no page-wide horizontal overflow; only a genuinely wide table may scroll sideways.
- A citation opens the correct source, preserves report position, and restores focus when its detail view closes.
- Unknown source metadata, long questions, long domains, failed runs, empty sources, and history failures remain legible and actionable.
- Question submission, history navigation, cancellation, streaming updates, and existing idempotency behavior continue to work.
- Reduced motion and keyboard navigation are checked in the running implementation.

## Verification of this design deliverable

Inspected current source files and confirmed the local homepage responds. Composed four Figma screens, exported and visually reviewed them, corrected clipped horizontal auto-layout containers and multiline text, and checked that report layers are editable and use Geist. This review does not constitute browser verification of a redesigned app: application code was not changed in this task, and the Figma screens are static concepts.
