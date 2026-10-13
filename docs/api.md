# API

Application HTTP endpoints exposed by the Next.js BFF (which proxies to
the Python research service — see [architecture.md](./architecture.md#service-boundaries)).
All request/response bodies validate against the schemas in
[state-management.md](./state-management.md). Authentication and
authorization details: [security.md](./security.md).

The BFF root is confirmed at `apps/web/app/api/`; only `/api/health` exists in the current slice.
The research endpoints below remain planned under `apps/web/app/api/research/**/route.ts`.

## `POST /api/research/runs`

| | |
|---|---|
| Purpose | Create a new research run |
| Auth | Required — HTTP-only session cookie |
| Request | `{ question: string, reportRequirements?: string[], budgetOverrides?: Partial<Budget> }` (validated against a request schema derived from `ResearchStateSchema`'s input fields) |
| Response | `202 Accepted` `{ runId: string, status: "queued" }` |
| Validation | Question length/content, budget overrides within `BudgetSchema` bounds, tenant/user resolved from session |
| Errors | `400` invalid request, `401` unauthenticated, `429` tenant budget/rate limit exceeded |
| Idempotency | Client may supply an idempotency key; server may also issue one. Duplicate creation with the same key returns the existing run instead of creating a second one |
| Authorization | Tenant/user derived from session; run is created scoped to that tenant |

## `GET /api/research/runs/:runId`

| | |
|---|---|
| Purpose | Fetch the current durable run projection |
| Auth | Required |
| Request | Path param `runId` |
| Response | `200` — a projection of `ResearchState` (status, budget/usage, subQuestions, gaps, counts) suitable for reconciling after an SSE reconnect |
| Validation | `runId` must be a UUID owned by the caller's tenant |
| Errors | `401`, `403` (cross-tenant access), `404` |
| Idempotency | N/A (read) |
| Authorization | Must belong to caller's tenant — see [security.md](./security.md#tenant-isolation) |

## `GET /api/research/runs/:runId/events`

| | |
|---|---|
| Purpose | SSE stream of `AgentEvent`s for a run |
| Auth | Required — same-origin cookie auth (see [events-and-sse.md](./events-and-sse.md#transport)) |
| Request | Path param `runId`; optional `Last-Event-ID` header for replay |
| Response | `text/event-stream`, one `AgentEvent` per SSE message, heartbeats as comments |
| Validation | `runId` ownership check before opening the stream |
| Errors | `401`, `403`, `404` |
| Idempotency | Replay via `Last-Event-ID` is safe to call repeatedly |
| Authorization | Tenant-scoped |

## `POST /api/research/runs/:runId/cancel`

| | |
|---|---|
| Purpose | Request cancellation of a running run |
| Auth | Required |
| Request | Path param `runId`, empty body |
| Response | `202 Accepted` `{ runId, status: "cancelling" }` (transitions to `"cancelled"` once a node boundary is reached — see [research-workflow.md](./research-workflow.md#cancellation)) |
| Validation | Run must exist and be in a cancellable status |
| Errors | `401`, `403`, `404`, `409` (already terminal) |
| Idempotency | Idempotent — repeated calls are no-ops once cancellation is in flight or complete |
| Authorization | Tenant-scoped |

## `POST /api/research/runs/:runId/resume`

| | |
|---|---|
| Purpose | Resume a run interrupted for approval or recovered after infrastructure failure |
| Auth | Required |
| Request | Path param `runId`, optional `{ approval: {...} }` body for interrupt-specific approvals |
| Response | `202 Accepted` `{ runId, status }` |
| Validation | Run must have a valid LangGraph checkpoint to resume from |
| Errors | `401`, `403`, `404`, `409` (not resumable) |
| Idempotency | Idempotent against the same checkpoint |
| Authorization | Tenant-scoped |

## `GET /api/research/runs/:runId/report`

| | |
|---|---|
| Purpose | Fetch the final report and evidence map |
| Auth | Required |
| Request | Path param `runId` |
| Response | `200` `{ reportMarkdown: string, citations: Citation[], sources: Source[], evidenceClaims: EvidenceClaim[] }`; `404`/`409` if not yet completed |
| Validation | Run must be `status: "completed"` |
| Errors | `401`, `403`, `404`, `409` (not yet complete) |
| Idempotency | N/A (read) |
| Authorization | Tenant-scoped |

## `GET /api/research/sources/:sourceId`

| | |
|---|---|
| Purpose | Fetch safe source metadata and a permitted excerpt |
| Auth | Required |
| Request | Path param `sourceId` |
| Response | `200` — `Source` metadata plus the specific `Citation` excerpt(s) tied to it for this run; never the full raw body |
| Validation | `sourceId` must belong to a run visible to the caller's tenant |
| Errors | `401`, `403`, `404` |
| Idempotency | N/A (read) |
| Authorization | Tenant-scoped; excerpt-only, not full artifact access — see [artifact-storage.md](./artifact-storage.md#access-control) |

## Example: creating and following a run

```http
POST /api/research/runs
Content-Type: application/json

{ "question": "How should recent export controls affect semiconductor investment strategy?" }
```

```http
202 Accepted
{ "runId": "b6e2...", "status": "queued" }
```

```http
GET /api/research/runs/b6e2.../events
Accept: text/event-stream
```

```text
event: node.started
data: {"type":"node.started","eventId":"...","runId":"b6e2...","timestamp":"...","nodeId":"intake","agent":"intake","label":"Validating request"}

event: run.completed
data: {"type":"run.completed","eventId":"...","runId":"b6e2...","timestamp":"...","reportUrl":"/api/research/runs/b6e2.../report"}
```

See [events-and-sse.md](./events-and-sse.md) for the complete event
catalog and reconnect semantics.
