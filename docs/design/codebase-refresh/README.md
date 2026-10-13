# Codebase UI refresh

This implementation uses a new graphite, cool-white, and copper visual direction, developed directly in the app. The earlier Figma proposal is not the source for these screens.

## Pages

| Route | What changed | Desktop preview | Mobile preview |
| --- | --- | --- | --- |
| `/` | Centered introduction, generated research-instrument artwork, asymmetric capabilities, explanatory accordions, final research action | [Home](home-desktop.png) | [Home](home-mobile.png) |
| `/login` | Account form, show-password control, explicit local-preview state, workspace entry | [Login](login-desktop.png) | [Login](login-mobile.png) |
| `/signup` | Name, email, password, native validation, honest account status | [Signup](signup-desktop.png) | [Signup](signup-mobile.png) |
| `/research` | Focused question composer, 6/12/20-search scope controls, actionable examples, shared searchable history | [Research](research-desktop.png) | [Research](research-mobile.png) |
| `/research/[runId]` | Independent report/evidence panes, source selection, methodology, safe Markdown tables, copy and download | [Report](report-desktop.png) | [Report](report-mobile.png) |
| Unknown routes / render failures | Designed recovery pages with working navigation or retry | Browser verified for 404 | Responsive |

The initial screenshots captured UI-only account previews. Those previews have now been replaced with Supabase email/password authentication, Google OAuth, confirmation and password recovery. Research pages require an authenticated private workspace. See [authentication.md](../../authentication.md) for current configuration, migrations and verification; the historical anonymous design-check scripts below are not the current Auth smoke test.

## Skills applied

- **frontend-design:** a subject-specific precision-instrument identity, consistent typography, direct copy, and a four-section marketing narrative.
- **high-end-visual-design:** concentric input/card enclosures, restrained surface depth, rounded primary actions with nested icon controls, responsive layouts.
- **emil-design-eng:** short custom-eased interaction feedback, focus restoration, reduced motion, touch-safe hover rules, and quiet repeated workspace interactions.
- **gpt-taste:** centered headline exploration, a filled asymmetric capability grid, GSAP text interpolation and explanatory pinning confined to the homepage. Decorative partner marquees and invented testimonials were rejected because the product has no supporting content for them.
- **imagegen-frontend-web:** eight separately generated horizontal references, plus one text-free artwork asset used in the actual website. Built-in image generation was used throughout.

## Before / after review

| Before | After | Why |
| --- | --- | --- |
| Separate creation/report navigation | Shared workspace shell | Preserve orientation between pages |
| Report sources below the answer | Sources and methodology alongside the report | Use the available width without stretching prose |
| All citations link to one list anchor | Citation numbers resolve through the report’s reference URLs | Select the actual referenced source |
| Minimal ad hoc Markdown parser | React Markdown with GFM tables and a citation transform | Render common research formats safely |
| Infrastructure-focused copy | Research-focused language | Explain useful actions to the reader |
| Platform-dependent font stack | Self-hosted Outfit | Consistent rendering without runtime font-service requests |
| Missing account and recovery pages | Login, signup, 404, and error interfaces | Complete the frontend route experience honestly |

## Assets and generation prompts

The eight horizontal reference outputs are [reference-1.png](reference-1.png) through [reference-8.png](reference-8.png). They are design exploration, not screenshots of implemented capabilities. In particular, generated claims, source excerpts, PDF viewers, settings, attachment controls, and profile initials shown in references are not product requirements and were not copied into the app.

The production artwork is `apps/web/public/images/research-instrument.webp`, approximately 76KB. It contains no text or interface controls. Fonts are self-hosted in `apps/web/public/fonts/` with the Outfit OFL license.

Shared reference prompt: one horizontal 16:9 section; HogsKin research platform; graphite `#181C20`, cool white `#F7F8FA`, pale steel `#DCE2E6`, copper `#A96142`; Outfit-like sans; precise tactile surfaces; readable hierarchy; no purple glows, fake metrics, testimonials, or partner brands.

