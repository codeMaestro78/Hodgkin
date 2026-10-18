import { describe, expect, it } from "vitest";
import {
  activeElapsedMs,
  formatRunDuration,
} from "../app/components/run-clock";

const start = Date.parse("2026-01-01T10:00:00Z");
const at = (seconds: number) => start + seconds * 1000;

describe("activeElapsedMs", () => {
  it("counts wall time when the run never waited", () => {
    expect(activeElapsedMs({ startedAt: start, end: at(90) })).toBe(90_000);
  });

  it("freezes while a plan decision is pending", () => {
    const waiting = { startedAt: start, pausedSince: at(20) };
    expect(activeElapsedMs({ ...waiting, end: at(20) })).toBe(20_000);
    expect(activeElapsedMs({ ...waiting, end: at(80) })).toBe(20_000);
    expect(activeElapsedMs({ ...waiting, end: at(600) })).toBe(20_000);
  });

  it("resumes after the decision without counting the closed wait", () => {
    // Waited 60s between t=20 and t=80, then ran 30 more seconds.
    expect(
      activeElapsedMs({ startedAt: start, end: at(110), pausedMs: 60_000 }),
    ).toBe(50_000);
  });

  it("combines closed waits with a second open wait", () => {
    expect(
      activeElapsedMs({
        startedAt: start,
        end: at(300),
        pausedMs: 60_000,
        pausedSince: at(200),
      }),
    ).toBe(140_000);
  });

  it("never goes negative on clock skew or bad input", () => {
    expect(
      activeElapsedMs({ startedAt: start, end: at(-5), pausedMs: 10_000 }),
    ).toBe(0);
    expect(
      activeElapsedMs({ startedAt: start, end: at(10), pausedSince: at(30) }),
    ).toBe(10_000);
    expect(
      activeElapsedMs({ startedAt: start, end: at(10), pausedMs: Number.NaN }),
    ).toBe(10_000);
  });
});

describe("formatRunDuration", () => {
  it("formats processing and wait durations independently", () => {
    expect(formatRunDuration(125_999)).toBe("2m 5s");
    expect(formatRunDuration(48_000)).toBe("0m 48s");
  });

  it("does not display negative durations", () => {
    expect(formatRunDuration(-1)).toBe("0m 0s");
  });
});
