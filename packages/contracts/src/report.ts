import { z } from "zod";
import { UuidSchema } from "./common";

const section = z.enum([
  "overview",
  "mechanisms",
  "comparison",
  "risks",
  "implications",
]);
const claimIds = z.array(UuidSchema).max(40);
const status = z.enum(["addressed", "unresolved"]);
const association = {
  status,
  claimIds,
  basis: z.enum(["model_linked_verified_findings", "not_established"]),
};
const requirement = z.discriminatedUnion("origin", [
  z
    .object({
      id: z.literal("question"),
      origin: z.literal("main_question"),
      text: z.string().min(1).max(10000),
      ...association,
    })
    .strict(),
  z
    .object({
      id: z.string().regex(/^requirement-([1-9]|1[0-9]|20)$/),
      origin: z.literal("user_requirement"),
      text: z.string().min(1).max(500).regex(/\S/),
      ...association,
    })
    .strict(),
]);

/** Compact verified-evidence projection; contains no page bodies or generated prose.
 * `addressed` means evidence association only, never certified fulfillment.
 * `answered` is reserved for independently validated criteria or future acceptance;
 * the evidence-links-v1 builder cannot establish it.
 */
export const ReportDocumentV1Schema = z
  .object({
    version: z.literal(1),
    assessmentVersion: z.literal("evidence-links-v1"),
    mode: z.enum(["focused", "balanced", "deep"]),
    title: z.string().min(1).max(10000),
    sections: z
      .array(
        z
          .object({
            id: section,
            title: z.string().min(1).max(200),
            claimIds,
          })
          .strict(),
      )
      .length(5),
    findings: z
      .array(
        z
          .object({
            id: UuidSchema,
            text: z.string().min(1).max(1200),
            section,
            citationIds: z.array(UuidSchema).min(1).max(8),
            sourceIds: z.array(UuidSchema).min(1).max(8),
          })
          .strict(),
      )
      .max(40),
    requirements: z.array(requirement).min(1).max(21),
    questionCoverage: z
      .array(
        z
          .object({
            id: UuidSchema,
            text: z.string().min(1).max(1000),
            status,
            claimIds,
            basis: z.enum(["collection_provenance", "not_established"]),
          })
          .strict(),
      )
      .max(16),
    quality: z
      .object({
        status: z.enum(["answered", "partial", "insufficient_evidence"]),
        reason: z.string().min(1).max(1000),
        verifiedFindings: z.number().int().min(0).max(40),
        excludedFindings: z.number().int().nonnegative(),
      })
      .strict(),
  })
  .strict()
  .superRefine((doc, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: "custom", message });
    const unique = (ids: string[]) => new Set(ids).size === ids.length;
    const ids = doc.findings.map((f) => f.id);
    if (!unique(ids)) fail("Duplicate finding IDs");
    if (!unique(doc.sections.map((s) => s.id))) fail("Duplicate section IDs");
    if (!unique(doc.requirements.map((r) => r.id)))
      fail("Duplicate requirement IDs");
    if (!unique(doc.questionCoverage.map((q) => q.id)))
      fail("Duplicate question IDs");
    for (const finding of doc.findings) {
      if (!unique(finding.citationIds) || !unique(finding.sourceIds))
        fail("Duplicate evidence links");
    }
    const known = new Set(ids);
    for (const row of [
      ...doc.sections,
      ...doc.requirements,
      ...doc.questionCoverage,
    ]) {
      if (!unique(row.claimIds) || row.claimIds.some((id) => !known.has(id))) {
        fail("Duplicate or dangling claim links");
      }
    }
    const overview = doc.findings.filter((f) => f.section === "overview");
    const summaryIds = new Set(
      (overview.length ? overview : doc.findings.slice(0, 2)).map((f) => f.id),
    );
    for (const row of doc.sections) {
      const expected = doc.findings
        .filter((f) =>
          row.id === "overview"
            ? summaryIds.has(f.id)
            : !summaryIds.has(f.id) && f.section === row.id,
        )
        .map((f) => f.id);
      if (JSON.stringify(row.claimIds) !== JSON.stringify(expected))
        fail("Invalid section placement");
    }
    doc.requirements.forEach((row, index) => {
      if (
        row.id !== (index === 0 ? "question" : `requirement-${index}`) ||
        row.origin !== (index === 0 ? "main_question" : "user_requirement")
      )
        fail("Invalid requirement identity");
      if (index === 0 && (row.text !== doc.title || row.claimIds.length))
        fail("Main question is unassessed");
      if (index > 0 && row.text.length > 500)
        fail("User requirement exceeds 500 characters");
      const linked = row.claimIds.length > 0;
      if (
        row.status !== (linked ? "addressed" : "unresolved") ||
        row.basis !==
          (linked ? "model_linked_verified_findings" : "not_established")
      )
        fail("Invalid requirement association");
    });
    for (const row of doc.questionCoverage) {
      const linked = row.claimIds.length > 0;
      if (
        row.status !== (linked ? "addressed" : "unresolved") ||
        row.basis !== (linked ? "collection_provenance" : "not_established")
      )
        fail("Invalid question association");
    }
    if (doc.quality.verifiedFindings !== doc.findings.length)
      fail("Finding count mismatch");
    if (doc.quality.status === "answered")
      fail("evidence-links-v1 cannot certify answered");
    if (
      (doc.findings.length === 0) !==
      (doc.quality.status === "insufficient_evidence")
    )
      fail("Invalid evidence quality");
  });

