import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  ReportDocumentSchema,
  ReportDocumentV1Schema,
  ReportDocumentV2Schema,
  ReportDocumentV3Schema,
  ReportDocumentV4Schema,
  type ReportDocumentV2,
} from "../src/index";

const v1 = JSON.parse(
  readFileSync(
    new URL("../fixtures/valid/report-document-v1.json", import.meta.url),
    "utf8",
  ),
);
const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const claim = v1.findings[0].id;
function make(): ReportDocumentV2 {
  return {
    ...structuredClone(v1),
    version: 2,
    assessmentVersion: "coverage-ledger-v1",
    runId: id(400),
    planId: id(401),
    assessmentId: id(402),
    modePolicyVersion: "research-mode-policy-v1",
    dimensions: [
      {
        id: id(500),
        label: "Costs",
        requirementIds: ["question", "requirement-1"],
        status: "verified_covered",
        claimIds: [claim],
        reason: "All planned criteria have reviewed evidence.",
        basis: "criterion-review-v1",
        criteria: [
          {
            id: id(600),
            outcome: "met",
            claimIds: [claim],
            basis: "criterion-review-v1",
            reason: "Reviewed cost evidence.",
          },
        ],
      },
    ],
    requirementOutcomes: ["question", "requirement-1"].map((requirement) => ({
      id: requirement,
      outcome: "established",
      dimensionIds: [id(500)],
      claimIds: [claim],
      reason: "All mapped dimensions have reviewed evidence.",
    })),
    comparisons: [
      {
        dimensionId: id(500),
        cells: [
          { alternative: "Approach A", status: "supported", claimIds: [claim] },
          {
            alternative: "Approach B",
            status: "not_established",
            claimIds: [],
          },
        ],
      },
    ],
    sourceIndependence: {
      status: "unknown",
      reason: "No independence assessment is established.",
    },
  };
}

