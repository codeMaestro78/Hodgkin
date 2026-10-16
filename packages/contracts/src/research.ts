import { z } from "zod";
import { BudgetSchema, UsageSchema } from "./budget";
import {
  DateTimeSchema,
  ProviderSchema,
  RunStatusSchema,
  SchemaVersionSchema,
  SourceClassSchema,
  UuidSchema,
} from "./common";
import { ResearchGapSchema } from "./evidence";

export const SubQuestionSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    planVersion: z.number().int().positive(),
    question: z.string().min(5).max(1000),
    rationale: z.string().max(1000),
    successCriteria: z.array(z.string().max(400)).min(1).max(5),
    preferredProvider: ProviderSchema.optional(),
    sourceClasses: z.array(SourceClassSchema).min(1),
    status: z.enum(["pending", "running", "complete", "failed", "skipped"]),
    attempts: z.number().int().nonnegative(),
  })
  .strict();

export const ResearchPlanSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    planVersion: z.number().int().positive(),
    parentPlanVersion: z.number().int().positive().nullable(),
    subQuestionIds: z.array(UuidSchema).min(1).max(16),
    createdAt: DateTimeSchema,
  })
  .strict();

export const WorkerResultSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    subQuestionId: UuidSchema,
    sourceIds: z.array(UuidSchema).max(24),
    evidenceClaimIds: z.array(UuidSchema).max(60),
    gaps: z.array(ResearchGapSchema).max(10),
    providerCallIds: z.array(UuidSchema).max(20),
    completed: z.boolean(),
    errorCode: z.string().max(100).nullable(),
  })
  .strict();

export const ReflectionDecisionSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    decision: z.enum(["continue", "synthesize", "incomplete"]),
    rationale: z.string().min(1).max(2000),
    materialGaps: z.array(ResearchGapSchema).max(4),
    expectedMarginalGain: z.number().min(0).max(1),
  })
  .strict();

export const ResearchStateSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    runId: UuidSchema,
    tenantId: UuidSchema,
    userId: UuidSchema,
    threadId: z.string().min(1).max(200),
    status: RunStatusSchema,
    originalQuestion: z.string().min(5).max(10_000),
    normalizedQuestion: z.string().min(5).max(5_000),
    reportRequirements: z.array(z.string().min(1).max(500).regex(/\S/)).max(20),
    activePlanId: UuidSchema.nullable(),
    planVersion: z.number().int().nonnegative(),
    subQuestionIds: z.array(UuidSchema).max(16),
    sourceIds: z.array(UuidSchema).max(200),
    evidenceClaimIds: z.array(UuidSchema).max(300),
    gapIds: z.array(UuidSchema).max(30),
    reflectionRound: z.number().int().nonnegative(),
    concurrencyLimit: z.number().int().min(1).max(16),
    reflectionDecision: ReflectionDecisionSchema.nullable(),
    budget: BudgetSchema,
    usage: UsageSchema,
    reportId: UuidSchema.nullable(),
    cancellationRequestedAt: DateTimeSchema.nullable(),
    cancelledAt: DateTimeSchema.nullable(),
    errorCode: z.string().max(100).nullable(),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  })
  .strict();

export const ResearchRunProjectionSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    runId: UuidSchema,
    tenantId: UuidSchema,
    userId: UuidSchema,
    status: RunStatusSchema,
    originalQuestion: z.string().min(5).max(10_000),
    budget: BudgetSchema,
    usage: UsageSchema,
    planVersion: z.number().int().nonnegative(),
    sourceCount: z.number().int().nonnegative(),
    evidenceClaimCount: z.number().int().nonnegative(),
    gapCount: z.number().int().nonnegative(),
    reportId: UuidSchema.nullable(),
    cancellationRequestedAt: DateTimeSchema.nullable(),
    cancelledAt: DateTimeSchema.nullable(),
    createdAt: DateTimeSchema,
    updatedAt: DateTimeSchema,
  })
  .strict();

export const WatermarkedRunProjectionSchema = z
  .object({
    run: ResearchRunProjectionSchema,
    snapshotSequence: z.number().int().nonnegative(),
  })
  .strict();

export const CreateResearchRunRequestSchema = z
  .object({
    question: z.string().min(5).max(10_000),
    reportRequirements: z
      .array(z.string().min(1).max(500).regex(/\S/))
      .max(20)
      .default([]),
    budgetOverrides: BudgetSchema.partial().optional(),
    idempotencyKey: z.string().min(16).max(200).optional(),
    requireApproval: z.boolean().default(true),
  })
  .strict();

export const CreateResearchRunResponseSchema = z
  .object({
    runId: UuidSchema,
    status: z.literal("queued"),
  })
  .strict();
