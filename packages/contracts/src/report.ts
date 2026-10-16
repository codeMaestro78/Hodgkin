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
