# Evidence desk design specification

## Direction

A research workbench, not an operations dashboard. The primary relationship is
question → report claim → preserved evidence. No stock images, simulated telemetry,
unmeasured confidence percentages, billing quotas, or decorative agent counts.

Tokens shared with the landing page: canvas #F7F8FA, surface #FFFFFF,
ink #181C20, muted #66717A, copper #A96142, border #DCE2E6.
Copper hover #8E4E33 and selected wash #F7EEE9. Outfit remains locally hosted. Titles 30–36px,
report body 16px/1.75, controls 13–14px. Corners 8px controls / 14px composer.
Semantic workspace tokens inherit the public site's brand accents; account and
public layouts remain unchanged. Success/error retain their semantic colors.

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
- Completed: Markdown brief, section navigation, reading time, copy/download.
- Old report without checks: explicit missing-data state, never inferred validation.
- Claim checks: display stored exact-span and semantic verdict separately; do not
  describe an entire source or report as factually verified.

## Motion

CSS for press/hover; existing GSAP for occasional panel entrances. The tab marker
uses interruptible WAAPI transform animation (180ms), avoiding a JavaScript
per-frame navigation tween. Keyboard actions
and reduced-motion preferences bypass movement. No repeated entrance animations
on SSE updates. 140ms press feedback, 180ms selection, 220ms sheet entry.
The landing illustration has one finite 1800ms copper trace, not a continuously
moving backdrop behind reading content. Reduced motion omits it entirely.

Report header, metrics, progress and brief share one 760px maximum-width column
and auto inline margins. A prior metrics margin shorthand and font-dependent
`ch` measurements made them appear detached; shared sizing fixes this structurally.

Motion research: [web.dev performance guide](https://web.dev/articles/animations-guide),
[GSAP responsive motion](https://gsap.com/docs/v3/GSAP/gsap.matchMedia()/),
[Motion reduced motion](https://motion.dev/docs/react-use-reduced-motion), and
[Aceternity background beams](https://ui.aceternity.com/components/background-beams-with-collision).
Beam effects are inspiration for the landing trace, not a dependency or an ongoing
effect in the report. No extra animation library is required.

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
