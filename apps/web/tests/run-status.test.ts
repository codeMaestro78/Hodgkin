import { afterEach, expect, it, vi } from "vitest";
import {
  modeDeadline,
  retryDeadline,
  runStage,
  statusForNodeStart,
  runFailure,
  modeAccessMessage,
  researchStartFailure,
  researchBudgetFailure,
  snapshotRefreshDelay,
  createSnapshotRefresh,
  isTransientSnapshotFailure,
  snapshotRetryDelay,
  SNAPSHOT_RECONNECTING_MESSAGE,
  runPhaseIndex,
  runPhases,
} from "../lib/run-status";

it("coalesces source bursts without delaying terminal snapshots", () => {
  expect(snapshotRefreshDelay("source.discovered")).toBe(5000);
  expect(snapshotRefreshDelay("run.failed")).toBe(0);
  expect(snapshotRefreshDelay("run.completed")).toBe(0);
  expect(snapshotRefreshDelay("node.started")).toBe(1000);
});

it("enforces a five-second minimum between full snapshots", () => {
  expect(snapshotRefreshDelay("node.started", 10_000, 14_000)).toBe(1000);
  expect(snapshotRefreshDelay("node.started", 10_000, 12_000)).toBe(3000);
  expect(snapshotRefreshDelay("source.discovered", 10_000, 15_000)).toBe(5000);
  expect(snapshotRefreshDelay("run.completed", 10_000, 10_001)).toBe(0);
});

it("retries transient snapshot outages without treating them as run failures", () => {
  expect(isTransientSnapshotFailure(503)).toBe(true);
  expect(isTransientSnapshotFailure(504)).toBe(true);
  expect(isTransientSnapshotFailure(404)).toBe(false);
  expect(snapshotRetryDelay(1)).toBe(1000);
  expect(snapshotRetryDelay(2)).toBe(2000);
  expect(snapshotRetryDelay(8)).toBe(10000);
  expect(SNAPSHOT_RECONNECTING_MESSAGE).toContain("may still be running");
  expect(SNAPSHOT_RECONNECTING_MESSAGE).toContain("reconnecting");
});

afterEach(() => vi.useRealTimers());

it("preempts a pending source refresh for a stage without duplicate requests", () => {
  vi.useFakeTimers();
  const load = vi.fn();
  const refresh = createSnapshotRefresh(load);
  for (let i = 0; i < 20; i++) refresh.schedule(1500);
  vi.advanceTimersByTime(100);
  expect(load).not.toHaveBeenCalled();
  refresh.schedule(0);
  vi.advanceTimersByTime(0);
  expect(load).toHaveBeenCalledTimes(1);
  expect(refresh.scheduled).toBe(false);
  vi.advanceTimersByTime(2000);
  expect(load).toHaveBeenCalledTimes(1);
});

it("does not postpone urgent refreshes and cancels on route cleanup", () => {
  vi.useFakeTimers();
  const load = vi.fn();
  const refresh = createSnapshotRefresh(load);
  refresh.schedule(0);
  refresh.schedule(1500);
  vi.advanceTimersByTime(0);
  expect(load).toHaveBeenCalledTimes(1);
  refresh.schedule(1000);
  refresh.cancel();
  vi.advanceTimersByTime(2000);
  expect(load).toHaveBeenCalledTimes(1);
});

it("never labels a terminal error as queued", () => {
  expect(runStage("failed")).toBe("Research failed");
  expect(runStage("cancelled")).toBe("Research stopped");
});
it("explains a time limit without an opaque code", () => {
  expect(runFailure("wall_clock_limit_exceeded")).toContain(
    "active-time limit",
  );
});
it("explains when a Deep writer response hit its output ceiling", () => {
  expect(runFailure("writer_output_limit_reached")).toContain("output limit");
  expect(runFailure("writer_output_limit_reached")).toContain(
    "collected sources remain available",
  );
});
it("explains Deep mode access from server-owned plan modes", () => {
  expect(modeAccessMessage("deep", ["focused", "balanced"])).toContain(
    "Investigator plan",
  );
  expect(modeAccessMessage("deep", ["focused", "balanced"])).toContain(
    "Focused and Balanced",
  );
  expect(modeAccessMessage("deep", ["focused", "balanced", "deep"])).toBeNull();
  expect(modeAccessMessage("deep", undefined)).toBeNull();
});
it("turns a server mode denial into a specific upgrade message", () => {
  expect(
    researchStartFailure(
      403,
      "research mode is not available on this plan",
      "deep",
      ["focused", "balanced"],
    ),
  ).toContain("Investigator plan");
  expect(
    researchStartFailure(
      403,
      { message: "Research mode is not available on this plan" },
      "deep",
    ),
  ).toContain("Upgrade to Investigator");
  expect(
    researchStartFailure(403, "authentication required", "deep"),
  ).toBeNull();
});

