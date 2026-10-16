import { describe, expect, it } from "vitest";
import {
  answerSectionKind,
  followupSuggestions,
  hasNoVerifiedFindings,
  readingMinutes,
  reportDisplayMarkdown,
  reportSections,
} from "../lib/report-presentation";

describe("report presentation", () => {
  it("detects empty findings without hiding a populated structured report", () => {
    expect(hasNoVerifiedFindings({ findings: [] }, undefined)).toBe(true);
    expect(hasNoVerifiedFindings({ findings: [{}] }, [])).toBe(false);
    expect(hasNoVerifiedFindings(null, [{ publishedInReport: false }])).toBe(
      true,
    );
    expect(hasNoVerifiedFindings(null, [{ publishedInReport: true }])).toBe(
      false,
    );
    expect(hasNoVerifiedFindings(null, undefined)).toBe(false);
  });

  it("hides the legacy generated ratio while preserving findings and domain equations", () => {
    const equation = "$$\nE = mc^2\n$$";
    const markdown = `## Summary\nSupported finding. [1]\n\n$$\n\\text{published share} = \\frac{2}{3} \\approx 66.7\\%\n$$\n\n${equation}`;
    const shown = reportDisplayMarkdown(markdown);
    expect(shown).not.toContain("published share");
    expect(shown).toContain("Supported finding. [1]");
    expect(shown).toContain(equation);
    expect(reportDisplayMarkdown(shown)).toBe(shown);
  });
  it("builds stable unique section ids and removes formatting", () => {
    expect(
      reportSections(
        "## **Decision**\n### [Evidence](https://example.com)\n## Decision",
      ),
    ).toEqual([
      { id: "report-section-0", title: "Decision" },
      { id: "report-section-1", title: "Evidence" },
      { id: "report-section-2", title: "Decision" },
    ]);
  });
  it("excludes fenced examples and source lists", () => {
    expect(
      reportSections(
        "```md\n## Not a heading\n```\n## Answer\n## Sources\n## Hidden",
      ),
    ).toEqual([{ id: "report-section-0", title: "Answer" }]);
  });
  it("supports tilde fences and empty reports", () => {
    expect(reportSections("~~~\n# Example\n~~~")).toEqual([]);
    expect(readingMinutes("")).toBe(1);
    expect(readingMinutes(Array(440).fill("word").join(" "))).toBe(2);
  });
});

describe("answerSectionKind", () => {
  it("classifies lead, limitation and method headings", () => {
    expect(answerSectionKind("Executive summary")).toBe("lead");
    expect(answerSectionKind("Direct answer")).toBe("lead");
    expect(answerSectionKind(" Limitations ")).toBe("limitations");
    expect(answerSectionKind("Methodology")).toBe("method");
    expect(answerSectionKind("Risks and limitations of evidence")).toBe("body");
  });
});

describe("followupSuggestions", () => {
  it("prefers open gap queries, then uncovered questions, deduplicated", () => {
    expect(
      followupSuggestions({
        gaps: [
          { suggestedQuery: "Find primary evidence  for X", status: "open" },
          { suggestedQuery: "Already investigating", status: "investigating" },
          { suggestedQuery: null, status: "open" },
        ],
        questionCoverage: [
          { text: "find primary evidence for x", status: "unresolved" },
          { text: "Covered question", status: "addressed" },
          { text: "What remains uncovered?", status: "unresolved" },
          { text: "Another open question?", status: "unresolved" },
        ],
      }),
    ).toEqual([
      "Find primary evidence for X",
      "What remains uncovered?",
      "Another open question?",
    ]);
  });

  it("returns nothing when no gap or uncovered question was recorded", () => {
    expect(followupSuggestions({})).toEqual([]);
  });
});