| Output | Prompt direction |
| --- | --- |
| Reference 1 | Centered homepage hero: “A clearer answer. A traceable path.”, research/method actions, layered smoked-glass document plates connected by copper lines |
| Reference 2 | Asymmetric capability section with source inspection, question scope, and research trail |
| Reference 3 | Dark method section with glass document macro and three expandable research stages |
| Reference 4 | Minimal closing research action with white/graphite contrast and a material detail crop |
| Reference 5 | Login section with an atmospheric illustration, email/password fields, and explicit disconnected account state |
| Reference 6 | Signup section with reversed composition, name/email/password fields, and local-workspace entry |
| Reference 7 | Research composer with history, scope choices, examples, and a primary research action |
| Reference 8 | Report workspace with readable article, comparison table, citation controls, sources, and methodology |
| Artwork | Text-free photographic still life of four smoked-glass document plates above matte graphite stone, fine copper traces, steel edges, abstract engraved lines, grey negative space, low diagonal camera angle, restrained studio lighting |

## Verification

Node 24 type checking and the production build passed. All 33 browser checks passed, covering 1440px and 1920px desktop layouts and 390px/320px mobile widths. The completed research run used for visual review was loaded from the local service. Research creation was intercepted in the browser to verify the request without creating a paid agent run.

[browser-check.js](browser-check.js) checks desktop/mobile overflow, composer examples and focus, scope submission, independent report scrolling, citation mapping, methodology, drawer focus, account preview behavior, reduced motion, and 404 recovery.

[edge-check.js](edge-check.js) checks Markdown tables, contained table overflow, raw-HTML non-execution, citation focus restoration, report download, unavailable/failed research states, and narrow-screen layouts. Error and table scenarios use browser-local fixtures; no backend research data is changed.

The design preserves research API routes, SSE updates, cancellation/retry actions, and submission idempotency headers. Authentication now replaces the shared development identity with verified Supabase users. Source excerpts are not fabricated: the current API returns source metadata, so the detail panel links to the original rather than pretending to expose verified supporting passages.

## Workspace motion

The motion pass uses the existing `gsap` and `@gsap/react` dependencies, with Radix Tabs composed in the shadcn pattern and adapted to the existing semantic CSS. It does not initialize Tailwind, replace the theme, import a Figma design, or introduce another animation engine.

- Depth selection and evidence tabs use a single moving marker: 300ms, `power3.out`, interruptible from its current position. Resizing and font changes realign it without replaying the transition.
- Sources/methodology content enters from its activation side over 280ms. Radix handles arrow keys, Home/End, focus and panel relationships. Each tab restores its own scroll position; report and history positions remain independent.
- Research opening, report publication, selected source details, account screens and feedback use short transform/opacity entrances. Polling, typing and ordinary report interactions do not replay the report entrance. Navigation is not delayed for an exit animation.
- Home copy and capability cards reveal with GSAP; native method accordions receive a short content entrance. Existing desktop-only method pinning remains confined to the marketing page.
- Pending requests display a spinner, and loading placeholders/live phases use quiet opacity feedback. Reduced motion disables entrances, pulses and movement; the selected marker still moves immediately to the correct resting state. Media changes are handled at runtime and animation/observer/event cleanup is scoped to component lifetimes.

The interaction-design skill informed timing and compositor-only movement; shadcn informed tab composition and keyboard behavior; the React performance skill kept effects tied to meaningful state changes. Playwright verification now includes the original 33 checks plus 11 motion checks in [motion-check.js](motion-check.js), covering interrupted switching, tab scroll restoration, keyboard controls, resize, runtime reduced motion, and pending/error recovery. All 44 browser checks, Node 24 type checking and the production build passed. Research POSTs remain browser-mocked to avoid creating paid agent runs. See [the evidence-panel preview](motion-report.png).

References: [Nodus visual reference](https://ui.aceternity.com/template-preview/nodus-agent-template), [GSAP installation](https://gsap.com/docs/v3/Installation/), [GSAP React lifecycle](https://gsap.com/resources/React/), and [Radix Tabs keyboard/API reference](https://www.radix-ui.com/primitives/docs/components/tabs).
