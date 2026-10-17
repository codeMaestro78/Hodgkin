import { z } from "zod";
import {
  DateTimeSchema,
  ProviderSchema,
  SchemaVersionSchema,
  UuidSchema,
} from "./common";
import { ResearchModeSchema, ResearchModeResolutionSchema } from "./mode";

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
    mode: ResearchModeSchema.optional(),
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

export const RetrievalProviderAccountingSchema = z
  .object({
    provider: ProviderSchema,
    searchCalls: z.number().int().nonnegative(),
    discovered: z.number().int().nonnegative().nullable(),
    shortlisted: z.number().int().nonnegative().nullable(),
    excluded: z.number().int().nonnegative().nullable(),
    duplicateWork: z.number().int().nonnegative().nullable(),
    unavailable: z.number().int().nonnegative().nullable(),
    policyVersions: z.array(z.string().min(1).max(100)).max(10),
    countsComplete: z.boolean(),
    extractedSources: z.number().int().nonnegative(),
    citedInVerifiedFinding: z.number().int().nonnegative(),
  })
  .strict();

export const RetrievalExtractionOutcomesSchema = z
  .object({
    succeeded: z.number().int().nonnegative(),
    failed: z.number().int().nonnegative(),
    uncertain: z.number().int().nonnegative(),
    pending: z.number().int().nonnegative(),
    other: z.number().int().nonnegative(),
  })
  .strict();

export const RetrievalSemanticReviewOutcomesSchema = z
  .object({
    supports: z.number().int().nonnegative(),
    partially_supports: z.number().int().nonnegative(),
    contradicts: z.number().int().nonnegative(),
    unrelated: z.number().int().nonnegative(),
    notRecorded: z.number().int().nonnegative(),
  })
  .strict();

export const RetrievalAccountingSchema = z
  .object({
    schemaVersion: z.literal("1.1"),
    providers: z.array(RetrievalProviderAccountingSchema).max(8),
    extractionCalls: z.number().int().nonnegative(),
    extractionOutcomes: RetrievalExtractionOutcomesSchema,
    extractedSources: z.number().int().nonnegative(),
    citedInVerifiedFinding: z.number().int().nonnegative(),
    citationChecks: z.number().int().nonnegative(),
    exactSpanVerifiedCitations: z.number().int().nonnegative(),
    semanticReviewOutcomes: RetrievalSemanticReviewOutcomesSchema,
    publishedClaims: z.number().int().nonnegative(),
    answerUsefulness: z.literal("not_assessed"),
    dimensionRelevance: z.literal("not_assessed"),
    sourceIndependence: z.literal("not_assessed"),
  })
  .strict();

export const RunInsightsSchema = z
  .object({
    mode: ResearchModeSchema.nullable().optional(),
    modePolicyVersion: z.string().min(1).max(100).nullable().optional(),
    modeResolution: ResearchModeResolutionSchema.nullable().optional(),
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
    retrievalAccounting: RetrievalAccountingSchema.optional(),
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
