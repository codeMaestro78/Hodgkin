import { describe, expect, it } from "vitest";
import { readingMinutes, reportSections } from "../lib/report-presentation";

describe("report presentation", () => {
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
