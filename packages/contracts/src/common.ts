import { z } from "zod";

export const SCHEMA_VERSION = "1.2" as const;
// Persisted 1.1 snapshots remain readable; new extensions emit 1.2.
export const SchemaVersionSchema = z.enum(["1.1", SCHEMA_VERSION]);
export const UuidSchema = z.uuid();
export const DateTimeSchema = z.iso.datetime({ offset: true });
export const Sha256Schema = z.string().regex(/^[a-f0-9]{64}$/);

export const RunStatusSchema = z.enum([
  "queued",
  "planning",
  "researching",
  "verifying",
  "reflecting",
  "writing",
  "completed",
  "failed",
  "cancelled",
]);

export const ProviderSchema = z.enum([
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
  "official",
  "primary",
  "paper",
  "news",
  "secondary",
  "community",
  "unknown",
]);
