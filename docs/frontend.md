# Frontend (Next.js)

The Next.js 15 / TypeScript / Tailwind application: research composer,
streaming report, and execution console. See [ui-ux.md](./ui-ux.md) for
the visual/UX specification and [api.md](./api.md) /
[events-and-sse.md](./events-and-sse.md) for the contracts this app
consumes.

`TODO: verify repository path` — proposed root: `apps/web/`.

## Role

The Next.js app is both the **UI** and a **backend-for-frontend (BFF)**:
it authenticates the browser session, proxies/subscribes to the Python
research service's run/event endpoints, and never talks to providers, the
database, or object storage directly (see
[architecture.md](./architecture.md#service-boundaries)).

## Component hierarchy

```text
ResearchWorkspace
├── WorkspaceHeader
│   ├── RunStatus
│   ├── BudgetMeter
│   └── CancelResumeActions
├── ResearchInputPanel
│   ├── QuestionComposer
│   ├── DepthSelector
│   └── SourceAndDomainControls
├── SplitPane
│   ├── ReportCanvas
│   │   ├── ResearchPlan
│   │   ├── StreamingMarkdown
│   │   ├── InlineCitation
│   │   └── EvidencePopover
│   └── IntelligenceRail
│       ├── AgentExecutionTree
│       ├── EvidenceLedger
│       ├── SourceExplorer
│       ├── GapAndConflictPanel
│       └── LiveEventConsole
└── BottomTimeline
    ├── NodeSpans
    ├── ProviderCalls
    └── RetryAndCheckpointMarkers
```

## Component responsibilities

| Component | Backed by |
|---|---|
| `QuestionComposer` | `POST /api/research/runs` |
| `RunStatus`, `BudgetMeter` | Durable run projection (`GET /api/research/runs/:runId`) + `node.*` events |
| `CancelResumeActions` | `POST .../cancel`, `POST .../resume` |
| `StreamingMarkdown` | `report.delta` events |
| `InlineCitation` / `EvidencePopover` | `claim.verified` events + `GET /api/research/sources/:sourceId` |
| `AgentExecutionTree` | `node.started` / `node.progress` events |
| `EvidenceLedger` | `claim.verified` events, deduped by claim ID |
| `SourceExplorer` | `source.discovered` events |
| `GapAndConflictPanel` | Gap/contradiction data on the run projection |
| `LiveEventConsole` | Raw `AgentEvent` stream (concise, generated progress summaries — not private chain-of-thought) |
| `BottomTimeline` | Node spans, provider calls, retry/checkpoint markers derived from events |

## SSE integration

The frontend opens `GET /api/research/runs/:runId/events` via
`EventSource` (or a `fetch()` streaming client if bearer auth is
required — see [events-and-sse.md](./events-and-sse.md#transport)). On
mount or reconnect:

1. Fetch the durable run projection first
   (`GET /api/research/runs/:runId`).
2. Open the event stream with `Last-Event-ID` set to the last processed
   event, if any.
3. Apply incoming events through a reducer that **upserts by ID** and
   **deduplicates by `eventId`** — never blind-append (see
   [events-and-sse.md](./events-and-sse.md#frontend-reconciliation)).

## Cancel / resume

`CancelResumeActions` calls the idempotent
`POST /api/research/runs/:runId/cancel` /
`POST /api/research/runs/:runId/resume` endpoints and reflects the
resulting status optimistically, then reconciles against the next
`node.*`/`run.*` event.

## What the frontend must not do

- Must not call provider APIs, the database, or object storage directly —
  everything goes through the BFF/API layer.
- Must not render raw model chain-of-thought — only concise, generated
  progress summaries and tool metadata (see
  [ui-ux.md](./ui-ux.md#agent-execution-tree)).
- Must not treat `report.delta` token streaming alone as the source of
  truth for "is the run done" — that's `run.completed`/`run.failed`.
