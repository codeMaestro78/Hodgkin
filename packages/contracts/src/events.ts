import { z } from "zod";
import { DateTimeSchema, SchemaVersionSchema, UuidSchema } from "./common";
import { EvidenceClaimSchema, SourceSchema } from "./evidence";

const EventEnvelopeSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    eventId: UuidSchema,
    eventSequence: z.number().int().positive(),
    tenantId: UuidSchema,
    runId: UuidSchema,
    timestamp: DateTimeSchema,
  })
  .strict();

export const AgentEventSchema = z.discriminatedUnion("type", [
  EventEnvelopeSchema.extend({
    type: z.literal("task.state"),
    taskId: UuidSchema,
    nodeId: z.string().min(1).max(100),
    status: z.enum(["running", "completed", "failed", "cancelled"]),
    attempt: z.number().int().positive(),
    label: z.string().min(1).max(250),
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("node.started"),
    nodeId: z.string().min(1).max(100),
    agent: z.string().min(1).max(100),
    label: z.string().min(1).max(250),
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("node.progress"),
    nodeId: z.string().min(1).max(100),
    message: z.string().min(1).max(1000),
    percent: z.number().min(0).max(100).nullable(),
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("source.discovered"),
    source: SourceSchema.pick({
      id: true,
      canonicalUrl: true,
      title: true,
      sourceClass: true,
    }),
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("claim.verified"),
    claim: EvidenceClaimSchema,
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("report.delta"),
    markdownDelta: z.string().min(1),
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("run.completed"),
    reportId: UuidSchema,
  }),
  EventEnvelopeSchema.extend({
    type: z.literal("run.failed"),
    code: z.string().min(1).max(100),
    message: z.string().min(1).max(1000),
    retryable: z.boolean(),
  }),
]);
