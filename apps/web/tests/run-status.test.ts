import { expect, it } from "vitest";
import {
  modeDeadline,
  runStage,
  runFailure,
  snapshotRefreshDelay,
} from "../lib/run-status";

it("coalesces source bursts without delaying terminal snapshots", () => {
  expect(snapshotRefreshDelay("source.discovered")).toBe(1500);
  expect(snapshotRefreshDelay("run.failed")).toBe(0);
  expect(snapshotRefreshDelay("run.completed")).toBe(0);
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
it.each([
  [6, 180_000],
  [12, 300_000],
  [20, 600_000],
])("keeps mode %i bounded at %i", (calls, ms) => {
  expect(modeDeadline(calls)).toBe(ms);
});
