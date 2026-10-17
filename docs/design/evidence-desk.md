# Evidence desk design specification

## Direction

A research workbench, not an operations dashboard. The primary relationship is
question → report claim → preserved evidence. No stock images, simulated telemetry,
unmeasured confidence percentages, billing quotas, or decorative agent counts.

Tokens shared with the landing page: warm paper canvas #FFFCFA, surface #FFFFFF,
ink #252522, muted #756F67, copper #A96142, border #E4E1DD. Every neutral is a
warm grey; former cool greys were remapped at equal luminance so contrast is unchanged.
Copper hover #8E4E33 and selected wash #F7EEE9. Outfit remains locally hosted. Titles 30–36px,
report body 16px/1.75, controls 13–14px. Corners 8px controls / 14px composer.
Primary actions (New research, Start research, auth submit) are ink #252522 pills;
copper is reserved for citation marks. The workspace shell is sand #F7F2ED with the
work column as a raised paper sheet (20px radius, 8px inset; flush below 1000px).
Selected depth and active navigation use an ink ring and a white raised pill.
Success/error retain their semantic colors.

## Desktop

```text
History 240px | Toolbar 56px
              Composer + depth choices       | Scope summary
              Templates                      | Evidence rules
              ----------------------------------------------
              Report / actual run progress   | Sources / Checks / Method
              Own scroll container           | Own scroll container
```

The history list scrolls without moving its account footer. The report stays
readable at 70–80 characters per line. Evidence is 340px on wide displays.
Collapsing history must not discard filters. No horizontal page overflow.
Workspace links (Reports, Library, Compare, Automation) sit in one labelled
`nav`, each with a distinct icon; Research preferences is anchored above the
account footer rather than duplicated in the toolbar. Toolbar actions never
wrap: below 640px Compare and PDF become labelled icon buttons, "Save to
library" shortens to "Save", and the toolbar title is hidden.

## Mobile

```text
History trigger | Title | Evidence / Report switch
Composer OR report (one independent scroll surface)
Sources / Checks / Method (shown when Evidence is selected)
History opens a focus-trapped, labelled side sheet.
```

## States

- Opening: structural skeleton, labelled loading status; no invented results.
- Empty history/library: actionable invitation to start a question.
- Empty search: clear filter; retain loaded records.
- Submission: disable duplicate submission; preserve question and depth on error.
- Queued/planning: actual stage and elapsed time; no estimated countdown.
- Collecting: actual sub-question states and incoming preserved sources.
- Checking/writing: explain the gate; sources remain inspectable.
- Stopping: retain progress and evidence, label request separately from stopped.
- Failed: recorded error, retry action, retained collected evidence.
- Progress rail: reflection counts as Research (it loops back into collection).
  Queued, failed and cancelled runs mark no phase as done or current, because
  the stopping point is not recorded; the last step reads Failed/Stopped.
- Completed: Markdown brief, section navigation, reading time, copy/download.
- Old report without checks: explicit missing-data state, never inferred validation.
- Claim checks: display stored exact-span and semantic verdict separately; do not
  describe an entire source or report as factually verified.

## Motion

CSS for press/hover; existing GSAP for occasional panel entrances. The tab marker
uses interruptible WAAPI transform animation (180ms), avoiding a JavaScript
per-frame navigation tween. Keyboard actions
and reduced-motion preferences bypass movement; opacity and colour transitions
remain so state changes stay perceptible. No repeated entrance animations
on SSE updates. 140ms press feedback (scale 0.97), 180ms selection, 220ms sheet
entry. Hover effects are gated behind `(hover: hover) and (pointer: fine)`.
Report header, metrics, progress and brief share one 760px maximum-width column
and auto inline margins. A prior metrics margin shorthand and font-dependent
`ch` measurements made them appear detached; shared sizing fixes this structurally.

