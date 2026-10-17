import { z } from "zod";
import { UuidSchema } from "./common";

export const EditResearchPlanRequestSchema = z
  .object({
    planId: UuidSchema,
    expectedPlanVersion: z.number().int().positive(),
    questions: z.array(z.string().trim().min(5).max(1000)).min(1).max(8),
  })
  .strict();

export const EditResearchPlanResponseSchema = z
  .object({
    runId: UuidSchema,
    planId: UuidSchema,
    planVersion: z.number().int().positive(),
    status: z.literal("awaiting_approval"),
    questions: z
      .array(
        z
          .object({ id: UuidSchema, question: z.string().min(5).max(1000) })
          .strict(),
      )
      .min(1)
      .max(8),
  })
  .strict();

export type EditResearchPlanRequest = z.infer<
  typeof EditResearchPlanRequestSchema
>;
export type EditResearchPlanResponse = z.infer<
  typeof EditResearchPlanResponseSchema
>;
