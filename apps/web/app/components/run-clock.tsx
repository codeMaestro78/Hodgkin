"use client";
import { useEffect, useState } from "react";

/**
 * Active run time: wall time minus every interval spent waiting for a plan
 * decision. `pausedMs` covers closed waits; `pausedSince` marks an open one.
 */
export function activeElapsedMs({
  startedAt,
  end,
  pausedMs = 0,
  pausedSince,
}: {
  startedAt: number;
  end: number;
  pausedMs?: number | undefined;
  pausedSince?: number | null | undefined;
}) {
  const open =
    pausedSince != null && Number.isFinite(pausedSince)
      ? Math.max(0, end - Math.max(pausedSince, startedAt))
      : 0;
  const paused = (Number.isFinite(pausedMs) ? Math.max(0, pausedMs) : 0) + open;
  return Math.max(0, end - startedAt - paused);
}

export function RunClock({
  startedAt,
  endedAt,
  pausedMs,
  pausedSince,
}: {
  startedAt: string;
  endedAt?: string | undefined;
  pausedMs?: number | undefined;
  pausedSince?: string | null | undefined;
}) {
  const [now, setNow] = useState<number | null>(null);
  const paused = Boolean(pausedSince) && !endedAt;
  useEffect(() => {
    setNow(Date.now());
    // A paused clock cannot change, so it doesn't need to tick.
    if (endedAt || pausedSince) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt, endedAt, pausedSince]);
  const end = endedAt ? Date.parse(endedAt) : now;
  const seconds =
    end === null
      ? null
      : Math.floor(
          activeElapsedMs({
            startedAt: Date.parse(startedAt),
            end,
            pausedMs,
            pausedSince: pausedSince ? Date.parse(pausedSince) : null,
          }) / 1000,
        );
  return (
    <span className="run-clock" data-paused={paused || undefined}>
      {seconds === null || !Number.isFinite(seconds) ? (
        "Elapsed time loading"
      ) : (
        <>
          {`${Math.floor(seconds / 60)}m ${seconds % 60}s ${endedAt ? "total" : "elapsed"}`}
          {paused && (
            <span className="run-clock-paused"> · paused for approval</span>
          )}
        </>
      )}
    </span>
  );
}