describe("explicit report V2", () => {
  it("retains V1 provenance separately from assessed outcomes", () => {
    const parsed = ReportDocumentV2Schema.parse(make());
    expect(parsed.requirements).toEqual(v1.requirements);
    expect(parsed.questionCoverage).toEqual(v1.questionCoverage);
    expect(parsed.requirements[0]?.status).toBe("unresolved");
    expect(parsed.requirementOutcomes[0]?.outcome).toBe("established");
    expect(parsed.quality.status).toBe("partial");
  });

  it("dispatches V1 and explicit V2 without upgrading old documents", () => {
    expect(ReportDocumentSchema.parse(v1)).toEqual(v1);
    expect(ReportDocumentSchema.parse(make()).version).toBe(2);
    expect(ReportDocumentV1Schema.safeParse(make()).success).toBe(false);
    expect(ReportDocumentV2Schema.safeParse(v1).success).toBe(false);
  });

  it("defaults only omitted comparisons to an empty array", () => {
    const { comparisons, ...document } = make();
    expect(ReportDocumentV2Schema.parse(document).comparisons).toEqual([]);
    expect(
      ReportDocumentV2Schema.safeParse({ ...document, comparisons: null })
        .success,
    ).toBe(false);
  });

  it("allows honest unassessed dimensions despite provenance claim links", () => {
    const doc = make();
    doc.dimensions[0]!.status = "evidence_found";
    doc.dimensions[0]!.basis = "not_assessed";
    doc.dimensions[0]!.criteria[0]!.outcome = "unknown";
    doc.dimensions[0]!.criteria[0]!.basis = "not_assessed";
    doc.dimensions[0]!.criteria[0]!.claimIds = [];
    for (const outcome of doc.requirementOutcomes) {
      outcome.outcome = "not_assessed";
      outcome.claimIds = [];
    }
    expect(ReportDocumentV2Schema.safeParse(doc).success).toBe(true);
  });

  it("allows partial outcomes supported by reviewed partial criteria", () => {
    const doc = make();
    doc.dimensions[0]!.status = "unresolved";
    doc.dimensions[0]!.criteria[0]!.outcome = "partial";
    for (const outcome of doc.requirementOutcomes)
      outcome.outcome = "partially_established";
    expect(ReportDocumentV2Schema.safeParse(doc).success).toBe(true);
  });

  it("supports insufficient evidence without fabricating claims or assessments", () => {
    const doc = make();
    doc.findings = [];
    for (const row of [
      ...doc.sections,
      ...doc.requirements,
      ...doc.questionCoverage,
    ])
      row.claimIds = [];
    for (const row of doc.requirements) {
      row.status = "unresolved";
      row.basis = "not_established";
    }
    for (const row of doc.questionCoverage) {
      row.status = "unresolved";
      row.basis = "not_established";
    }
    doc.quality.status = "insufficient_evidence";
    doc.quality.verifiedFindings = 0;
    doc.dimensions = [];
    for (const row of doc.requirementOutcomes) {
      row.outcome = "not_assessed";
      row.claimIds = [];
      row.dimensionIds = [];
    }
    doc.comparisons = [];
    expect(ReportDocumentV2Schema.safeParse(doc).success).toBe(true);
  });

  const mutations: [string, (doc: any) => void][] = [
    [
      "implicit version",
      (d) => {
        delete d.version;
      },
    ],
    [
      "wrong assessment version",
      (d) => {
        d.assessmentVersion = "evidence-links-v1";
      },
    ],
    [
      "missing immutable run identity",
      (d) => {
        delete d.runId;
      },
    ],
    [
      "invalid plan identity",
      (d) => {
        d.planId = "not-a-uuid";
      },
    ],
    [
      "missing assessment identity",
      (d) => {
        delete d.assessmentId;
      },
    ],
    [
      "blank policy",
      (d) => {
        d.modePolicyVersion = "  ";
      },
    ],
    [
      "unknown top-level fields",
      (d) => {
        d.rawContent = "not public";
      },
    ],
    [
      "answered quality",
      (d) => {
        d.quality.status = "answered";
      },
    ],
    [
      "duplicate dimensions",
      (d) => {
        d.dimensions.push(structuredClone(d.dimensions[0]));
      },
    ],
    [
      "duplicate criteria across dimensions",
      (d) => {
        const second = structuredClone(d.dimensions[0]);
        second.id = id(501);
        d.dimensions.push(second);
      },
    ],
    [
      "unknown dimension requirement",
      (d) => {
        d.dimensions[0].requirementIds.push("requirement-2");
      },
    ],
    [
      "duplicate dimension requirement",
      (d) => {
        d.dimensions[0].requirementIds.push("question");
      },
    ],
    [
      "invalid dimension state",
      (d) => {
        d.dimensions[0].status = "answered";
      },
    ],
    [
      "empty criterion list",
      (d) => {
        d.dimensions[0].criteria = [];
      },
    ],
    [
      "duplicate dimension claims",
      (d) => {
        d.dimensions[0].claimIds.push(claim);
      },
    ],
    [
      "dangling dimension claims",
      (d) => {
        d.dimensions[0].claimIds = [id(999)];
      },
    ],
    [
      "dangling criterion claims",
      (d) => {
        d.dimensions[0].criteria[0].claimIds = [id(999)];
      },
    ],
    [
      "criterion claims outside dimension",
      (d) => {
        d.dimensions[0].claimIds = [];
      },
    ],
    [
      "unassessed criterion certification",
      (d) => {
        d.dimensions[0].criteria[0].basis = "not_assessed";
      },
    ],
    [
      "met without claims",
      (d) => {
        d.dimensions[0].criteria[0].claimIds = [];
      },
    ],
    [
      "dimension basis mismatch",
      (d) => {
        d.dimensions[0].basis = "not_assessed";
      },
    ],
    [
      "verified coverage with partial criterion",
      (d) => {
        d.dimensions[0].criteria[0].outcome = "partial";
      },
    ],
    [
      "missing requirement outcome",
      (d) => {
        d.requirementOutcomes.pop();
      },
    ],
    [
      "duplicate requirement outcomes",
      (d) => {
        d.requirementOutcomes[1].id = "question";
      },
    ],
    [
      "unknown outcome requirement",
      (d) => {
        d.requirementOutcomes[1].id = "requirement-2";
      },
    ],
    [
      "unknown outcome dimension",
      (d) => {
        d.requirementOutcomes[0].dimensionIds = [id(999)];
      },
    ],
    [
      "duplicate outcome dimensions",
      (d) => {
        d.requirementOutcomes[0].dimensionIds.push(id(500));
      },
    ],
    [
      "discarded requirement dimension mapping",
      (d) => {
        d.requirementOutcomes[0].dimensionIds = [];
      },
    ],
    [
      "outcome claims outside mapped dimensions",
      (d) => {
        d.requirementOutcomes[0].claimIds = [id(999)];
      },
    ],
    [
      "unassessed requirement with claims",
      (d) => {
        d.requirementOutcomes[0].outcome = "not_assessed";
      },
    ],
    [
      "established without claims",
      (d) => {
        d.requirementOutcomes[0].claimIds = [];
      },
    ],
    [
      "established with unresolved dimension",
      (d) => {
        d.dimensions[0].status = "unresolved";
      },
    ],
    [
      "partial based only on nominations",
      (d) => {
        d.dimensions[0].status = "evidence_found";
        d.dimensions[0].criteria[0].outcome = "unknown";
        d.dimensions[0].criteria[0].claimIds = [];
        d.dimensions[0].criteria[0].basis = "not_assessed";
        d.dimensions[0].basis = "not_assessed";
        for (const row of d.requirementOutcomes)
          row.outcome = "partially_established";
      },
    ],
    [
      "comparison with one alternative",
      (d) => {
        d.comparisons[0].cells.pop();
      },
    ],
    [
      "comparison alternatives differing only by case and space",
      (d) => {
        d.comparisons[0].cells[1].alternative = " approach a ";
      },
    ],
    [
      "comparison without any support",
      (d) => {
        d.comparisons[0].cells[0].status = "not_established";
        d.comparisons[0].cells[0].claimIds = [];
      },
    ],
    [
      "supported comparison cell without claims",
      (d) => {
        d.comparisons[0].cells[0].claimIds = [];
      },
    ],
    [
      "not-established cell with claims",
      (d) => {
        d.comparisons[0].cells[1].claimIds = [claim];
      },
    ],
    [
      "unknown comparison dimension",
      (d) => {
        d.comparisons[0].dimensionId = id(999);
      },
    ],
    [
      "duplicate comparison dimension",
      (d) => {
        d.comparisons.push(structuredClone(d.comparisons[0]));
      },
    ],
    [
      "independence certification",
      (d) => {
        d.sourceIndependence.status = "independent";
      },
    ],
    [
      "blank independence reason",
      (d) => {
        d.sourceIndependence.reason = "  ";
      },
    ],
    // V1 shape spreading omits refinements: these prove V1 safeParse still runs.
    [
      "V1 duplicate findings",
      (d) => {
        d.findings.push(structuredClone(d.findings[0]));
      },
    ],
    [
      "V1 duplicate sections",
      (d) => {
        d.sections[1].id = "overview";
      },
    ],
    [
      "V1 invalid section placement",
      (d) => {
        d.sections[0].claimIds = [];
      },
    ],
    [
      "V1 invalid requirement identity",
      (d) => {
        d.requirements[1].id = "requirement-2";
      },
    ],
    [
      "V1 main-question nomination",
      (d) => {
        d.requirements[0].claimIds = [claim];
      },
    ],
    [
      "V1 requirement association mismatch",
      (d) => {
        d.requirements[1].basis = "not_established";
      },
    ],
    [
      "V1 provenance association mismatch",
      (d) => {
        d.questionCoverage[0].status = "unresolved";
      },
    ],
    [
      "V1 dangling section claims",
      (d) => {
        d.sections[0].claimIds = [id(999)];
      },
    ],
    [
      "V1 finding count mismatch",
      (d) => {
        d.quality.verifiedFindings = 0;
      },
    ],
    [
      "V1 insufficient evidence with findings",
      (d) => {
        d.quality.status = "insufficient_evidence";
      },
    ],
  ];
  it.each(mutations)("rejects %s", (_name, mutate) => {
    const doc = make();
    mutate(doc);
    expect(ReportDocumentV2Schema.safeParse(doc).success).toBe(false);
    expect(ReportDocumentSchema.safeParse(doc).success).toBe(false);
  });
});

