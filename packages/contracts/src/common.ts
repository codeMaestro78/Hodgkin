import { z } from "zod";

export const SCHEMA_VERSION = "1.7" as const;
// Persisted 1.1–1.6 snapshots remain readable; typed report contracts emit 1.7.
export const SchemaVersionSchema = z.enum([
  "1.1",
  "1.2",
  "1.3",
  "1.4",
  "1.5",
  "1.6",
  SCHEMA_VERSION,
]);
export const UuidSchema = z.uuid();
export const DateTimeSchema = z.iso.datetime({ offset: true });
export const Sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);

export const RunStatusSchema = z.enum([
  "queued",
  "planning",
  "awaiting_approval",
  "researching",
  "verifying",
  "reflecting",
  "writing",
  "completed",
  "failed",
  "cancelled",
]);

export const ProviderSchema = z.enum([
  "openalex",
  "serper",
  "tavily",
  "parallel",
  "browser",
  "internal",
]);
export const ProviderOperationSchema = z.enum([
  "search",
  "news",
  "extract",
  "research",
  "model",
  "semantic_verify",
]);

export const SourceClassSchema = z.enum([
  "academic",
  "official",
  "primary",
  "paper",
  "news",
  "secondary",
  "community",
  "unknown",
]);
