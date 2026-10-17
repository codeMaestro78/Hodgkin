import { describe, expect, it } from "vitest";
import { methodSummary, providerLabel } from "../lib/research-method";

const questions = [
  { id: "q1", question: "First?", status: "complete" },
  { id: "q2", question: "Second?", status: "complete" },
];

describe("methodSummary", () => {
  it("counts unique sources per question and provider", () => {
    const summary = methodSummary(
      [
        {
          id: "a",
          title: "A",
          url: "https://a.test",
          provider: "tavily",
          discoveryPaths: [
            { subQuestionId: "q1", provider: "tavily" },
            { subQuestionId: "q1", provider: "tavily" },
            { subQuestionId: "q2", provider: "openalex" },
          ],
        },
        {
          id: "b",
          title: "B",
          url: "https://b.test",
          provider: "openalex",
          discoveryPaths: [{ subQuestionId: "q1", provider: "openalex" }],
        },
        { id: "c", title: "C", url: "https://c.test", provider: "exa" },
      ],
      questions,
    );
    expect(summary.providers).toEqual([
      { id: "openalex", label: "OpenAlex", count: 2 },
      { id: "exa", label: "Exa", count: 1 },
      { id: "tavily", label: "Tavily", count: 1 },
    ]);
    expect(summary.questions[0]?.sources.map((s) => s.id)).toEqual(["a", "b"]);
    expect(summary.questions[0]?.providers).toEqual([
      { id: "openalex", label: "OpenAlex", count: 1 },
      { id: "tavily", label: "Tavily", count: 1 },
    ]);
    expect(summary.questions[1]?.sources.map((s) => s.id)).toEqual(["a"]);
    expect(summary.unattributed).toBe(1);
  });

  it("treats paths to unknown questions as unattributed", () => {
    const summary = methodSummary(
      [
        {
          id: "a",
          title: "A",
          url: "https://a.test",
          provider: "tavily",
          discoveryPaths: [{ subQuestionId: "gone", provider: "tavily" }],
        },
      ],
      questions,
    );
    expect(summary.unattributed).toBe(1);
    expect(summary.questions.every((item) => item.sources.length === 0)).toBe(
      true,
    );
  });
});

it("labels providers readably", () => {
  expect(providerLabel("semantic_scholar")).toBe("Semantic Scholar");
  expect(providerLabel("new-index")).toBe("New index");
  expect(providerLabel("")).toBe("Unknown");
});
