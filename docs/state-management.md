# State Management

The canonical data contracts shared across the frontend, the Next.js BFF,
the event store, and the Python research service. These are Zod schemas in
TypeScript, mirrored as Pydantic models in Python — generate one from the
other or maintain contract tests in CI (see [testing.md](./testing.md)).

Any change to a schema on this page is a **contract change**: bump
`schemaVersion`, update both language definitions, check every consumer,
and update this file in the same change (see
[agent.md](./agent.md#14-agent-modification-rules)).

## RunStatus

```typescript
export const RunStatusSchema = z.enum([
  "queued", "planning", "researching", "verifying",
  "reflecting", "writing", "completed", "failed", "cancelled"
]);
```
Lifecycle diagram: [langgraph.md](./langgraph.md#graph-lifecycle).

## Provider

```typescript
export const ProviderSchema = z.enum([
  "serper", "tavily", "parallel", "browser", "internal"
]);
```
See [provider-routing.md](./provider-routing.md).

## Budget

```typescript
export const BudgetSchema = z.object({
  maxWallClockMs: z.number().int().positive().max(30 * 60_000),
  maxSearchCalls: z.number().int().min(1).max(50),
  maxBrowserSessions: z.number().int().min(0).max(5),
  maxReflectionRounds: z.number().int().min(0).max(3),
  maxInputTokens: z.number().int().positive(),
  maxOutputTokens: z.number().int().positive(),
  maxEstimatedCostUsd: z.number().nonnegative(),
});
```
Owner: `intake` (sets from defaults/plan tier). Mutated by: nothing after
creation — `usage` tracks consumption against it. See
[reflection.md](./reflection.md#hard-limits).

## Source

```typescript
export const SourceSchema = z.object({
  id: z.string().uuid(),
  canonicalUrl: z.string().url(),
  title: z.string().min(1).max(500),
  publisher: z.string().max(250).nullable(),
  provider: ProviderSchema,
  sourceClass: z.enum([
    "official", "primary", "paper", "news", "secondary", "community", "unknown"
  ]),
  publishedAt: z.string().datetime().nullable(),
  retrievedAt: z.string().datetime(),
  contentHash: z.string().min(32),
  artifactRef: z.string().min(1),
  qualityScore: z.number().min(0).max(1),
});
```
Owner: `research_worker` (creation), `verifier` (qualityScore refinement).
`artifactRef` points into object storage — see
[artifact-storage.md](./artifact-storage.md). Never store body content
inline here.

## Citation

```typescript
export const CitationSchema = z.object({
  id: z.string().uuid(),
  sourceId: z.string().uuid(),
  quote: z.string().min(1).max(600),
  locator: z.object({
    heading: z.string().max(300).nullable(),
    startChar: z.number().int().nonnegative().nullable(),
    endChar: z.number().int().nonnegative().nullable(),
  }),
  verified: z.boolean(),
  verificationMethod: z.enum(["exact_span", "semantic_entailment", "manual"]),
});
```
Owner: `verifier`. See [citation-verification.md](./citation-verification.md).

## EvidenceClaim

```typescript
export const EvidenceClaimSchema = z.object({
  id: z.string().uuid(),
  subQuestionId: z.string().uuid(),
  claim: z.string().min(1).max(1200),
  support: z.enum(["supported", "contradicted", "mixed", "insufficient"]),
  citationIds: z.array(z.string().uuid()).max(8),
  sourceIds: z.array(z.string().uuid()).min(1).max(8),
  confidence: z.number().min(0).max(1),
  caveats: z.array(z.string().max(500)).max(5),
  createdBy: z.string().min(1),
});
```
Owner: `distiller` (candidate creation), `verifier` (support
classification). Only `support: "supported"` (and, per report context,
`mixed` with caveats surfaced) claims are eligible for writer context —
`insufficient`/`contradicted`-only claims are retained for audit but
excluded. See [evidence-system.md](./evidence-system.md).

## SubQuestion

```typescript
export const SubQuestionSchema = z.object({
  id: z.string().uuid(),
  question: z.string().min(5).max(1000),
  rationale: z.string().max(1000),
  successCriteria: z.array(z.string().max(400)).min(1).max(5),
  preferredProvider: ProviderSchema.optional(),
  sourceClasses: z.array(SourceSchema.shape.sourceClass).min(1),
  status: z.enum(["pending", "running", "complete", "failed", "skipped"]),
  attempts: z.number().int().nonnegative(),
});
```
Owner: `planner` / `planner_delta` (creation), `research_worker` (status
transitions). Array bound: `ResearchState.subQuestions` max 16 total
across initial + delta rounds.

## ResearchGap

```typescript
export const ResearchGapSchema = z.object({
  id: z.string().uuid(),
  description: z.string().min(1).max(1000),
  severity: z.enum(["low", "medium", "high"]),
  suggestedQuery: z.string().max(500).nullable(),
  resolved: z.boolean(),
});
```
Owner: `verifier` (initial gap detection), `reflector` (materialGaps).

## ResearchState

```typescript
export const ResearchStateSchema = z.object({
  schemaVersion: z.literal("1.0"),
  runId: z.string().uuid(),
  tenantId: z.string().uuid(),
  userId: z.string().uuid(),
  threadId: z.string().min(1),
  status: RunStatusSchema,
  originalQuestion: z.string().min(5).max(10_000),
  normalizedQuestion: z.string().min(5).max(5_000),
  reportRequirements: z.array(z.string().max(500)).max(20),
  subQuestions: z.array(SubQuestionSchema).max(16),
  sourceIds: z.array(z.string().uuid()).max(200),
  evidenceClaimIds: z.array(z.string().uuid()).max(300),
  gaps: z.array(ResearchGapSchema).max(30),
  reflectionRound: z.number().int().nonnegative(),
  budget: BudgetSchema,
  usage: z.object({
    searchCalls: z.number().int().nonnegative(),
    browserSessions: z.number().int().nonnegative(),
    inputTokens: z.number().int().nonnegative(),
    outputTokens: z.number().int().nonnegative(),
    estimatedCostUsd: z.number().nonnegative(),
  }),
  finalReportArtifactRef: z.string().nullable(),
  errorCode: z.string().nullable(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
});
```

This is the single shared LangGraph state object. See field-by-field
ownership notes above; every array field is merged by stable ID via a
reducer, never positionally.

## AgentEvent (SSE payloads)

```typescript
export const AgentEventSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("node.started"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    nodeId: z.string(), agent: z.string(), label: z.string(),
  }),
  z.object({
    type: z.literal("node.progress"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    nodeId: z.string(), message: z.string(), percent: z.number().min(0).max(100).nullable(),
  }),
  z.object({
    type: z.literal("source.discovered"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    source: SourceSchema.pick({ id: true, canonicalUrl: true, title: true, sourceClass: true }),
  }),
  z.object({
    type: z.literal("claim.verified"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    claim: EvidenceClaimSchema,
  }),
  z.object({
    type: z.literal("report.delta"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    markdownDelta: z.string(),
  }),
  z.object({
    type: z.literal("run.completed"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    reportUrl: z.string().url(),
  }),
  z.object({
    type: z.literal("run.failed"),
    eventId: z.string(), runId: z.string().uuid(), timestamp: z.string().datetime(),
    code: z.string(), message: z.string(), retryable: z.boolean(),
  }),
]);
```
Full behavior: [events-and-sse.md](./events-and-sse.md). **Never repurpose
an existing `type` literal for a different payload shape** — add a new
union member instead (see [agent.md](./agent.md#14-agent-modification-rules)).

## ReflectionDecision

See [reflection.md](./reflection.md#reflection-outputs) for the schema and
full semantics.

## Reducers

- Every array of entities with a stable `id` (`subQuestions`, and IDs in
  `sourceIds`/`evidenceClaimIds`/`gaps`) is merged by that ID on fan-in.
- Parallel branches may return in any order or interleave — reducers must
  be commutative and idempotent (applying the same result twice must not
  duplicate an entry).
- On conflicting writes to the same ID from different branches (should be
  rare given per-worker sub-question ownership), the merge policy is
  last-write-wins by `updatedAt`, and the conflict is logged — see
  [reliability.md](./reliability.md#state-merge-conflicts).

## Stable IDs

All entity IDs are UUIDs generated at creation time by the node that
creates the entity, never derived positionally. This is what makes
ID-based reducers possible and what makes `AgentEvent`s and `Citation`s
independently resolvable after the fact.

## Fan-out / fan-in

See [langgraph.md](./langgraph.md#send--fan-out-fan-in).

## Checkpointing

See [langgraph.md](./langgraph.md#checkpoints-and-durable-execution) and
[database.md](./database.md#checkpointer-storage).

## Durable state vs. artifact references

- `ResearchState` (durable, checkpointed, relatively small) lives in
  PostgreSQL via the LangGraph checkpointer and the `runs`/projection
  tables.
- Large content (`artifactRef` targets) lives in object storage — see
  [artifact-storage.md](./artifact-storage.md).
- Never let `ResearchState` grow to hold content instead of references;
  the array size caps above (200 sources, 300 claims, etc.) exist to keep
  it bounded even under a full-budget run.

## State size constraints

| Field | Max |
|---|---|
| `subQuestions` | 16 |
| `sourceIds` | 200 |
| `evidenceClaimIds` | 300 |
| `gaps` | 30 |
| `EvidenceClaim.citationIds` | 8 |
| `EvidenceClaim.sourceIds` | 8 |
| `EvidenceClaim.caveats` | 5 |
| `SubQuestion.successCriteria` | 5 |
| `ReflectionDecision.materialGaps` | 4 |
