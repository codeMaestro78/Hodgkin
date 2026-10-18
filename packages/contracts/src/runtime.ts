import { z } from "zod";
import { UuidSchema } from "./common";
import { BudgetSchema } from "./budget";
import { ResearchModeSchema } from "./mode";

export const ApprovalRequestSchema = z
  .object({
    planId: UuidSchema,
    decision: z.enum(["approve", "reject"]),
  })
  .strict();

export const BatchRequestSchema = z
  .object({
    questions: z.array(z.string().trim().min(5).max(10_000)).min(1).max(20),
    idempotencyKey: z.string().min(16).max(200),
    requireApproval: z.boolean().default(true),
    budgetOverrides: BudgetSchema.partial().optional(),
    mode: ResearchModeSchema.optional(),
  })
  .strict();

export const ScheduleRequestSchema = z
  .object({
    question: z.string().trim().min(5).max(10_000),
    intervalMinutes: z.number().int().min(60).max(43200),
    idempotencyKey: z.string().min(16).max(200),
    requireApproval: z.boolean().default(true),
    budgetOverrides: BudgetSchema.partial().optional(),
    mode: ResearchModeSchema.optional(),
  })
  .strict();