function makeV3() {
  const doc = make();
  const first = doc.findings[0]!;
  const sourceA = first.sourceIds[0]!;
  const sourceB = id(202);
  const second = structuredClone(first);
  second.id = id(2);
  second.text = "A second verified statement that may disagree.";
  second.citationIds = [id(102)];
  second.sourceIds = [sourceB];
  doc.findings.push(second);
  doc.sections[0]!.claimIds.push(second.id);
  doc.dimensions[0]!.claimIds.push(second.id);
  doc.dimensions[0]!.criteria[0]!.claimIds.push(second.id);
  for (const outcome of doc.requirementOutcomes)
    outcome.claimIds.push(second.id);
  doc.quality.verifiedFindings = doc.findings.length;
  return {
    ...doc,
    version: 3 as const,
    assessmentVersion: "provenance-conflicts-v1" as const,
    sourceRelationships: [
      {
        fromSourceId: sourceA,
        toSourceId: sourceB,
        kind: "same_work" as const,
        confidence: "observed" as const,
        basis: "observed_doi_match" as const,
        identifier: "doi:10.1234/example",
      },
    ],
    conflicts: [
      {
        id: id(700),
        dimensionId: id(500),
        criterionIds: [id(600)],
        claimIds: [first.id, second.id],
        status: "potential" as const,
        basis: "criterion-review-v1" as const,
        reason: "Independent criterion review nominated a potential disagreement." as const,
      },
    ],
  };
}

