import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  BudgetSchema,
  CreateResearchRunRequestSchema,
  CreateResearchRunResponseSchema,
  FollowupRequestSchema,
  ResearchModeSchema,
  ResearchModeResolutionSchema,
  ResearchRunProjectionSchema,
  ResearchStateSchema,
  RunInsightsSchema,
  WatermarkedRunProjectionSchema,
} from "../src/index";

const state = JSON.parse(
  readFileSync(
    new URL("../fixtures/valid/research-state.json", import.meta.url),
    "utf8",
  ),
);
const request = { question: "Compare research approaches" };
const followup = { ...request, idempotencyKey: "mode-fixture-123456" };
const metadata = {
  mode: "deep",
  modePolicyVersion: "research-mode-policy-v1",
  modeResolution: "explicit",
};
const projection = Object.fromEntries(
  Object.keys(ResearchRunProjectionSchema.shape).map((key) => [
    key,
    state[key],
  ]),
);
Object.assign(projection, {
  sourceCount: 0,
  evidenceClaimCount: 0,
  gapCount: 0,
});
// Missing properties must be genuinely absent, just as with historical API responses.
for (const key of Object.keys(metadata)) delete projection[key];
const response = { runId: state.runId, status: "queued" };
const insights = {
  schemaVersion: state.schemaVersion,
  tasks: [],
  providerCalls: [],
  gaps: [],
  parentReportId: null,
  parentRunId: null,
  followupRuns: [],
  reportVersions: [],
};

describe("research mode compatibility", () => {
  it.each(["focused", "balanced", "deep"])(
    "accepts explicit %s without synthesizing policy",
    (mode) => {
      expect(ResearchModeSchema.parse(mode)).toBe(mode);
      expect(
        CreateResearchRunRequestSchema.parse({ ...request, mode }).mode,
      ).toBe(mode);
      expect(FollowupRequestSchema.parse({ ...followup, mode }).mode).toBe(
        mode,
      );
    },
  );

  it.each(["Deep", "unknown", "", 1])("rejects invalid mode %s", (mode) => {
    expect(
      CreateResearchRunRequestSchema.safeParse({ ...request, mode }).success,
    ).toBe(false);
    expect(FollowupRequestSchema.safeParse({ ...followup, mode }).success).toBe(
      false,
    );
  });

  it("preserves missing create and follow-up mode without selecting a default", () => {
    expect(CreateResearchRunRequestSchema.parse(request)).not.toHaveProperty(
      "mode",
    );
    expect(
      CreateResearchRunRequestSchema.parse({ ...request, mode: null }).mode,
    ).toBeNull();
    expect(FollowupRequestSchema.parse(followup)).not.toHaveProperty("mode");
    expect(
      FollowupRequestSchema.safeParse({ ...followup, mode: null }).success,
    ).toBe(false);
  });

  it.each(["policyVersion", "modePolicyVersion", "modeResolution"])(
    "rejects client-selected %s",
    (key) => {
      expect(
        CreateResearchRunRequestSchema.safeParse({
          ...request,
          [key]: "explicit",
        }).success,
      ).toBe(false);
      expect(
        FollowupRequestSchema.safeParse({ ...followup, [key]: "explicit" })
          .success,
      ).toBe(false);
    },
  );

  it.each([
    ["state", ResearchStateSchema, state],
    ["projection", ResearchRunProjectionSchema, projection],
    ["response", CreateResearchRunResponseSchema, response],
    ["insights", RunInsightsSchema, insights],
  ] as const)(
    "keeps %s compatible with historical and resolved metadata",
    (_name, schema, fixture) => {
      expect(schema.safeParse(fixture).success).toBe(true);
      expect(schema.safeParse({ ...fixture, ...metadata }).success).toBe(true);
      expect(
        schema.safeParse({
          ...fixture,
          mode: null,
          modePolicyVersion: null,
          modeResolution: null,
        }).success,
      ).toBe(true);
      expect(
        schema.safeParse({
          ...fixture,
          ...metadata,
          modeResolution: "legacy-inferred",
        }).success,
      ).toBe(true);
      expect(
        schema.safeParse({
          ...fixture,
          ...metadata,
          modeResolution: "inferred",
        }).success,
      ).toBe(false);
    },
  );

  it("preserves mode metadata through the watermarked projection", () => {
    const parsed = WatermarkedRunProjectionSchema.parse({
      run: { ...projection, ...metadata },
      snapshotSequence: 0,
    });
    expect(parsed.run.mode).toBe("deep");
    expect(ResearchModeResolutionSchema.options).toEqual([
      "explicit",
      "legacy-inferred",
    ]);
  });
});

describe("separate optional budget ceilings", () => {
  it("preserves legacy defaults and leaves new ceilings absent", () => {
    const {
      maxSearchCalls,
      maxBrowserSessions,
      maxReflectionRounds,
      ...budget
    } = state.budget;
    const parsed = BudgetSchema.parse(budget);
    expect(parsed).toMatchObject({
      maxSearchCalls: 12,
      maxBrowserSessions: 0,
      maxReflectionRounds: 1,
    });
    expect(parsed).not.toHaveProperty("maxProviderOperations");
    expect(parsed).not.toHaveProperty("maxSources");
    expect(CreateResearchRunRequestSchema.parse(request)).not.toHaveProperty(
      "budgetOverrides",
    );
  });

  it.each([
    [2, 1],
    [50, 20],
  ])(
    "accepts operations %s / sources %s",
    (maxProviderOperations, maxSources) => {
      const budgetOverrides = { maxProviderOperations, maxSources };
      expect(
        BudgetSchema.safeParse({ ...state.budget, ...budgetOverrides }).success,
      ).toBe(true);
      // A reduced budget must not relabel the selected mode.
      expect(
        CreateResearchRunRequestSchema.parse({
          ...request,
          mode: "deep",
          budgetOverrides,
        }).mode,
      ).toBe("deep");
    },
  );

  it.each([
    ["maxProviderOperations", 1],
    ["maxProviderOperations", 51],
    ["maxProviderOperations", 2.5],
    ["maxSources", 0],
    ["maxSources", 21],
    ["maxSources", 1.5],
    ["maxProviderOperations", null],
    ["maxSources", null],
  ])("rejects invalid %s = %s", (key, value) => {
    expect(
      BudgetSchema.safeParse({ ...state.budget, [key]: value }).success,
    ).toBe(false);
    expect(
      CreateResearchRunRequestSchema.safeParse({
        ...request,
        budgetOverrides: { [key]: value },
      }).success,
    ).toBe(false);
  });
});
