import { z } from "zod";
import { DateTimeSchema, UuidSchema } from "./common";

export const ReportComparisonRequestSchema = z
  .object({
    leftReportId: UuidSchema,
    rightReportId: UuidSchema,
  })
  .strict()
  .refine((value) => value.leftReportId !== value.rightReportId, {
    path: ["rightReportId"],
    message: "Choose two different report versions.",
  });

export const ComparedReportSchema = z
  .object({
    id: UuidSchema,
    runId: UuidSchema,
    version: z.number().int().min(1),
    title: z.string().min(1).max(10000),
    publishedAt: DateTimeSchema,
    quality: z.enum([
      "answered",
      "partial",
      "insufficient_evidence",
      "not_assessed",
    ]),
    structured: z.boolean(),
  })
  .strict();

export const ComparedReportListSchema = z
  .object({
    reports: z.array(ComparedReportSchema).max(50),
    nextCursor: UuidSchema.nullable(),
  })
  .strict();

export const ComparedFindingSchema = z
  .object({
    id: UuidSchema,
    text: z.string().min(1).max(1200),
    section: z.enum([
      "overview",
      "mechanisms",
      "comparison",
      "risks",
      "implications",
    ]),
    citationIds: z.array(UuidSchema).min(1).max(8),
    sourceIds: z.array(UuidSchema).min(1).max(8),
  })
  .strict();

export const ReportComparisonSchema = z
  .object({
    version: z.literal(1),
    left: ComparedReportSchema,
    right: ComparedReportSchema,
    findingsAvailable: z.boolean(),
    added: z.array(ComparedFindingSchema).max(40),
    removed: z.array(ComparedFindingSchema).max(40),
    retained: z
      .array(
        z
          .object({
            leftFindingId: UuidSchema,
            rightFindingId: UuidSchema,
            text: z.string().min(1).max(1200),
            sourceEvidenceChanged: z.boolean(),
          })
          .strict(),
      )
      .max(40),
    sources: z
      .object({
        left: z.number().int().min(0).max(320),
        right: z.number().int().min(0).max(320),
        sharedUrls: z.number().int().min(0).max(320),
        sharedContentHashes: z.number().int().min(0).max(320),
      })
      .strict(),
    textDiff: z
      .object({
        status: z.enum(["available", "size_limit"]),
        unified: z.string().max(120000),
      })
      .strict(),
    limitations: z.array(z.string().min(1).max(500)).min(1).max(5),
  })
  .strict();