describe("explicit report V3 provenance and conflict boundaries", () => {
  it("accepts report-scoped observed relationships and potential conflicts", () => {
    const parsed = ReportDocumentV3Schema.parse(makeV3());
    expect(parsed.sourceIndependence.status).toBe("unknown");
    expect(parsed.conflicts[0]?.status).toBe("potential");
    expect(ReportDocumentSchema.parse(parsed).version).toBe(3);
  });

  it.each([
    ["outside source", (doc: ReturnType<typeof makeV3>) => { doc.sourceRelationships[0]!.toSourceId = id(999); }],
    ["self relationship", (doc: ReturnType<typeof makeV3>) => { doc.sourceRelationships[0]!.toSourceId = doc.sourceRelationships[0]!.fromSourceId; }],
    ["unobserved basis", (doc: ReturnType<typeof makeV3>) => { doc.sourceRelationships[0]!.basis = "observed_content_hash_match" as never; }],
    ["unobserved confidence", (doc: ReturnType<typeof makeV3>) => { doc.sourceRelationships[0]!.confidence = "inferred" as never; }],
    ["outside claim", (doc: ReturnType<typeof makeV3>) => { doc.conflicts[0]!.claimIds[1] = id(999); }],
    ["claim outside reviewed criterion", (doc: ReturnType<typeof makeV3>) => { doc.dimensions[0]!.criteria[0]!.claimIds = [claim]; }],
    ["malformed DOI", (doc: ReturnType<typeof makeV3>) => { doc.sourceRelationships[0]!.identifier = "doi:not-a-doi"; }],
    ["confirmed conflict", (doc: ReturnType<typeof makeV3>) => { doc.conflicts[0]!.status = "confirmed" as never; }],
  ])("rejects %s", (_name, mutate) => {
    const doc = makeV3();
    mutate(doc);
    expect(ReportDocumentV3Schema.safeParse(doc).success).toBe(false);
  });

  it("keeps V1 and V2 readers unchanged", () => {
    const v2 = structuredClone(makeV3()) as unknown as Record<string, unknown>;
    delete v2.sourceRelationships;
    delete v2.conflicts;
    v2.version = 2;
    v2.assessmentVersion = "coverage-ledger-v1";
    expect(ReportDocumentSchema.parse(v2).version).toBe(2);
    expect(ReportDocumentV3Schema.safeParse(v1).success).toBe(false);
  });
});