export type ReportDocumentV1 = z.infer<typeof ReportDocumentV1Schema>;

const requirementId = z
  .string()
  .regex(/^(question|requirement-([1-9]|1[0-9]|20))$/);
const assessmentBasis = z.enum(["criterion-review-v1", "not_assessed"]);
const assessmentReason = z.string().min(1).max(1000).regex(/\S/);
const assessedDimension = z
  .object({
    id: UuidSchema,
    label: z.string().min(1).max(1000).regex(/\S/),
    requirementIds: z.array(requirementId).min(1).max(21),
    status: z.enum([
      "not_started",
      "searching",
      "evidence_found",
      "verified_covered",
      "unresolved",
      "blocked",
    ]),
    claimIds,
    reason: assessmentReason,
    basis: assessmentBasis,
    criteria: z
      .array(
        z
          .object({
            id: UuidSchema,
            outcome: z.enum(["met", "partial", "not_met", "unknown"]),
            claimIds,
            basis: assessmentBasis,
            reason: assessmentReason,
          })
          .strict(),
      )
      .min(1)
      .max(16),
  })
  .strict();

/** Explicit coverage assessment; V1 arrays retain their provenance-only meaning.
 * Callers authenticate the immutable scope and criterion reviews. This contract
 * checks references and conservative state consistency, not semantic truth.
 */
