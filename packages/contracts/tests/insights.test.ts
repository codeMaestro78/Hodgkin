import { describe, expect, it } from "vitest";
import {
  ExecutionTaskSchema,
  FollowupRequestSchema,
  RunInsightsSchema,
} from "../src/index";

describe("evidence desk boundaries", () => {
  it("requires a meaningful question and bounds report versions", () => {
    const request = {
      question: "  Inspect conflicting evidence  ",
      idempotencyKey: "fixture-key-123456",
      reportVersion: 2,
    };
    expect(FollowupRequestSchema.parse(request).question).toBe(
      "Inspect conflicting evidence",
    );
    expect(
      FollowupRequestSchema.safeParse({ ...request, question: "   " }).success,
    ).toBe(false);
    expect(
      FollowupRequestSchema.safeParse({ ...request, reportVersion: 10001 })
        .success,
    ).toBe(false);
    expect(
      FollowupRequestSchema.safeParse({
        ...request,
        tenantId: "client-controlled",
      }).success,
    ).toBe(false);
  });

  it("represents skipped work without fabricated timestamps", () => {
    expect(
      ExecutionTaskSchema.parse({
        id: "00000000-0000-4000-8000-000000000001",
        nodeId: "research_worker",
        name: "Evidence collection",
        status: "skipped",
        attempt: 0,
        startedAt: null,
        completedAt: null,
        errorCode: null,
        sourceIds: [],
        dependsOn: [],
      }).startedAt,
    ).toBeNull();
  });

  it("rejects provider secrets in public snapshots", () => {
    const snapshot = {
      schemaVersion: "1.2",
      tasks: [],
      providerCalls: [],
      gaps: [],
      parentReportId: null,
      parentRunId: null,
      followupRuns: [],
      reportVersions: [],
    };
    expect(RunInsightsSchema.safeParse(snapshot).success).toBe(true);
    expect(
      RunInsightsSchema.safeParse({ ...snapshot, apiKey: "not-public" })
        .success,
    ).toBe(false);
  });

  it("accepts source-stage accounting without converting unknown quality into zero", () => {
    const snapshot = {
      schemaVersion: "1.4",
      tasks: [],
      providerCalls: [],
      gaps: [],
      parentReportId: null,
      parentRunId: null,
      followupRuns: [],
      reportVersions: [],
      retrievalAccounting: {
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
      },
    };
    expect(RunInsightsSchema.parse(snapshot).retrievalAccounting).toEqual(
      snapshot.retrievalAccounting,
    );
    expect(
      RunInsightsSchema.safeParse({
        ...snapshot,
        retrievalAccounting: {
          ...snapshot.retrievalAccounting,
          dimensionRelevance: 0,
        },
      }).success,
    ).toBe(false);
  });
});
