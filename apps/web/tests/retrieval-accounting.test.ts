import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RetrievalAccountingPanel } from "../app/components/retrieval-accounting";
import type { RunInsights } from "../app/components/research-insights";

const accounting: NonNullable<RunInsights["retrievalAccounting"]> = {
  schemaVersion: "1.1",
  providers: [
    {
      provider: "openalex",
      searchCalls: 1,
      discovered: 6,
      shortlisted: 2,
      excluded: 4,
      duplicateWork: 1,
      unavailable: 1,
      policyVersions: ["academic-lexical-topk-v1"],
      countsComplete: true,
      extractedSources: 2,
      citedInVerifiedFinding: 1,
    },
    {
      provider: "tavily",
      searchCalls: 1,
      discovered: null,
      shortlisted: null,
      excluded: null,
      duplicateWork: null,
      unavailable: null,
      policyVersions: [],
      countsComplete: false,
      extractedSources: 0,
      citedInVerifiedFinding: 0,
    },
  ],
  extractionCalls: 2,
  extractionOutcomes: {
    succeeded: 1,
    failed: 1,
    uncertain: 0,
    pending: 0,
    other: 0,
  },
  extractedSources: 2,
  citedInVerifiedFinding: 1,
  citationChecks: 2,
  exactSpanVerifiedCitations: 1,
  semanticReviewOutcomes: {
    supports: 1,
    partially_supports: 0,
    contradicts: 0,
    unrelated: 0,
    notRecorded: 1,
  },
  publishedClaims: 1,
  answerUsefulness: "not_assessed",
  dimensionRelevance: "not_assessed",
  sourceIndependence: "not_assessed",
};

describe("retrieval accounting panel", () => {
  it("shows measured lifecycle counts and keeps missing measures explicit", () => {
    const html = renderToStaticMarkup(
      createElement(RetrievalAccountingPanel, { accounting }),
    );
    expect(html).toContain("Discovery and evidence accounting");
    expect(html).toContain("OpenAlex");
    expect(html).toContain("6 discovered");
    expect(html).toContain("2 shortlisted");
    expect(html).toContain("4 excluded");
    expect(html).toContain("Tavily: discovery counts not recorded");
    expect(html).toContain('aria-label="Source lifecycle summary"');
    expect(html).toContain("Discovered records</dt><dd>Not recorded");
    expect(html).toContain("Shortlisted records</dt><dd>Not recorded");
    expect(html).toContain("Discovery totals count provider records, not distinct works");
    expect(html).toContain("2 extraction calls");
    expect(html).toContain("2 sources extracted");
    expect(html).toContain("1 source cited in verified findings");
    expect(html).toContain("Extraction outcomes: 1 succeeded, 1 failed");
    expect(html).toContain("Citation checks: 2; exact spans verified: 1");
    expect(html).toContain("Semantic review: 1 supported");
    expect(html).toContain("Answer usefulness: not assessed");
    expect(html).toContain("Dimension relevance: not assessed");
    expect(html).toContain("Source independence: not assessed");
  });

  it("shows recorded discovery totals only when every provider is complete", () => {
    const complete = {
      ...accounting,
      providers: [accounting.providers[0]],
    } as typeof accounting;
    const html = renderToStaticMarkup(
      createElement(RetrievalAccountingPanel, { accounting: complete }),
    );
    expect(html).toContain("Discovered records</dt><dd>6</dd>");
    expect(html).toContain("Shortlisted records</dt><dd>2</dd>");
  });

  it("renders nothing for historical runs without the accounting projection", () => {
    expect(
      renderToStaticMarkup(
        createElement(RetrievalAccountingPanel, { accounting: undefined }),
      ),
    ).toBe("");
  });

  it("labels an immutable report-version snapshot separately from live run activity", () => {
    const html = renderToStaticMarkup(
      createElement(RetrievalAccountingPanel, {
        accounting,
        publishedSnapshot: true,
      }),
    );
    expect(html).toContain("Frozen with this published report version");
    expect(html).not.toContain("not a frozen report snapshot");
  });
});