export const ReportDocumentV2Schema = z
  .object({
    ...ReportDocumentV1Schema.shape,
    version: z.literal(2),
    assessmentVersion: z.literal("coverage-ledger-v1"),
    runId: UuidSchema,
    planId: UuidSchema,
    assessmentId: UuidSchema,
    modePolicyVersion: z.string().min(1).max(100).regex(/\S/),
    dimensions: z.array(assessedDimension).max(32),
    requirementOutcomes: z
      .array(
        z
          .object({
            id: requirementId,
            outcome: z.enum([
              "established",
              "partially_established",
              "not_established",
              "not_assessed",
            ]),
            dimensionIds: z.array(UuidSchema).max(32),
            claimIds,
            reason: assessmentReason,
          })
          .strict(),
      )
      .min(1)
      .max(21),
    comparisons: z
      .array(
        z
          .object({
            dimensionId: UuidSchema,
            cells: z
              .array(
                z
                  .object({
                    alternative: z.string().trim().min(1).max(300),
                    status: z.enum(["supported", "not_established"]),
                    claimIds,
                  })
                  .strict(),
              )
              .min(2)
              .max(20),
          })
          .strict(),
      )
      .max(32)
      .default([]),
    sourceIndependence: z
      .object({
        status: z.literal("unknown"),
        reason: assessmentReason,
      })
      .strict(),
    quality: ReportDocumentV1Schema.shape.quality.extend({
      status: z.enum(["partial", "insufficient_evidence"]),
    }),
  })
  .strict()
  .superRefine((doc, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: "custom", message });
    const unique = (ids: string[]) => new Set(ids).size === ids.length;
    // Explicitly project known V1 keys: new fields cannot weaken V1 strictness.
    const legacy = Object.fromEntries(
      Object.keys(ReportDocumentV1Schema.shape).map((key) => [
        key,
        doc[key as keyof typeof doc],
      ]),
    );
    const checked = ReportDocumentV1Schema.safeParse({
      ...legacy,
      version: 1,
      assessmentVersion: "evidence-links-v1",
    });
    if (!checked.success)
      for (const issue of checked.error.issues)
        ctx.addIssue({
          code: "custom",
          path: issue.path,
          message: issue.message,
        });

    const knownClaims = new Set(doc.findings.map((f) => f.id));
    const knownRequirements = new Set(doc.requirements.map((r) => r.id));
    const dimensions = new Map(doc.dimensions.map((d) => [d.id, d]));
    const validClaims = (ids: string[]) => {
      if (!unique(ids) || ids.some((id) => !knownClaims.has(id)))
        fail("Duplicate or dangling assessed claim links");
    };
    if (!unique(doc.dimensions.map((d) => d.id)))
      fail("Duplicate dimension IDs");
    if (!unique(doc.dimensions.flatMap((d) => d.criteria.map((c) => c.id))))
      fail("Duplicate criterion IDs");
    for (const dim of doc.dimensions) {
      validClaims(dim.claimIds);
      if (
        !unique(dim.requirementIds) ||
        dim.requirementIds.some((id) => !knownRequirements.has(id))
      )
        fail("Duplicate or unknown dimension requirement links");
      for (const criterion of dim.criteria) {
        validClaims(criterion.claimIds);
        if (criterion.claimIds.some((id) => !dim.claimIds.includes(id)))
          fail("Criterion claims must belong to dimension");
        if (
          criterion.basis === "not_assessed" &&
          (criterion.outcome !== "unknown" || criterion.claimIds.length)
        )
          fail("Unassessed criterion cannot certify an outcome");
        if (
          ["met", "partial"].includes(criterion.outcome) &&
          (criterion.basis !== "criterion-review-v1" ||
            !criterion.claimIds.length)
        )
          fail("Met/partial criterion needs reviewed claim support");
      }
      const reviewed = dim.criteria.some(
        (c) => c.basis === "criterion-review-v1",
      );
      if ((dim.basis === "criterion-review-v1") !== reviewed)
        fail("Dimension basis must match criterion reviews");
      if (
        dim.status === "verified_covered" &&
        (dim.basis !== "criterion-review-v1" ||
          !dim.claimIds.length ||
          dim.criteria.some((c) => c.outcome !== "met"))
      )
        fail(
          "Verified coverage requires every criterion to be reviewed and met",
        );
    }
    if (
      !unique(doc.requirementOutcomes.map((r) => r.id)) ||
      doc.requirementOutcomes.length !== knownRequirements.size ||
      doc.requirementOutcomes.some((r) => !knownRequirements.has(r.id))
    )
      fail(
        "Requirement outcomes must cover each provenance requirement exactly once",
      );
    for (const row of doc.requirementOutcomes) {
      validClaims(row.claimIds);
      if (
        !unique(row.dimensionIds) ||
        row.dimensionIds.some((id) => !dimensions.has(id))
      )
        fail("Duplicate or unknown outcome dimension links");
      const linked = row.dimensionIds.flatMap((id) =>
        dimensions.has(id) ? [dimensions.get(id)!] : [],
      );
      const mapped = doc.dimensions
        .filter((d) => d.requirementIds.includes(row.id))
        .map((d) => d.id);
      if (
        mapped.length !== row.dimensionIds.length ||
        mapped.some((id) => !row.dimensionIds.includes(id))
      )
        fail("Requirement outcome must retain all mapped dimensions");
      if (
        row.claimIds.some((id) => !linked.some((d) => d.claimIds.includes(id)))
      )
        fail("Outcome claims must belong to linked dimensions");
      if (row.outcome === "not_assessed" && row.claimIds.length)
        fail("Unassessed requirement cannot certify claim support");
      if (["established", "partially_established"].includes(row.outcome)) {
        if (!linked.length || !row.claimIds.length)
          fail("Established/partial requirement needs dimensions and claims");
        const reviewedClaims = new Set(
          linked.flatMap((d) =>
            d.criteria
              .filter(
                (c) =>
                  c.basis === "criterion-review-v1" &&
                  ["met", "partial"].includes(c.outcome),
              )
              .flatMap((c) => c.claimIds),
          ),
        );
        if (row.claimIds.some((id) => !reviewedClaims.has(id)))
          fail(
            "Requirement support must come from reviewed met/partial criteria",
          );
        if (
          row.outcome === "established" &&
          linked.some((d) => d.status !== "verified_covered")
        )
          fail(
            "Established requirement needs every mapped dimension verified covered",
          );
      }
    }
    if (!unique(doc.comparisons.map((row) => row.dimensionId)))
      fail("Duplicate comparison dimensions");
    for (const row of doc.comparisons) {
      const dim = dimensions.get(row.dimensionId);
      if (!dim) fail("Unknown comparison dimension");
      if (!unique(row.cells.map((c) => c.alternative.toLowerCase())))
        fail("Comparison alternatives must be distinct");
      if (!row.cells.some((c) => c.status === "supported"))
        fail("Comparison needs at least one supported cell");
      for (const cell of row.cells) {
        validClaims(cell.claimIds);
        if (cell.claimIds.some((id) => !dim?.claimIds.includes(id)))
          fail("Comparison claims must belong to its dimension");
        if ((cell.status === "supported") !== cell.claimIds.length > 0)
          fail("Comparison cell support must match claim links");
      }
    }
  });

