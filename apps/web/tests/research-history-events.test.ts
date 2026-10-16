import { expect, it, vi } from "vitest";
import {
  patchResearchHistory,
  publishResearchHistory,
  publishResearchHistorySnapshot,
  RESEARCH_HISTORY_EVENT,
  subscribeResearchHistorySnapshots,
  type ResearchHistorySnapshot,
} from "../lib/research-history-events";

const snapshot: ResearchHistorySnapshot = {
  runId: "run-a",
  status: "completed",
  sourceCount: 8,
};

it("publishes typed snapshots and unsubscribes cleanly", () => {
  const target = new EventTarget();
  const listener = vi.fn();
  const unsubscribe = subscribeResearchHistorySnapshots(listener, target);
  expect(publishResearchHistory(snapshot, target)).toBe(true);
  expect(listener).toHaveBeenCalledExactlyOnceWith(snapshot);
  unsubscribe();
  publishResearchHistorySnapshot(snapshot, target);
  expect(listener).toHaveBeenCalledTimes(1);
});

it("accepts reflecting snapshots from the existing run status contract", () => {
  expect(
    publishResearchHistory(
      { ...snapshot, status: "reflecting" },
      new EventTarget(),
    ),
  ).toBe(true);
});

it("ignores malformed events and rejects invalid publications", () => {
  const target = new EventTarget();
  const listener = vi.fn();
  const unsubscribe = subscribeResearchHistorySnapshots(listener, target);
  for (const detail of [
    null,
    {},
    { ...snapshot, sourceCount: -1 },
    { ...snapshot, sourceCount: 1.2 },
    { ...snapshot, sourceCount: Infinity },
    { ...snapshot, status: "invented" },
    { ...snapshot, runId: "" },
    { ...snapshot, token: "secret" },
  ]) {
    target.dispatchEvent(new CustomEvent(RESEARCH_HISTORY_EVENT, { detail }));
    expect(
      publishResearchHistorySnapshot(detail as ResearchHistorySnapshot, target),
    ).toBe(false);
  }
  target.dispatchEvent(new Event(RESEARCH_HISTORY_EVENT));
  expect(listener).not.toHaveBeenCalled();
  unsubscribe();
});

it("patches only matching entries while preserving metadata and order", () => {
  const first = {
    runId: "run-a",
    status: "researching",
    sourceCount: 2,
    question: "Question A",
    createdAt: "today",
  };
  const second = { ...first, runId: "run-b" };
  const history = [first, second];
  const patched = patchResearchHistory(history, snapshot);
  expect(patched).toEqual([{ ...first, ...snapshot }, second]);
  expect(patched[1]).toBe(second);
  expect(history[0]).toBe(first);
  expect(first.sourceCount).toBe(2);
  expect(patchResearchHistory(patched, snapshot)).toBe(patched);
  expect(patchResearchHistory(history, { ...snapshot, runId: "unknown" })).toBe(
    history,
  );
});

it("applies authoritative retry snapshots even if status/count moves backwards", () => {
  const history = [{ ...snapshot }];
  const retry = { ...snapshot, status: "queued" as const, sourceCount: 0 };
  expect(patchResearchHistory(history, retry)).toEqual([retry]);
  expect(
    patchResearchHistory(patchResearchHistory(history, retry), snapshot),
  ).toEqual([snapshot]);
});
