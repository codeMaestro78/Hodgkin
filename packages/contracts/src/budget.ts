import { z } from "zod";
import {
  DateTimeSchema,
  ProviderOperationSchema,
  ProviderSchema,
  SchemaVersionSchema,
  UuidSchema,
} from "./common";

export const BudgetSchema = z
  .object({
    maxWallClockMs: z
      .number()
      .int()
      .positive()
      .max(30 * 60_000),
    maxSearchCalls: z.number().int().min(1).max(50).default(12),
    maxBrowserSessions: z.number().int().min(0).max(5).default(0),
    maxReflectionRounds: z.number().int().min(0).max(3).default(1),
    maxInputTokens: z.number().int().positive(),
    maxOutputTokens: z.number().int().positive(),
    maxEstimatedCostUsd: z.number().nonnegative(),
  })
  .strict();

export const UsageSchema = z
  .object({
    searchCalls: z.number().int().nonnegative(),
    browserSessions: z.number().int().nonnegative(),
    inputTokens: z.number().int().nonnegative(),
    outputTokens: z.number().int().nonnegative(),
    estimatedCostUsd: z.number().nonnegative(),
    reservedSearchCalls: z.number().int().nonnegative(),
    reservedEstimatedCostUsd: z.number().nonnegative(),
  })
  .strict();

export const ReservationStateSchema = z.enum([
  "reserved",
  "consumed",
  "released",
  "uncertain",
]);

export const ProviderCallSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    reservationId: UuidSchema,
    provider: ProviderSchema,
    operation: ProviderOperationSchema,
    requestFingerprint: z.string().min(32).max(128),
    requestSchemaVersion: z.string().min(1).max(40),
    responseSchemaVersion: z.string().min(1).max(40).nullable(),
    providerRequestId: z.string().max(250).nullable(),
    outcome: z.enum(["pending", "succeeded", "failed", "uncertain"]),
    startedAt: DateTimeSchema,
    completedAt: DateTimeSchema.nullable(),
  })
  .strict();
