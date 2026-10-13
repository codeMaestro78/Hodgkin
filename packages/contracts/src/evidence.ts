import { z } from "zod";
import {
  DateTimeSchema,
  ProviderSchema,
  SchemaVersionSchema,
  Sha256Schema,
  SourceClassSchema,
  UuidSchema,
} from "./common";

export const SourceSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    canonicalUrl: z.url(),
    title: z.string().min(1).max(500),
    publisher: z.string().max(250).nullable(),
    provider: ProviderSchema,
    sourceClass: SourceClassSchema,
    publishedAt: DateTimeSchema.nullable(),
    retrievedAt: DateTimeSchema,
    contentHash: Sha256Schema,
    artifactRef: z.string().min(1).max(1024),
    qualityScore: z.number().min(0).max(1),
  })
  .strict();

export const CitationVerificationSchema = z
  .object({
    exactSpan: z
      .object({
        verified: z.boolean(),
        evidenceArtifactHash: Sha256Schema,
        startChar: z.number().int().nonnegative().nullable(),
        endChar: z.number().int().nonnegative().nullable(),
      })
      .strict(),
    semanticSupport: z
      .object({
        verdict: z.enum([
          "supports",
          "partially_supports",
          "contradicts",
          "unrelated",
        ]),
        confidence: z.number().min(0).max(1),
        verifierModel: z.string().min(1).max(200),
        verifierVersion: z.string().min(1).max(100),
      })
      .strict(),
    verifiedAt: DateTimeSchema,
  })
  .strict();

export const CitationSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    evidenceClaimId: UuidSchema,
    sourceId: UuidSchema,
    quote: z.string().min(1).max(600),
    locator: z
      .object({
        heading: z.string().max(300).nullable(),
        startChar: z.number().int().nonnegative().nullable(),
        endChar: z.number().int().nonnegative().nullable(),
      })
      .strict(),
    verification: CitationVerificationSchema,
  })
  .strict();

export const EvidenceClaimSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    subQuestionId: UuidSchema,
    claim: z.string().min(1).max(1200),
    support: z.enum(["supported", "contradicted", "mixed", "insufficient"]),
    citationIds: z.array(UuidSchema).max(8),
    sourceIds: z.array(UuidSchema).min(1).max(8),
    confidence: z.number().min(0).max(1),
    caveats: z.array(z.string().max(500)).max(5),
    createdBy: z.string().min(1).max(100),
    model: z.string().min(1).max(200),
    modelVersion: z.string().min(1).max(100),
    promptVersion: z.string().min(1).max(100),
    distillerVersion: z.string().min(1).max(100),
    verifierVersion: z.string().min(1).max(100),
  })
  .strict();

export const ResearchGapSchema = z
  .object({
    schemaVersion: SchemaVersionSchema,
    id: UuidSchema,
    tenantId: UuidSchema,
    runId: UuidSchema,
    description: z.string().min(1).max(1000),
    severity: z.enum(["low", "medium", "high"]),
    suggestedQuery: z.string().max(500).nullable(),
    resolved: z.boolean(),
  })
  .strict();
