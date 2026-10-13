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
});
