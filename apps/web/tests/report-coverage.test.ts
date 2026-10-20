import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  ReportDocumentV1Schema,
  ReportDocumentV2Schema,
  ReportDocumentV3Schema,
  ReportDocumentV4Schema,
  ReportDocumentV5Schema,
  ReportDocumentV6Schema,
} from "@research/contracts";
import {
  hasNumericalFinding,
  parseReportDocument,
} from "../lib/report-document";

it("flags source-reported percentages without treating citations as independent verification", () => {
  expect(
    hasNumericalFinding({
      findings: [
        {
          text: "Wait times fell by 18% across 450 cities.",
          sourceIds: ["source-a"],
        },
      ],
    }),
  ).toBe(true);
  expect(
    hasNumericalFinding({
      findings: [{ text: "Two systems use queues.", sourceIds: ["source-a"] }],
    }),
  ).toBe(false);
  expect(
    hasNumericalFinding({
      findings: [
        {
          text: "Wait times fell by 18%.",
          sourceIds: ["source-a", "source-b"],
        },
      ],
    }),
  ).toBe(true);
});
import { ReportCoverage } from "../app/components/report-coverage";
import { TechnicalResults } from "../app/components/technical-results";
import { reportDisplayMarkdown } from "../lib/report-presentation";

const legacy = ReportDocumentV1Schema.parse(
  JSON.parse(
    readFileSync(
      new URL(
        "../../../packages/contracts/fixtures/valid/report-document-v1.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ),
);
const dimensionId = "00000000-0000-4000-8000-000000000401";
const criterionId = "00000000-0000-4000-8000-000000000402";
const findingId = legacy.findings[0]!.id;

function assessed() {
  return ReportDocumentV2Schema.parse({
    ...legacy,
    version: 2,
    assessmentVersion: "coverage-ledger-v1",
    runId: "00000000-0000-4000-8000-000000000501",
    planId: "00000000-0000-4000-8000-000000000502",
    assessmentId: "00000000-0000-4000-8000-000000000503",
    modePolicyVersion: "research-mode-policy-v1",
    dimensions: [
      {
        id: dimensionId,
        label: "Operating costs",
        requirementIds: ["requirement-1"],
        status: "verified_covered",
        claimIds: [findingId],
        reason: "Cost criterion was reviewed against verified findings.",
        basis: "criterion-review-v1",
        criteria: [
          {
            id: criterionId,
            outcome: "met",
            claimIds: [findingId],
            basis: "criterion-review-v1",
            reason: "Verified evidence establishes the cost criterion.",
          },
        ],
      },
    ],
    requirementOutcomes: [
      {
        id: "question",
        outcome: "not_assessed",
        dimensionIds: [],
        claimIds: [],
        reason: "The whole question has not been assessed.",
      },
      {
        id: "requirement-1",
        outcome: "established",
        dimensionIds: [dimensionId],
        claimIds: [findingId],
        reason:
          "The requested cost assessment is established by reviewed criteria.",
      },
    ],
    sourceIndependence: {
      status: "unknown",
      reason: "Independent evidence lineages have not been assessed.",
    },
  });
}

function provenanceReport() {
  const document = assessed();
  const first = document.findings[0]!;
  const second = structuredClone(first);
  const secondId = "00000000-0000-4000-8000-000000000601";
  const secondSourceId = "00000000-0000-4000-8000-000000000602";
  const [fromSourceId, toSourceId] = [
    first.sourceIds[0]!,
    secondSourceId,
  ].sort();
  second.id = secondId;
  second.text = "A second verified statement that may disagree.";
  second.citationIds = ["00000000-0000-4000-8000-000000000603"];
  second.sourceIds = [secondSourceId];
  document.findings.push(second);
  document.sections[0]!.claimIds.push(secondId);
  document.dimensions[0]!.claimIds.push(secondId);
  document.dimensions[0]!.criteria[0]!.claimIds.push(secondId);
  for (const outcome of document.requirementOutcomes)
    if (outcome.id !== "question") outcome.claimIds.push(secondId);
  document.quality.verifiedFindings = document.findings.length;
  return ReportDocumentV3Schema.parse({
    ...document,
    version: 3,
    assessmentVersion: "provenance-conflicts-v1",
    sourceRelationships: [
      {
        fromSourceId,
        toSourceId,
        kind: "same_work",
        confidence: "observed",
        basis: "observed_doi_match",
        identifier: "doi:10.1234/example",
      },
    ],
    conflicts: [
      {
        id: "00000000-0000-4000-8000-000000000604",
        dimensionId,
        criterionIds: [criterionId],
        claimIds: [findingId, secondId],
        status: "potential",
        basis: "criterion-review-v1",
        reason:
          "Independent criterion review nominated a potential disagreement.",
      },
    ],
  });
}

function narrativeReport(composed = true) {
  const document = provenanceReport();
  const [first, second] = document.findings;
  return ReportDocumentV4Schema.parse({
    ...document,
    mode: "balanced",
    version: 4,
    assessmentVersion: "evidence-narrative-v1",
    narrative: composed
      ? {
          basis: "narrative-composition-v1",
          status: "composed",
          reason: null,
          blocks: [
            {
              id: "narrative-1",
              role: "answer",
              dimensionId: null,
              sentences: [
                {
                  claimId: first!.id,
                  citationIds: first!.citationIds,
                  origin: "ledger",
                },
              ],
            },
            {
              id: "narrative-2",
              role: "dimension",
              dimensionId,
              sentences: [
                {
                  claimId: second!.id,
                  citationIds: second!.citationIds,
                  origin: "narrative",
                },
              ],
            },
          ],
          narrativeClaimIds: [second!.id],
          proposedSentenceCount: 3,
          publishedSentenceCount: 2,
          rejectedSentenceCount: 1,
        }
      : {
          basis: "narrative-composition-v1",
          status: "not_composed",
          reason: "insufficient_time",
          blocks: [],
          narrativeClaimIds: [],
          proposedSentenceCount: 0,
          publishedSentenceCount: 0,
          rejectedSentenceCount: 0,
        },
  });
}

it("renders a V5 literal technical result with a source inspection action", () => {
  const base = narrativeReport();
  const finding = base.findings[0]!;
  const document = ReportDocumentV5Schema.parse({
    ...base,
    version: 5,
    assessmentVersion: "technical-results-v1",
    technicalResults: [
      {
        kind: "theorem",
        title: "Theorem 2",
        claimId: finding.id,
        citationIds: finding.citationIds.slice(0, 1),
        sourceIds: finding.sourceIds.slice(0, 1),
        sourceArtifactHash: "a".repeat(64),
        assumptions: ["reversible chains"],
        notation: [],
        sourceLocation: "Theorem 2",
        expression: {
          sourceText: "t_mix <= log(1/pi_min)/lambda",
          representation: "plain_text",
          transformation: "none",
        },
        verification: "exact_passage_and_scoped_semantic_claim_review_v2",
      },
    ],
  });
  const html = renderToStaticMarkup(
    createElement(TechnicalResults, {
      document,
      sourceTitles: new Map([[finding.sourceIds[0]!, "Primary paper"]]),
      onOpenSource: () => {},
    }),
  );
  expect(html).toContain("Source-stated technical results");
  expect(html).toContain("t_mix &lt;= log(1/pi_min)/lambda");
  expect(html).toContain("Inspect Primary paper");
  expect(
    reportDisplayMarkdown(
      "Before\n<!-- technical-results-v1:start -->\n## Source-stated technical results\n<!-- technical-results-v1:end -->\nAfter",
      true,
    ),
  ).not.toContain("Source-stated technical results");
});

it("renders only contract-admitted V6 measurements and server-approved charts", () => {
  const base = ReportDocumentV5Schema.parse({
    ...narrativeReport(),
    version: 5,
    assessmentVersion: "technical-results-v1",
    technicalResults: [],
  });
  const finding = base.findings[0]!;
  const measurement = (id: string, subject: string, value: string) => ({
    id,
    title: `Outcome for ${subject}`,
    claimId: finding.id,
    citationId: finding.citationIds[0],
    sourceId: finding.sourceIds[0],
    sourceArtifactHash: "a".repeat(64),
    subject,
    metric: "response rate",
    value,
    unit: "%",
    population: "adults",
    period: "2024",
    method: "randomized trial",
    definition: "participants with response",
    sourcePassage: `Outcome for ${subject}: response rate ${value}% in adults in 2024.`,
    sourceLocation: "Table 2",
    plotValue: value,
    verification: "exact_passage_and_scoped_semantic_claim_review_v1" as const,
  });
  const rows = [
    measurement("measurement-1", "Group A", "47.2"),
    measurement("measurement-2", "Group B", "51.0"),
  ];
  const document = ReportDocumentV6Schema.parse({
    ...base,
    version: 6,
    assessmentVersion: "typed-measurements-v1",
    measurements: rows,
    measurementComparisons: [
      {
        id: "measurement-comparison-1",
        metric: "response rate",
        measurementIds: rows.map((row) => row.id),
        status: "comparable",
        basis: "exact_scope_match_v1",
      },
    ],
    measurementCharts: [
      {
        id: "chart-1",
        title: "response rate by subject",
        metric: "response rate",
        unit: "%",
        population: "adults",
        period: "2024",
        method: "randomized trial",
        definition: "participants with response",
        measurementIds: rows.map((row) => row.id),
        basis: "identical_metric_unit_population_period_method_definition_v1",
      },
    ],
  });
  expect(() =>
    ReportDocumentV6Schema.parse({ ...document, measurementComparisons: [] }),
  ).toThrow();
  const html = renderToStaticMarkup(
    createElement(TechnicalResults, {
      document,
      sourceTitles: new Map([[finding.sourceIds[0]!, "Study"]]),
      onOpenSource: () => {},
    }),
  );
  expect(html).toContain("Source-stated measurements");
  expect(html).toContain("47.2");
  expect(html).toContain("response rate by subject");
  expect(html).toContain("Comparable within recorded scope");
  expect(html).toContain("exact cited passage");
});

it("rejects a V6 chart when population differs between measurement records", () => {
  const base = ReportDocumentV5Schema.parse({
    ...narrativeReport(),
    version: 5,
    assessmentVersion: "technical-results-v1",
    technicalResults: [],
  });
  const finding = base.findings[0]!;
  const row = (id: string, population: string) => ({
    id,
    title: "Outcome",
    claimId: finding.id,
    citationId: finding.citationIds[0],
    sourceId: finding.sourceIds[0],
    sourceArtifactHash: "a".repeat(64),
    subject: id,
    metric: "rate",
    value: "2",
    unit: "%",
    population,
    period: "2024",
    method: "trial",
    definition: "response",
    sourcePassage: "rate 2%",
    sourceLocation: null,
    plotValue: "2",
    verification: "exact_passage_and_scoped_semantic_claim_review_v1" as const,
  });
  const rows = [row("m1", "adults"), row("m2", "children")];
  expect(() =>
    ReportDocumentV6Schema.parse({
      ...base,
      version: 6,
      assessmentVersion: "typed-measurements-v1",
      measurements: rows,
      measurementComparisons: [
        {
          id: "measurement-comparison-1",
          metric: "rate",
          measurementIds: ["m1", "m2"],
          status: "not_established",
          basis: "missing_or_incompatible_scope_v1",
        },
      ],
      measurementCharts: [
        {
          id: "chart",
          title: "rate",
          metric: "rate",
          unit: "%",
          population: "adults",
          period: "2024",
          method: "trial",
          definition: "response",
          measurementIds: ["m1", "m2"],
          basis: "identical_metric_unit_population_period_method_definition_v1",
        },
      ],
    }),
  ).toThrow();
});

it("explains when a V5 report has no admitted technical results", () => {
  const document = ReportDocumentV5Schema.parse({
    ...narrativeReport(),
    version: 5,
    assessmentVersion: "technical-results-v1",
    technicalResults: [],
  });
  const html = renderToStaticMarkup(
    createElement(TechnicalResults, {
      document,
      sourceTitles: new Map(),
      onOpenSource: () => {},
    }),
  );
  expect(html).toContain("Source-stated technical results");
  expect(html).toContain(
    "No source-located technical results passed this report’s evidence checks.",
  );
  expect(html).not.toContain("technical-results-list");
});

it("renders source-literal LaTeX without trusting embedded links", () => {
  const base = narrativeReport();
  const finding = base.findings[0]!;
  const document = ReportDocumentV5Schema.parse({
    ...base,
    version: 5,
    assessmentVersion: "technical-results-v1",
    technicalResults: [
      {
        kind: "bound",
        title: "Recorded bound",
        claimId: finding.id,
        citationIds: finding.citationIds.slice(0, 1),
        sourceIds: finding.sourceIds.slice(0, 1),
        sourceArtifactHash: "a".repeat(64),
        assumptions: [],
        notation: [],
        sourceLocation: null,
        expression: {
          sourceText: String.raw`\lambda \le 1 \href{javascript:alert(1)}{unsafe}`,
          representation: "latex",
          transformation: "none",
        },
        verification: "exact_passage_and_scoped_semantic_claim_review_v2",
      },
    ],
  });
  const html = renderToStaticMarkup(
    createElement(TechnicalResults, {
      document,
      sourceTitles: new Map(),
      onOpenSource: () => {},
    }),
  );
  expect(html).toContain("katex");
  expect(html).not.toContain('href="javascript:');
});

function render(value: unknown, sources: { id: string; title: string }[] = []) {
  const document = parseReportDocument(value);
  return document
    ? renderToStaticMarkup(createElement(ReportCoverage, { document, sources }))
    : null;
}

it("dual-reads validated v1 and v2 without rewriting their meaning", () => {
  expect(parseReportDocument(legacy)).toEqual(legacy);
  expect(parseReportDocument(assessed())).toEqual(assessed());
});

it("preserves the legacy requirement markup and association-only wording", () => {
  expect(render(legacy)).toBe(
    '<details><summary>Question and report requirements</summary><p class="desk-help">Evidence links are not proof that a requirement is fully satisfied.</p><ul><li><strong>Compare approaches</strong> — Unresolved</li><li><strong>Assess costs</strong> — Evidence linked; completeness not established</li></ul></details>',
  );
});

it("shows recorded v2 assessments with reasons, criteria and supporting findings", () => {
  const html = render(assessed())!;
  expect(html).toContain("Requirement coverage (2)");
  expect(html).toContain("<strong>Assess costs</strong> — Established");
  expect(html).toContain("<strong>Compare approaches</strong> — Not assessed");
  expect(html).toContain("Research dimensions (1)");
  expect(html).toContain("Operating costs</strong> — Verified coverage");
  expect(html).toContain(
    "Cost criterion was reviewed against verified findings.",
  );
  expect(html).toContain("Planned criteria (1)");
  expect(html).toContain("Verified evidence establishes the cost criterion.");
  expect(html).toContain("Supporting verified findings (1)");
  expect(html).toContain("Verified statement.");
  expect(html).toContain("Source independence: unknown.");
  expect(html).not.toContain("Evidence linked; completeness not established");
  expect(html).not.toContain("<details open");
});

it("renders report-scoped provenance and unresolved conflicts without overstating them", () => {
  const document = provenanceReport();
  const html = render(document, [
    { id: document.findings[0]!.sourceIds[0]!, title: "Source Alpha" },
    { id: document.findings[1]!.sourceIds[0]!, title: "Source Beta" },
  ])!;
  expect(html).toContain("Observed source relationships (1)");
  expect(html).toContain("Source Alpha ↔ Source Beta (doi:10.1234/example)");
  expect(html).toContain("Potential disagreements (1)");
  expect(html).toContain("Potential disagreement · unresolved");
  expect(html).toContain("not confirmed or adjudicated contradictions");
  expect(html).toContain("A second verified statement that may disagree.");
  expect(html).toContain("Evidence sources: Source Alpha");
  expect(html).toContain("Evidence sources: Source Beta");
  expect(html).not.toContain("content hash");
});

it.each([
  ["partially_established", "Partially established"],
  ["not_established", "Not established"],
  ["not_assessed", "Not assessed"],
] as const)(
  "displays requirement outcome %s without inferring it from provenance links",
  (outcome, label) => {
    const document = assessed();
    const row = document.requirementOutcomes[1]!;
    row.outcome = outcome;
    if (outcome === "not_assessed") row.claimIds = [];
    const html = render(document)!;
    // The unchanged legacy requirements array still says addressed.
    expect(html).toContain(`<strong>Assess costs</strong> — ${label}`);
    expect(html).not.toContain("Evidence linked; completeness not established");
  },
);

it.each([
  ["not_started", "Not started"],
  ["searching", "Searching"],
  ["evidence_found", "Evidence found"],
  ["unresolved", "Unresolved"],
  ["blocked", "Blocked"],
] as const)(
  "keeps dimension %s distinct from verified coverage",
  (status, label) => {
    const document = assessed();
    document.dimensions[0]!.status = status;
    document.requirementOutcomes[1]!.outcome = "not_established";
    const html = render(document)!;
    expect(html).toContain(`Operating costs</strong> — ${label}`);
    expect(html).not.toContain(" — Verified coverage");
  },
);

it("shows empty assessed dimensions without inventing coverage", () => {
  const document = assessed();
  document.dimensions = [];
  document.requirementOutcomes = document.requirementOutcomes.map((row) => ({
    ...row,
    outcome: "not_assessed",
    dimensionIds: [],
    claimIds: [],
  }));
  expect(render(document)).toContain("No assessed dimensions were recorded.");
});

it("fails closed for malformed, unsupported or dangling assessment documents", () => {
  const dangling = assessed();
  dangling.dimensions[0]!.claimIds = ["00000000-0000-4000-8000-000000000999"];
  for (const value of [
    null,
    undefined,
    {},
    { ...legacy, version: 3 },
    { ...assessed(), assessmentVersion: "future" },
    dangling,
    { ...assessed(), quality: { ...legacy.quality, status: "answered" } },
  ]) {
    expect(parseReportDocument(value)).toBeNull();
    expect(render(value)).toBeNull();
  }
});

it("renders recorded assessment text as text rather than HTML", () => {
  const document = assessed();
  document.dimensions[0]!.reason = "<script>unsafe()</script>";
  const html = render(document)!;
  expect(html).toContain("&lt;script&gt;unsafe()&lt;/script&gt;");
  expect(html).not.toContain("<script>");
});

it("summarizes a v4 narrative as verified sentences while keeping provenance panels", () => {
  const html = render(narrativeReport())!;
  expect(html).toContain("Narrative composition (2 verified sentences)");
  expect(html).toContain(
    "3 proposed · 2 published · 1 withheld · 1 newly verified",
  );
  expect(html).toContain("<strong>Direct answer</strong> (1)");
  expect(html).toContain(
    "<strong>Research dimension</strong> — Operating costs (1)",
  );
  expect(html).toContain("there is no unverified connecting prose");
  expect(html).toContain("Observed source relationships (1)");
  expect(html).toContain("Potential disagreements (1)");
  expect(html).toContain("Requirement coverage (2)");
});

it("explains an uncomposed v4 narrative without inventing structure", () => {
  const html = render(narrativeReport(false))!;
  expect(html).toContain("Narrative composition (not composed)");
  expect(html).toContain(
    "Not enough active time remained to verify a narrative.",
  );
  expect(html).not.toContain("Direct answer");
});

it("fails closed for a v4 narrative that references unverified text", () => {
  const document = structuredClone(narrativeReport()) as Record<string, any>;
  document.narrative.blocks[0].sentences[0].claimId =
    "00000000-0000-4000-8000-000000000999";
  expect(parseReportDocument(document)).toBeNull();
});
