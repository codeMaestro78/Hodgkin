"use client";
import { useEffect, useState } from "react";

export function RunClock({
  startedAt,
  endedAt,
}: {
  startedAt: string;
  endedAt?: string | undefined;
}) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    if (endedAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [startedAt, endedAt]);
  const end = endedAt ? Date.parse(endedAt) : now;
  const seconds =
    end === null
      ? null
      : Math.max(0, Math.floor((end - Date.parse(startedAt)) / 1000));
  return (
    <span className="run-clock">
      {seconds === null || !Number.isFinite(seconds)
        ? "Elapsed time loading"
        : `${Math.floor(seconds / 60)}m ${seconds % 60}s ${endedAt ? "total" : "elapsed"}`}
    </span>
  );
}
