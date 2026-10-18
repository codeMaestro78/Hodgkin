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

export function formatRunDuration(milliseconds: number): string {
  const totalSeconds = Math.floor(Math.max(0, milliseconds) / 1000);
  return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
}

export function RunClock({
  startedAt,
  endedAt,
  processingMs,
  pausedMs,
  pausedSince,
}: {
  startedAt: string;
  endedAt?: string | undefined;
  processingMs?: number | null | undefined;
  pausedMs?: number | undefined;
  pausedSince?: string | null | undefined;
}) {
  const [now, setNow] = useState<number | null>(null);
  const paused = Boolean(pausedSince) && !endedAt;
  useEffect(() => {
    setNow(Date.now());
    // Keep the elapsed and approval-wait counters current while awaiting review.
    if (endedAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt, endedAt, pausedSince]);
  const end = endedAt ? Date.parse(endedAt) : now;
  const elapsedMs = end === null ? null : Math.max(0, end - Date.parse(startedAt));
  const approvalWaitMs =
    elapsedMs === null
      ? null
      : Math.max(0, pausedMs ?? 0) +
        (pausedSince
          ? Math.max(
              0,
              (end ?? Date.parse(startedAt)) -
                Math.max(Date.parse(pausedSince), Date.parse(startedAt)),
            )
          : 0);
  const activeMs = Number.isFinite(processingMs) ? Math.max(0, processingMs as number) : null;
  return (
    <span className="run-clock" data-paused={paused || undefined}>
      {elapsedMs === null || !Number.isFinite(elapsedMs) ? (
        "Elapsed time loading"
      ) : (
        <>
          {`Worker processing ${activeMs === null ? "not recorded" : formatRunDuration(activeMs)}`}
          {` · approval wait ${approvalWaitMs === null ? "—" : formatRunDuration(approvalWaitMs)}`}
          {` · elapsed ${elapsedMs === null ? "—" : formatRunDuration(elapsedMs)}`}
          {paused && (
            <span className="run-clock-paused"> · paused for approval</span>
          )}
        </>
      )}
    </span>
  );
}