Motion research: [web.dev performance guide](https://web.dev/articles/animations-guide),
[GSAP responsive motion](https://gsap.com/docs/v3/GSAP/gsap.matchMedia()/),
[Motion reduced motion](https://motion.dev/docs/react-use-reduced-motion), and
[Aceternity background beams](https://ui.aceternity.com/components/background-beams-with-collision).
Beam effects informed the landing field. They are not a dependency, and nothing moves continuously behind
report reading content. No extra animation library is required.

## Brand

- The mark is a "cited H" (`BrandMark` in `components/ui.tsx`). The tall left stem stands for the source, the shorter right stem for the claim, and the crossbar for the link between them. A copper footnote dot at the top right makes it read as H¹.
- The strokes use `currentColor`, so the mark follows its surface: ink on paper, paper in the dark sidebar. The dot is always copper.
- The wordmark is "HogsKin" followed by a copper period.
- On hover, the crossbar re-draws itself (stroke-dashoffset, `pathLength=1`) and then the dot pops in. Both are disabled under reduced motion.
- `app/icon.svg` is the favicon: a paper H and a copper dot on an ink rounded square.

## Landing page

Paper #FFFCFA, sand #F7F2ED panels with #EFE6DC hairlines, ink #252522 pill
buttons. Copper appears only on citation marks and the live status dot.
Hero choreography (CSS entrances; the field and console are small client components):

1. A canvas field of dots, squares and diamonds irises open (mask-size, 2.6s).
   It is quiet behind the headline. A slow diagonal band brightens it, and a few
   marks briefly turn copper. It runs at 30fps and pauses offscreen or in a hidden tab.
2. Headline characters bloom from the centre outwards (blur 8px to 0, 700ms).
3. Lead, buttons, then the console rise in (620/720/860ms).
4. The console replays one Balanced run through the real graph on a 25s loop
   derived from elapsed time. The rail lists the persisted node ids (`intake`,
   `planner`, `approval_gate`, `research_worker`, `reflector`, `verifier`,
   `synthesizer`) with run-clock durations. Scenes share one grid cell so the
   panel never changes height:
   - compose: depth budgets (6/12/20 searches) and plan review switched on;
   - plan: intake scope note, three sub-questions, then the approval gate with
     the run clock paused until "Approve plan" is pressed;
   - collect: one lane per sub-question with its query, progress and source
     count, a 12-search budget counter, then reflector coverage 3/3;
   - verify: four claim drafts get exact-span and semantic-review chips; one
     "Partial" draft is excluded and counted;
   - report: the cited answer streams, key figures appear (values verbatim from
     the quotes), the published share formula, and a quote card for citation 2.
   Citations and trailing punctuation are glued to their word so they never wrap
   alone. Narrow screens show marks for every node and a label for the current one.

Below the hero:

- The statement scrubs word opacity with scroll.
- Section headings rise line by line out of masks (GSAP SplitText, `autoSplit`
  re-splits after font load or resize; reduced motion leaves them unsplit).
- Gallery tiles and method steps reveal with blur and rise once.
- Method steps describe the real nodes (four stages, node ids as mono chips).
  Cards stay opaque while stacking; only their contents dim. A copper trace with
  a marker draws down the steps on wide screens.
- Step trails light in order.
- The "Watch the plan take shape" tile loops (950ms steps): the planner writes
  three tasks in, each runs in turn with a spinning mark, the read-source count
  rises, and coverage reaches 3 / 3. It pauses offscreen; reduced motion shows
  one done, one running and one queued.
- The console stays flat; it only scales from 0.93 to 1 as the hero scrolls.
- FAQ answers open with grid-template-rows (380ms).
- A sand band (`.lp-band`) sits between the method steps and the FAQ. It has a
  masked 56px ruled grid and a copper/sage glow that drifts with scroll. It
  holds two sections, both linked from the nav as "Evidence":
  - `#verify` "How we verify": three rules, each with a live vignette
    (`landing/verify-vignettes.tsx`) that uses the hero run's sources.
    - Rule 1: a claim's exact span is matched in the retrieved text.
    - Rule 2: five candidate claims get the real verdicts (supports,
      partially_supports, unrelated). Three publish; two are struck out.
    - Rule 3: pressing citation 2 opens its source card with the passage
      marked.
  - `#evidence` "Beside every answer": the evidence tour
    (`landing/evidence-tour.tsx`). ARIA vertical tabs (Sources, Methodology,
    Checks) support arrow keys, Home and End. They auto-advance on a 7s
    progress bar only while visible and not hovered or focused.
- Vignettes and the plan tile share `use-loop-step.ts`. Loops pause offscreen
  and in hidden tabs, and hold a still frame under reduced motion.
- Lenis smooth scroll (lerp 0.11) is driven by the GSAP ticker and updates
  ScrollTrigger. Anchor links offset by 88px for the fixed nav; nested
  scrollers keep native scrolling. Lenis is destroyed on unmount and skipped
  under reduced motion.
- A fixed, pointer-events-none SVG grain (`.lp::after`, 6% multiply) adds paper
  texture without repainting scrolling content.

Easing is cubic-bezier(0.22, 1, 0.36, 1) for movement, with a slight overshoot
(0.22, 1.2, 0.36, 1) for chips and checks. Reduced motion renders the finished
console, a static field, and every section fully visible.

## Crew characters

Four original SVG characters (`components/crew/critter.tsx`, `crew.css`): folio
(ochre page), lens (sage magnifier), seal (slate check) and quill (rose nib). They
blink, breathe and glance; on fine pointers without reduced motion, `CrewEyes`
makes every `[data-critter]` follow the cursor with one rAF lerp. Placement: perched
on the hero console, the auth specimen card and the composer; peeking beside the
FAQ; and in every `Empty` state. The quill scribbles while a run is starting or live;
the seal cheers when the hero run completes. All are decorative (`aria-hidden`).

## Pricing and accounts

`/pricing` lists Individual plans only (Free, Scholar, Investigator) with a
monthly/yearly toggle, comparison table and FAQ. Figures and limits are placeholders
with no billing backend; plan CTAs link to `/signup?plan=<id>`, which ignores the
parameter. Login, signup and password pages use an inset sand story panel with the
evidence field, a cited specimen answer with the crew, and a paper form with ringed
inputs and a staggered rise (`auth.css`). Workspace styling lives in
`workspace-skin.css`.

## Orchestration panel

"Inspect live orchestration" (`components/research-insights.tsx`,
`orchestration.css`) shows persisted task attempts only. It never infers progress.

- Summary row: a live dot (pulses while a task runs), the recorded, running and
  failed counts, and a progress rail of finished over total.
- Graph: three numbered lanes:
  - Plan: `intake`, `planner`, `approval_gate`, `planner_delta`.
  - Collect in parallel: `research_worker`, `research_task`.
  - Assess and publish: everything else.
- Lane state comes from its tasks: idle, active, done, or failed. Any failed
  task fails the lane.
- A lane connector flows only after its lane is active or done.
- An empty lane says what it is waiting for. It shows no placeholder tasks.
- The dashed loop-back from assessment to the planner is shown at 620px
  container width and up. It turns ink and animates once a `planner_delta` task
  has run, and states how many times coverage repair ran.
- Nodes show a status glyph (spinner while running), elapsed time, attempt
  number when greater than one, and source count.
- Selecting a node opens task details: started and finished times, dependency
  chips that select the upstream task, sources, and the recorded error with the
  run-level retry note.
- Task list is the accessible alternative and the default at 760px and below.
- Reduced motion stops the spinner, the pulse, and the connector and loop flow.

The fixture `?view=run&tasks=staged` exercises the panel. It has all three
lanes, a failed collector, a repair loop, and a retried running verifier
(`orchestration-check.js`).

## Run clock and plan approval

The run clock shows active time, not wall time. The API's `approval.waitedMs`
sums closed plan-review waits. Each wait runs from an `approval.requested` event
to the next decision, or to cancellation. `approval.waitStartedAt` marks a wait
that is still open. While that wait is open, the clock stops ticking and reads
"paused for approval". Approving or rejecting closes the wait in the UI
immediately, and the clock resumes without counting the wait. A repair plan
opens its own wait. The fixture `?view=run&state=awaiting_approval` covers this.

## Share and export

One toolbar trigger, "Share", opens a native `popover` panel
(`components/report-actions.tsx`, `report-actions.css`). It sits in the top
layer, so the toolbar's horizontal scrolling never clips it. It is anchored
under the trigger on desktop and becomes a bottom sheet at 640px and below.
Escape and outside clicks close it, and focus returns to the trigger. Busy
controls park focus on the panel so focus is never dropped.

- Private link: an ink "Create link" pill. The created link stays visible in a
  read-only field with a Copy button that confirms with "Copied" for 2s. If
  clipboard access is denied, the field is selected for manual copying.
- Active links: each shows its relative and absolute expiry and a Revoke
  action. Revoked or expired links collapse to a one-line count. The trigger
  badge counts active links.
- Export: Markdown and BibTeX tiles with a spinner while preparing and a check
  when done. After a download, a receipt shows version, size, and a shortened
  SHA-256. The download route rejects artifacts whose size or hash does not
  match, so a finished download has been verified.
- One `role="status"` line reports results. Successes are green; errors use the
  danger tint.
- The component is keyed by report id, so switching report versions never shows
  another version's link.

The fixture mocks shares, revocation and exports; BibTeX export fails on purpose
(`share-check.js`).

## Answer layout

Once a report exists, the brief leads with the answer
(`components/research-answer.tsx`, `research-answer.css`).

- The question renders as a sand bubble. Answer quality is a slim strip whose
  dot and tint follow `data-quality` (partial is amber, insufficient evidence
  uses the danger tint, unassessed stays sand).
- Run metrics, the stage rail and orchestration join into one bordered strip.
  It stays full width so the brief column remains aligned.
- Each `##` section is wrapped in `section.answer-section[data-kind]`. The first
  (executive summary or direct answer) is `lead`, a sand panel with larger
  type. `limitations` is a sand caveat callout and `method` is muted.
- Citation chips open one shared hover card (`#citation-preview`, portaled to
  the body). It shows the publisher, title, kind and date, then the quoted
  passage, stating whether the exact span was matched. It opens after 220ms,
  swaps instantly between chips, follows keyboard focus, closes on Escape,
  scroll or click, and ignores touch.
- Tables get a label bar with Copy (tab-separated, citations as `[n]`).
- References are built from the `## Sources` list in APA, MLA, Chicago,
  Harvard or IEEE. The choice persists (`hogskin.citationStyle`). No author
  metadata is collected, so the publisher stands in as author, and the list
  says so. Numbers open the source; each entry and the whole list copy.
- Follow-up chips come from open gaps' suggested queries, then unresolved
  coverage questions. Choosing one fills and focuses the follow-up field; it
  never launches a run by itself.
- The Methodology tab opens with "Searches the agents ran": provider calls,
  providers and kept sources, per-provider counts, then numbered questions
  that expand to the sources each one found.

The rich fixture is `?view=run&answer=rich` (`answer-check.js`).

## Research workspace

The brief and its evidence share one resizable split
(`components/research-workspace.tsx`, `research-workspace.css`,
`lib/report-table.ts`). `workspace-check.js` covers it.

- A vertical `role="separator"` sits on the panel edge. Drag it, or use the
  arrow keys (24px, Shift 80px), Home or End; Enter or double-click resets.
  Width lives in `--evidence-width` on `.report-grid`. Dragging writes the
  variable directly and measures only on release, so a long report never
  re-renders per frame. CSS clamps the column to 300px–65%, JavaScript also
  keeps 380px for the report, and the value persists in
  `hogskin.evidenceWidth`. At 1100px and below the split and handle are off;
  the existing report/evidence toggle applies.
- The panel header has three presets: Read (340px), Split (half) and Evidence
  (62%), plus a hide button that reuses the toolbar's evidence visibility.
- The reading column grows with its container
  (`clamp(760px, 88cqi, 920px)`). Header, signal, progress and article use the
  same rule, so they stay aligned.
- Once the panel is at least 560px wide, the source list becomes a comparison
  table:
  - Columns: citation number; source (title, site, publisher, date); the
    relevant extract quoted by published claims, with its match status; and an
    assessment (class, cited or collected, repeated material).
  - Sort by citation order, title or newest. Show 10, 25 or all.
  - Extract and assessment columns can be hidden (`hogskin.sourceTable`).
  - Choosing a title opens the selected source as before.
  - Cells stay `display: table-cell`. The assessment pills sit in an inner
    `.source-table-assess` flex column, so every cell in a row shares its
    borders. `workspace-check.js` asserts that every cell in a row has the
    same top and bottom edges.
- The rendered report Markdown is memoised on its text. Polling and layout
  measurement therefore never remount citation chips, which keeps focus
  return reliable.

## Rich report content

- Math: `remark-math` with `rehype-katex`. Use `$$…$$` for inline and display
  math. Single dollars stay text, so currency is never parsed as math. KaTeX
  runs untrusted, with `throwOnError: false`, and expansion and size limits.
  `katex` is pinned to the version `rehype-katex` renders with, so the CSS
  class names match.
- Tables: the label bar adds a Table/Chart switch (only for chartable tables),
  Copy (TSV), CSV download (with a BOM; formula-leading cells are prefixed with
  `'`) and an expanded modal `<dialog>` that shows the table and its chart. The
  header stays sticky in a bounded scroll region.
- Charts: a table can be charted when it has text labels, 2–24 rows, and a
  column in which every cell is a number with one consistent unit. Citation
  markers are ignored. Bars are horizontal, start at zero, scale only by
  transform, and show the formatted value. The metric is chosen with a select
  when several columns qualify. Reduced motion removes the bar and row
  animations.
- The backend writer generates these from verified findings (next section).
  Its output is rendered in the fixture by `?view=run&answer=backend`
  (`report-content-check.js`).

## Generated report content

`render_report` (`services/research-api/src/research_api/reports.py`) adds
structure after the analysis sections and before Limitations. Everything is
built from published findings only, never from rejected drafts.

- Key figures, all modes:
  - The writer may attach up to four figures to a claim: subject, metric, the
    value as written, and the index of the citation it comes from.
  - `verified_figures` keeps a figure only when:
    - the claim passed the full evidence gate;
    - the value appears verbatim, as a whole token, in that verified quote. A
      bare number may not drop a following `%`;
    - the same number appears in the claim;
    - the subject and metric appear in the claim or the quote.
  - Values are never converted, rounded or combined.
  - Figures are grouped into one table per metric, so a chart never mixes
    measures. A table needs at least 2 rows and holds at most 24.
  - Tables per report: Focused 2, Balanced 4, Deep 6.
- Evidence by source (Balanced and Deep, with at least two cited sources):
  findings per source, findings shared with another source, and the sections
  each source supports. It describes overlap, not publisher independence.
- Evidence coverage (Deep): findings and distinct cited sources per section.
- Publication share (Balanced and Deep): a display formula of published over
  candidate findings in Methodology.
- Model-written cell text is escaped (`|`, `[`, `$` and other Markdown
  syntax), so labels cannot create citations, links or math.
- Drafts recorded before `figures` existed still parse, but the strict writer
  schema requires the field.

## Library and data

Use existing durable completed runs as the report library. Search and status
filters organize existing data, not new fake folders. Quote/check projection is
tenant- and run-scoped; expose only named public fields, never artifact paths,
provider credentials, or internal provenance. No migration is needed.

## Acceptance

Test 390px / 768px / 1440px layouts, long questions, tables, empty/failed runs,
keyboard selection, sheet Escape/focus return, reduced motion, independent scroll,
quote rendering, source/claim joins, authentication and cross-tenant boundaries.
Measure input-to-visible update in a browser fixture without claiming provider
latency improvements. Never weaken authentication for screenshot testing.

## Delivered validation

The isolated fixture imports the actual composer, report, library, and workspace
components, replacing only Next navigation and API responses. It is outside the
App Router and is never an authentication bypass. 29 browser assertions cover
three depth budgets, the fast-explainer exception, submission failures, keyboard
focus return, quote checks, responsive panels, independent scrolling, reduced
motion, failed/working/empty runs, report filtering, shared report-column
alignment and the landing-page button color. Desktop and mobile
screenshots were visually reviewed using the existing locally hosted Outfit font.

The report filter updated in 55ms in one local fixture measurement (32 records,
390px Chromium viewport). This is a development observation including automation
overhead, not an SLA or measurement of network/provider latency. The real
`/research/reports` route was separately checked to require login.

Backend tests cover safe quote/check projection, absent/malformed verification,
explicit tenant/run predicates in the evidence join, and owner-scoped bounded
report listing. Existing source ceilings and claim verification remain unchanged.

### Reproduce the browser fixture

Use `mktemp -d` for an output directory. From the repository root, bundle
`apps/web/tests/browser-fixture/main.tsx` with esbuild (`--bundle --jsx=automatic`),
aliasing both `next/link` and `next/navigation` to the absolute path of
`apps/web/tests/browser-fixture/navigation.tsx`. Mark `/images/*` external and
set `process.env.NODE_ENV` to `"development"`. Copy the fixture index.html and
the two existing Outfit font files into the output directory. Serve that
directory on `127.0.0.1:3101` and run:

```sh
npx @playwright/cli -s=evidence-desk open http://127.0.0.1:3101
npx @playwright/cli -s=evidence-desk run-code --filename=apps/web/tests/browser-fixture/check.js
npx @playwright/cli -s=evidence-desk close
```

Live signed-in provider completion and physical-device testing remain manual
checks. No hosted database migration or provider request is required for this
redesign's fixture tests.
