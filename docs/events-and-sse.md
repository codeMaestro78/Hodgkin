# Events and SSE

The append-only event log and its real-time delivery over
Server-Sent Events. See [api.md](./api.md#get-apiresearchrunsrunidevents)
for the HTTP contract and [state-management.md](./state-management.md#agentevent)
for the `AgentEvent` schema.

## Append-only event log

Every node emits at least one event as it executes. Events are:
- **Persisted before publication** — via a transactional outbox or
  equivalent pattern. An event is never published to SSE subscribers
  before it is durably recorded.
- **Ordered with stable, monotonic run-local sequence numbers**, in
  addition to a globally unique `eventId`.
- **Replayable** — a client can reconnect and request everything after a
  given `Last-Event-ID`.

This exists because a research run can take minutes, browser tabs can
lose connectivity, and the frontend must be able to reconstruct exactly
what happened without re-running anything.

## Event catalog

| Event | Payload highlights | Emitted by |
|---|---|---|
| `node.started` | `nodeId`, `agent`, `label` | Every node, on entry |
| `node.progress` | `nodeId`, `message`, `percent` (nullable) | Long-running nodes (workers, distiller) |
| `source.discovered` | `source` (id, canonicalUrl, title, sourceClass) | `research_worker` |
| `claim.verified` | `claim` (full `EvidenceClaim`) | `verifier` |
| `report.delta` | `markdownDelta` | `writer`, while streaming the draft |
| `run.completed` | `reportUrl` | `quality_gate`, on success |
| `run.failed` | `code`, `message`, `retryable` | Any node, on unrecoverable error |

Schema: `AgentEventSchema` is a Zod discriminated union on `type` — see
[state-management.md](./state-management.md#agentevent). **Never
repurpose an existing `type` literal for a new payload shape**; add a new
union member and update this table in the same change.

## Event IDs and sequencing

Every event carries a globally unique `eventId` plus `runId` and
`timestamp`. The event store additionally tracks a run-local sequence
number used for `Last-Event-ID` replay and for the frontend's dedup
reducer (see below).

## Transport

```typescript
// app/api/research/runs/[runId]/events/route.ts
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ runId: string }> }
) {
  const { runId } = await params;
  const session = await requireSession(request);
  await assertRunAccess(session.user.id, runId);

  const lastEventId = request.headers.get("last-event-id");
  const upstream = await openBackendEventStream({ runId, lastEventId, session });

  return new Response(upstream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
```

Notes:
- Native `EventSource` performs `GET` requests only and does not allow
  arbitrary authorization headers — **prefer same-origin cookie
  authentication**. If bearer-token auth is mandatory, use a `fetch()`
  streaming client instead of `EventSource`.
- Deployment platforms may impose duration limits or buffer responses —
  test the exact production adapter (see [deployment.md](./deployment.md)).
  For long research runs, host the SSE service on infrastructure that
  supports long-lived connections, or use a managed realtime channel while
  retaining the same event contract.
- The endpoint sets `Content-Type: text/event-stream`, sends heartbeat
  comments to keep the connection alive through proxies, includes stable
  event IDs, and supports `Last-Event-ID` replay.

## Reconnect behavior

On reconnect, the client:
1. First reconciles against the **durable run projection**
   (`GET /api/research/runs/:runId`) to get current status/counts.
2. Then reopens the SSE stream with `Last-Event-ID` set to the last event
   it successfully processed, applying only the events that follow.

This two-step reconciliation avoids a class of bugs where a client trusts
a stale in-memory view built purely from a partial event stream.

## Heartbeats

The SSE stream sends periodic heartbeat comments (not `AgentEvent`
payloads) to prevent idle-connection timeouts at intermediate proxies.
`PLANNED` — exact interval pending repository inspection; a reasonable
default is every 15–30 seconds.

## Transactional outbox

Writing an event and publishing it are two different guarantees. The
outbox pattern (or equivalent) ensures:
1. The event row is committed to PostgreSQL in the same transaction as
   whatever state change it describes (or immediately after, with a
   reconciliation job for the gap).
2. A separate publisher reads committed, unpublished events and pushes
   them to active SSE subscribers.

This is what makes replay correct — a client reconnecting after a crash
sees exactly the same events a client that never disconnected would have
seen, in the same order.

## Frontend reconciliation

The frontend's event reducer must:
- Deduplicate by `eventId` (a replayed event may be delivered more than
  once at the edges of a reconnect window).
- Apply events in `timestamp`/sequence order, not arrival order, if they
  can arrive out of order across a reconnect boundary.
- Treat `claim.verified` and `source.discovered` as upserts by ID, not
  appends, matching the backend reducer semantics in
  [state-management.md](./state-management.md#reducers).

See [frontend.md](./frontend.md#sse-integration) for the consuming
component.