it("recognizes only the structured insufficient-research-units response", () => {
  expect(
    researchBudgetFailure(402, {
      message: "insufficient research units",
      requiredUnits: 2,
      availableUnits: 0,
      periodEnd: "2026-11-19T00:00:00Z",
    }),
  ).toEqual({
    requiredUnits: 2,
    availableUnits: 0,
    periodEnd: "2026-11-19T00:00:00Z",
  });
  expect(researchBudgetFailure(402, "payment required")).toBeNull();
  expect(
    researchBudgetFailure(402, { message: "billing configuration unavailable" }),
  ).toBeNull();
  expect(
    researchBudgetFailure(403, { message: "insufficient research units" }),
  ).toBeNull();
});
it.each([
  [6, 180_000],
  [12, 300_000],
  [20, 600_000],
])("keeps mode %i bounded at %i", (calls, ms) => {
  expect(modeDeadline(calls)).toBe(ms);
});

it("maps every recorded status to an honest progress phase", () => {
  expect(runPhases).toHaveLength(5);
  expect(runPhaseIndex("awaiting_approval")).toBe(0);
  expect(runPhaseIndex("reflecting")).toBe(runPhaseIndex("researching"));
  expect(runPhaseIndex("verifying")).toBe(2);
  expect(runPhaseIndex("completed")).toBe(4);
  for (const status of ["queued", "failed", "cancelled"])
    expect(runPhaseIndex(status)).toBe(-1);
});

it.each([
  ["intake", "planning"],
  ["planner", "planning"],
  ["planner_delta", "planning"],
  ["research_worker", "researching"],
  ["research_task", "researching"],
  ["assess_evidence", "reflecting"],
  ["reflector", "reflecting"],
  ["verifier", "verifying"],
  ["synthesizer", "writing"],
  ["unknown", null],
])("maps recorded node start %s to status %s", (nodeId, status) => {
  expect(statusForNodeStart(nodeId)).toBe(status);
});

it.each([
  ["focused", 180_000],
  ["balanced", 300_000],
  ["deep", 600_000],
] as const)(
  "uses persisted %s mode rather than a small call budget",
  (mode, deadline) => {
    expect(
      retryDeadline({
        mode,
        modePolicyVersion: "research-mode-policy-v1",
        budget: { maxSearchCalls: 2 },
      }),
    ).toBe(deadline);
  },
);

it.each([60_000, 90_000, 900_000])(
  "preserves recorded retry limit %i without raising it",
  (maxWallClockMs) => {
    expect(
      retryDeadline({
        mode: "deep",
        modePolicyVersion: "research-mode-policy-v1",
        budget: { maxSearchCalls: 20, maxWallClockMs },
      }),
    ).toBe(maxWallClockMs);
  },
);

it("uses the legacy call-derived deadline only when persisted policy is absent", () => {
  expect(retryDeadline({ budget: { maxSearchCalls: 2 } })).toBe(120_000);
  expect(
    retryDeadline({
      mode: null,
      modePolicyVersion: null,
      budget: { maxSearchCalls: 12 },
    }),
  ).toBe(300_000);
  expect(retryDeadline({ mode: "deep", budget: { maxSearchCalls: 6 } })).toBe(
    180_000,
  );
  expect(
    retryDeadline({
      mode: "deep",
      modePolicyVersion: "future-policy",
      budget: { maxSearchCalls: 6 },
    }),
  ).toBe(180_000);
  expect(
    retryDeadline({
      mode: "deep",
      modePolicyVersion: "future-policy",
      budget: { maxSearchCalls: 6, maxWallClockMs: 45_000 },
    }),
  ).toBe(45_000);
});