const sourceRelationship = z
  .object({
    fromSourceId: UuidSchema,
    toSourceId: UuidSchema,
    kind: z.enum(["same_content", "same_work", "same_publisher"]),
    confidence: z.literal("observed"),
    basis: z.enum([
      "observed_content_hash_match",
      "observed_doi_match",
      "verified_publisher_metadata_match",
    ]),
    identifier: z.string().min(1).max(2500).optional(),
  })
  .strict();

const assessedConflict = z
  .object({
    id: UuidSchema,
    dimensionId: UuidSchema,
    criterionIds: z.array(UuidSchema).min(1).max(16),
    claimIds: z.array(UuidSchema).min(2).max(40),
    status: z.literal("potential"),
    basis: z.literal("criterion-review-v1"),
    reason: z.literal("Independent criterion review nominated a potential disagreement."),
  })
  .strict();

/** V3 adds bounded source-lineage observations and model-nominated conflicts.
 * Neither establishes source independence or adjudicates a conflict as fact. */
export const ReportDocumentV3Schema = z
  .object({
    ...ReportDocumentV2Schema.shape,
    version: z.literal(3),
    assessmentVersion: z.literal("provenance-conflicts-v1"),
    sourceRelationships: z.array(sourceRelationship).max(190),
    conflicts: z.array(assessedConflict).max(128),
  })
  .strict()
  .superRefine((doc, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: "custom", message });
    const v2Keys = Object.keys(ReportDocumentV2Schema.shape);
    const v2 = Object.fromEntries(
      v2Keys.map((key) => [
        key,
        key === "version"
          ? 2
          : key === "assessmentVersion"
            ? "coverage-ledger-v1"
            : doc[key as keyof typeof doc],
      ]),
    );
    const checked = ReportDocumentV2Schema.safeParse(v2);
    if (!checked.success)
      for (const issue of checked.error.issues)
        ctx.addIssue({ code: "custom", path: issue.path, message: issue.message });

    const reportSources = new Set(doc.findings.flatMap((finding) => finding.sourceIds));
    const relationshipKeys = new Set<string>();
    for (const row of doc.sourceRelationships) {
      if (
        row.fromSourceId >= row.toSourceId ||
        !reportSources.has(row.fromSourceId) ||
        !reportSources.has(row.toSourceId)
      )
        fail("Source relationships must link two distinct report sources in canonical order");
      const key = `${row.fromSourceId}:${row.toSourceId}:${row.kind}`;
      if (relationshipKeys.has(key)) fail("Duplicate source relationship");
      relationshipKeys.add(key);
      const expectedBasis = {
        same_content: "observed_content_hash_match",
        same_work: "observed_doi_match",
        same_publisher: "verified_publisher_metadata_match",
      }[row.kind];
      if (row.basis !== expectedBasis) fail("Relationship basis does not match its kind");
      if (
        (row.kind === "same_content" && row.identifier !== undefined) ||
        (row.kind !== "same_content" && !row.identifier?.trim())
      )
        fail("Relationship identifier does not match its evidence basis");
      if (
        row.kind === "same_work" &&
        !/^doi:10\.\d{4,9}\/[^\s\u0000-\u001f\u007f]+$/i.test(row.identifier ?? "")
      )
        fail("Same-work relationship requires an observed DOI identifier");
    }

    const dimensions = new Map(doc.dimensions.map((dimension) => [dimension.id, dimension]));
    const conflictKeys = new Set<string>();
    const conflictIds = new Set<string>();
    for (const conflict of doc.conflicts) {
      const dimension = dimensions.get(conflict.dimensionId);
      if (!dimension) fail("Conflict references an unknown report dimension");
      if (conflictIds.has(conflict.id)) fail("Duplicate conflict ID");
      conflictIds.add(conflict.id);
      if (
        new Set(conflict.criterionIds).size !== conflict.criterionIds.length ||
        new Set(conflict.claimIds).size !== conflict.claimIds.length
      )
        fail("Conflict links must be unique");
      const criteria = new Set(dimension?.criteria.map((criterion) => criterion.id) ?? []);
      if (conflict.criterionIds.some((id) => !criteria.has(id)))
        fail("Conflict references an unknown criterion");
      const claims = new Set(dimension?.claimIds ?? []);
      if (conflict.claimIds.some((id) => !claims.has(id)))
        fail("Conflict claims must belong to the linked dimension");
      const criterionClaims = new Set(
        conflict.criterionIds.flatMap(
          (id) => dimension?.criteria.find((criterion) => criterion.id === id)?.claimIds ?? [],
        ),
      );
      if (conflict.claimIds.some((id) => !criterionClaims.has(id)))
        fail("Conflict claims must be linked to a reviewed criterion");
      const key = `${conflict.dimensionId}:${[...conflict.criterionIds].sort().join(":")}:${[...conflict.claimIds].sort().join(":")}`;
      if (conflictKeys.has(key)) fail("Duplicate conflict assessment");
      conflictKeys.add(key);
    }
  });

