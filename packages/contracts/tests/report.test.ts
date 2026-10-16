import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { ReportDocumentV1Schema } from "../src/index.js";

// The Python suite asserts that the real builder produces this shared fixture.
const fixture = JSON.parse(
  readFileSync(
    new URL("../fixtures/valid/report-document-v1.json", import.meta.url),
    "utf8",
  ),
);
const make = (question = "Compare approaches") => {
  const doc = structuredClone(fixture);
  doc.title = question;
  doc.requirements[0].text = question;
  return doc;
};

describe("report V1 cross-language contract", () => {
  it("accepts the Python builder projection and preserves associations", () => {
    const doc = ReportDocumentV1Schema.parse(make());
    expect(doc.quality.status).toBe("partial");
    expect(doc.requirements[0]?.status).toBe("unresolved");
    expect(doc.requirements[1]?.basis).toBe("model_linked_verified_findings");
    expect(doc.questionCoverage[0]?.basis).toBe("collection_provenance");
    expect(doc.assessmentVersion).toBe("evidence-links-v1");
  });

  it("accepts the public API main question maximum", () => {
    expect(
      ReportDocumentV1Schema.parse(make("Q".repeat(10000))).title.length,
    ).toBe(10000);
  });

  const valid = make();
  it.each([
    (d: any) => {
      d.quality.status = "answered";
    },
    (d: any) => {
      d.quality.verifiedFindings = 0;
    },
    (d: any) => {
      d.quality.status = "insufficient_evidence";
    },
    (d: any) => {
      d.sections[0].claimIds.push("00000000-0000-4000-8000-000000000999");
    },
    (d: any) => {
      d.sections[0].claimIds.push(d.findings[0].id);
    },
    (d: any) => {
      d.sections[0].claimIds = [];
    },
    (d: any) => {
      d.sections[1].id = "overview";
    },
    (d: any) => {
      d.findings[0].citationIds.push(d.findings[0].citationIds[0]);
    },
    (d: any) => {
      d.findings[0].sourceIds = [];
    },
    (d: any) => {
      d.findings[0].sourceIds = ["invalid"];
    },
    (d: any) => {
      d.findings[0].body = "raw page";
    },
    (d: any) => {
      d.findings = Array(41).fill(d.findings[0]);
    },
    (d: any) => {
      d.questionCoverage = Array(17).fill(d.questionCoverage[0]);
    },
    (d: any) => {
      d.requirements[0].claimIds = [d.findings[0].id];
    },
    (d: any) => {
      d.requirements[1].text = "R".repeat(501);
    },
    (d: any) => {
      d.requirements[1].status = "unresolved";
    },
    (d: any) => {
      d.questionCoverage[0].basis = "not_established";
    },
    (d: any) => {
      d.questionCoverage[0].text = "Q".repeat(1001);
    },
    (d: any) => {
      d.requirements = [];
    },
    (d: any) => {
      d.rawPageContent = "body";
    },
  ])("rejects invalid shapes or evidence associations (%#)", (mutate) => {
    const doc = structuredClone(valid);
    mutate(doc);
    expect(ReportDocumentV1Schema.safeParse(doc).success).toBe(false);
  });
});
