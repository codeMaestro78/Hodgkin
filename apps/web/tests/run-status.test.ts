import { afterEach, expect, it, vi } from "vitest";
import {
  modeDeadline,
  runStage,
  runFailure,
  snapshotRefreshDelay,
  createSnapshotRefresh,
} from "../lib/run-status";

it("coalesces source bursts without delaying terminal snapshots", () => {
  expect(snapshotRefreshDelay("source.discovered")).toBe(1500);
  expect(snapshotRefreshDelay("run.failed")).toBe(0);
  expect(snapshotRefreshDelay("run.completed")).toBe(0);
  expect(snapshotRefreshDelay("node.started")).toBe(0);
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
it.each([
  [6, 180_000],
  [12, 300_000],
  [20, 600_000],
])("keeps mode %i bounded at %i", (calls, ms) => {
  expect(modeDeadline(calls)).toBe(ms);
});
