import { z } from "zod";
import { DateTimeSchema, SchemaVersionSchema, UuidSchema } from "./common";

export const ClaimStatusSchema = z.enum([
  "supported",
  "partially_supported",
  "contradicted",
  "insufficient_evidence",
  "not_checked",
]);
export const ExecutionTaskSchema = z
  .object({
    id: UuidSchema,
    nodeId: z.string().max(100),
    name: z.string().max(1000),
    status: z.enum([
      "queued",
      "running",
      "paused",
      "completed",
      "failed",
      "cancelled",
      "skipped",
    ]),
    attempt: z.number().int().nonnegative(),
    startedAt: DateTimeSchema.nullable(),
    completedAt: DateTimeSchema.nullable(),
    errorCode: z.string().max(100).nullable(),
    sourceIds: z.array(UuidSchema).max(200),
    dependsOn: z.array(z.string().max(100)).max(20),
  })
  .strict();
export const FollowupRequestSchema = z
  .object({
    question: z.string().trim().min(5).max(1000),
    gapId: UuidSchema.optional(),
    reportVersion: z.number().int().positive().max(10000).optional(),
    idempotencyKey: z.string().min(16).max(200),
  })
  .strict();
export const PublicGapSchema = z
  .object({
    id: UuidSchema,
    description: z.string().max(1000),
    why: z.string().max(1000),
    suggestedQuery: z.string().max(1000).nullable(),
    status: z.enum(["open", "investigating", "resolved"]),
    claimIds: z.array(UuidSchema).max(40),
    subQuestionIds: z.array(UuidSchema).max(16),
  })
  .strict();
export const RunInsightsSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    tasks: z.array(ExecutionTaskSchema).max(100),
    providerCalls: z
      .array(
        z
          .object({
            id: UuidSchema,
            provider: z.string().max(32),
            operation: z.string().max(64),
            outcome: z.string().max(32),
            startedAt: DateTimeSchema,
            completedAt: DateTimeSchema.nullable(),
          })
          .strict(),
      )
      .max(100),
    gaps: z.array(PublicGapSchema).max(40),
    parentReportId: UuidSchema.nullable(),
    parentRunId: UuidSchema.nullable(),
    followupRuns: z
      .array(
        z
          .object({
            runId: UuidSchema,
            status: z.string().max(32),
            createdAt: DateTimeSchema,
          })
          .strict(),
      )
      .max(20),
    reportVersions: z
      .array(
        z
          .object({
            id: UuidSchema,
            version: z.number().int().positive(),
            createdAt: DateTimeSchema,
          })
          .strict(),
      )
      .max(20),
  })
  .strict();

export const PublicClaimCheckSchema = z
  .object({
    id: UuidSchema,
    claim: z.string().max(1200),
    caveats: z.array(z.string().max(500)).max(5),
    reportId: UuidSchema.nullable(),
    section: z.string().max(300).nullable(),
    publishedInReport: z.boolean(),
    method: z.string().max(200),
    status: ClaimStatusSchema,
    supportingSourceIds: z.array(UuidSchema).max(8),
    contradictingSourceIds: z.array(UuidSchema).max(8),
    citations: z
      .array(
        z
          .object({
            id: UuidSchema,
            sourceId: UuidSchema,
            quote: z.string().max(600),
            exactSpanVerified: z.boolean(),
            verdict: z.enum([
              "supports",
              "partially_supports",
              "contradicts",
              "unrelated",
              "not_recorded",
            ]),
            context: z.string().max(1200).nullable(),
          })
          .strict(),
      )
      .max(8),
  })
  .strict();
