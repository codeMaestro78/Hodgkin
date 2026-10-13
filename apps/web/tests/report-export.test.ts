import { expect, it } from "vitest";
import { reportExport } from "../lib/report-export";
it("exports the selected version with citations and honest verification/gap summaries", () => {
  const output = reportExport({
    originalQuestion: "Compare evidence",
    report: {
      version: 2,
      publishedAt: "2026-10-13",
      markdown:
        "## Findings\nEvidence [1]\n## Sources\n1. [Source](https://example.test)",
    },
    sources: [
      { id: "s", title: "Original source", url: "https://example.test" },
    ],
    claimChecks: [
      {
        claim: "Evidence is limited",
        status: "partially_supported",
        citations: [
          {
            sourceId: "s",
            quote: "Exact source passage",
            exactSpanVerified: true,
            verdict: "partially_supports",
          },
        ],
      },
    ],
    insights: {
      gaps: [
        {
          description: "Missing evidence",
          why: "A claim is unresolved",
          status: "open",
        },
      ],
    },
  });
  expect(output).toContain("Report version 2");
  expect(output).toContain("https://example.test");
  expect(output).toContain("Exact source passage");
  expect(output).toContain("partially supported");
  expect(output).toContain("Missing evidence");
  expect(output).not.toContain("confidence");
});
it("does not invent verification for old reports", () => {
  expect(
    reportExport({
      originalQuestion: "Old question",
      report: { version: 1, publishedAt: "old", markdown: "Old report" },
      sources: [],
    }),
  ).toContain("No claim checks were recorded");
});