const narrativeRole = z.enum(["answer", "dimension", "synthesis", "tradeoffs", "implications"]);
/** Mode-specific organisation limits mirrored by the backend narrative composer. */
export const NARRATIVE_LIMITS = {
  focused: { roles: ["answer", "tradeoffs"], maxBlocks: 3, maxSentences: 6, maxNewClaims: 4 },
  balanced: {
    roles: ["answer", "dimension", "tradeoffs", "implications"],
    maxBlocks: 8,
    maxSentences: 8,
    maxNewClaims: 8,
  },
  deep: {
    roles: ["answer", "dimension", "synthesis", "tradeoffs", "implications"],
    maxBlocks: 14,
    maxSentences: 8,
    maxNewClaims: 16,
  },
} as const;

const narrativeSentence = z
  .object({
    claimId: UuidSchema,
    citationIds: z.array(UuidSchema).min(1).max(8),
    origin: z.enum(["ledger", "narrative"]),
  })
  .strict();

const evidenceNarrative = z
  .object({
    basis: z.literal("narrative-composition-v1"),
    status: z.enum(["composed", "not_composed"]),
    reason: z
      .enum([
        "no_verified_findings",
        "insufficient_time",
        "writer_unavailable",
        "composition_failed",
        "no_supported_sentences",
      ])
      .nullable(),
    blocks: z
      .array(
        z
          .object({
            id: z.string().regex(/^narrative-([1-9]|1[0-4])$/),
            role: narrativeRole,
            dimensionId: UuidSchema.nullable(),
            sentences: z.array(narrativeSentence).min(1).max(8),
          })
          .strict(),
      )
      .max(14),
    narrativeClaimIds: z.array(UuidSchema).max(16),
    proposedSentenceCount: z.number().int().min(0).max(112),
    publishedSentenceCount: z.number().int().min(0).max(112),
    rejectedSentenceCount: z.number().int().min(0).max(112),
  })
  .strict();

/** V4 orders verified findings into a mode-specific narrative. Every sentence is an
 * exact ledger finding; narrative-origin findings passed the same exact-passage and
 * fully supportive semantic-review gate. Headings are fixed presentation labels. */