function makeV4() {
  const doc = makeV3();
  const [first, second] = doc.findings;
  return {
    ...doc,
    version: 4 as const,
    assessmentVersion: "evidence-narrative-v1" as const,
    narrative: {
      basis: "narrative-composition-v1" as const,
      status: "composed" as "composed" | "not_composed",
      reason: null as string | null,
      blocks: [
        {
          id: "narrative-1",
          role: "answer" as string,
          dimensionId: null as string | null,
          sentences: [
            { claimId: first!.id, citationIds: [...first!.citationIds], origin: "ledger" as "ledger" | "narrative" },
          ],
        },
        {
          id: "narrative-2",
          role: "dimension" as string,
          dimensionId: id(500) as string | null,
          sentences: [
            { claimId: second!.id, citationIds: [...second!.citationIds], origin: "narrative" as "ledger" | "narrative" },
          ],
        },
      ],
      narrativeClaimIds: [second!.id],
      proposedSentenceCount: 3,
      publishedSentenceCount: 2,
      rejectedSentenceCount: 1,
    },
  };
}

describe("explicit report V4 evidence narrative", () => {
  it("accepts a narrative made only of verified findings", () => {
    const doc = makeV4();
    doc.mode = "balanced";
    const parsed = ReportDocumentV4Schema.parse(doc);
    expect(parsed.narrative.blocks).toHaveLength(2);
    expect(ReportDocumentSchema.parse(parsed).version).toBe(4);
  });

  it("accepts an honest uncomposed narrative", () => {
    const doc = makeV4();
    doc.mode = "balanced";
    doc.narrative = {
      ...doc.narrative,
      status: "not_composed",
      reason: "insufficient_time",
      blocks: [],
      narrativeClaimIds: [],
      proposedSentenceCount: 0,
      publishedSentenceCount: 0,
      rejectedSentenceCount: 0,
    };
    expect(ReportDocumentV4Schema.safeParse(doc).success).toBe(true);
  });

  type V4 = ReturnType<typeof makeV4>;
  it.each([
    ["role outside focused mode", (doc: V4) => { doc.mode = "focused"; }],
    ["composed without reason null", (doc: V4) => { doc.narrative.reason = "composition_failed"; }],
    ["unknown claim", (doc: V4) => { doc.narrative.blocks[0]!.sentences[0]!.claimId = id(999); }],
    ["changed citations", (doc: V4) => { doc.narrative.blocks[0]!.sentences[0]!.citationIds = [id(999)]; }],
    ["late answer", (doc: V4) => { doc.narrative.blocks.reverse(); doc.narrative.blocks[0]!.id = "narrative-1"; doc.narrative.blocks[1]!.id = "narrative-2"; }],
    ["non-sequential block id", (doc: V4) => { doc.narrative.blocks[1]!.id = "narrative-7"; }],
    ["dimension block without dimension", (doc: V4) => { doc.narrative.blocks[1]!.dimensionId = null; }],
    ["unknown dimension", (doc: V4) => { doc.narrative.blocks[1]!.dimensionId = id(999); }],
    ["origin mismatch", (doc: V4) => { doc.narrative.blocks[1]!.sentences[0]!.origin = "ledger"; }],
    ["unplaced narrative claim", (doc: V4) => { doc.narrative.blocks.pop(); doc.narrative.publishedSentenceCount = 1; doc.narrative.rejectedSentenceCount = 2; }],
    ["duplicate placement", (doc: V4) => { doc.narrative.blocks[1]!.sentences.push(structuredClone(doc.narrative.blocks[1]!.sentences[0]!)); }],
    ["wrong published count", (doc: V4) => { doc.narrative.publishedSentenceCount = 3; }],
    ["wrong rejected count", (doc: V4) => { doc.narrative.rejectedSentenceCount = 0; }],
    ["confirmed narrative status", (doc: V4) => { doc.narrative.status = "verified" as never; }],
    ["extra narrative text", (doc: V4) => { (doc.narrative.blocks[0] as Record<string, unknown>).text = "Unverified prose."; }],
    ["broken V3 boundary", (doc: V4) => { doc.conflicts[0]!.status = "confirmed" as never; }],
  ])("rejects %s", (_name, mutate) => {
    const doc = makeV4();
    doc.mode = "balanced";
    mutate(doc);
    expect(ReportDocumentV4Schema.safeParse(doc).success).toBe(false);
  });

  it("keeps V3 documents readable without a narrative", () => {
    expect(ReportDocumentSchema.parse(makeV3()).version).toBe(3);
    expect(ReportDocumentV4Schema.safeParse(makeV3()).success).toBe(false);
  });
});