export const ReportDocumentV4Schema = z
  .object({
    ...ReportDocumentV3Schema.shape,
    version: z.literal(4),
    assessmentVersion: z.literal("evidence-narrative-v1"),
    narrative: evidenceNarrative,
  })
  .strict()
  .superRefine((doc, ctx) => {
    const fail = (message: string) => ctx.addIssue({ code: "custom", message });
    const v3Keys = Object.keys(ReportDocumentV3Schema.shape);
    const v3 = Object.fromEntries(
      v3Keys.map((key) => [
        key,
        key === "version"
          ? 3
          : key === "assessmentVersion"
            ? "provenance-conflicts-v1"
            : doc[key as keyof typeof doc],
      ]),
    );
    const checked = ReportDocumentV3Schema.safeParse(v3);
    if (!checked.success)
      for (const issue of checked.error.issues)
        ctx.addIssue({ code: "custom", path: issue.path, message: issue.message });

    const narrative = doc.narrative;
    const limits = NARRATIVE_LIMITS[doc.mode];
    const composed = narrative.status === "composed";
    if (composed !== (narrative.blocks.length > 0))
      fail("Composed narrative status must match its blocks");
    if (composed !== (narrative.reason === null))
      fail("Only an uncomposed narrative records a reason");
    if (narrative.blocks.length > limits.maxBlocks) fail("Narrative exceeds its mode block limit");
    if (narrative.narrativeClaimIds.length > limits.maxNewClaims)
      fail("Narrative exceeds its mode claim limit");
    const findings = new Map(doc.findings.map((finding) => [finding.id, finding]));
    const dimensions = new Set(doc.dimensions.map((dimension) => dimension.id));
    const narrativeIds = new Set(narrative.narrativeClaimIds);
    if (narrativeIds.size !== narrative.narrativeClaimIds.length)
      fail("Duplicate narrative claim IDs");
    const placed = new Set<string>();
    const blockKeys = new Set<string>();
    let sentences = 0;
    narrative.blocks.forEach((block, index) => {
      if (block.id !== `narrative-${index + 1}`) fail("Narrative block IDs must be sequential");
      if (!(limits.roles as readonly string[]).includes(block.role))
        fail("Narrative role is not allowed for this mode");
      if (block.role === "answer" && index !== 0) fail("The answer block must open the narrative");
      if ((block.role === "dimension") !== (block.dimensionId !== null))
        fail("Only dimension blocks reference a dimension");
      if (block.dimensionId !== null && !dimensions.has(block.dimensionId))
        fail("Narrative block references an unknown dimension");
      const key = `${block.role}:${block.dimensionId ?? ""}`;
      if (blockKeys.has(key)) fail("Duplicate narrative block");
      blockKeys.add(key);
      if (block.sentences.length > limits.maxSentences)
        fail("Narrative block exceeds its mode sentence limit");
      for (const sentence of block.sentences) {
        sentences += 1;
        const finding = findings.get(sentence.claimId);
        if (!finding) fail("Narrative sentence references an unknown finding");
        else if (JSON.stringify(sentence.citationIds) !== JSON.stringify(finding.citationIds))
          fail("Narrative citations must match the verified finding");
        if (placed.has(sentence.claimId)) fail("A finding may appear once in the narrative");
        placed.add(sentence.claimId);
        if ((sentence.origin === "narrative") !== narrativeIds.has(sentence.claimId))
          fail("Narrative sentence origin does not match its claim");
      }
    });
    if (narrative.narrativeClaimIds.some((id) => !placed.has(id)))
      fail("Every narrative claim must be placed in the narrative");
    if (narrative.publishedSentenceCount !== sentences)
      fail("Published narrative count must match its sentences");
    if (
      narrative.rejectedSentenceCount !==
      narrative.proposedSentenceCount - narrative.publishedSentenceCount
    )
      fail("Rejected narrative count must match proposed and published counts");
  });

export const ReportDocumentSchema = z.union([
  ReportDocumentV1Schema,
  ReportDocumentV2Schema,
  ReportDocumentV3Schema,
  ReportDocumentV4Schema,
]);
export type ReportDocumentV2 = z.infer<typeof ReportDocumentV2Schema>;
export type ReportDocumentV3 = z.infer<typeof ReportDocumentV3Schema>;
export type ReportDocumentV4 = z.infer<typeof ReportDocumentV4Schema>;
export type ReportDocument = z.infer<typeof ReportDocumentSchema>;
