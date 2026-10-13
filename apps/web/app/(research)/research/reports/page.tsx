"use client";
import Link from "next/link";
import { useDeferredValue, useEffect, useState } from "react";
import {
  WorkspaceShell,
  type HistoryRun,
} from "../../../components/workspace-shell";
import { dateLabel, Icon } from "../../../components/ui";
import {
  Alert,
  Button,
  Empty,
  Skeleton,
} from "../../../components/workbench-ui";

export default function ReportsPage() {
  const [runs, setRuns] = useState<HistoryRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [reload, setReload] = useState(0);
  const search = useDeferredValue(query.trim().toLowerCase());
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetch("/api/research/runs?reportsOnly=true", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Reports couldn’t be loaded. Try again.");
        const body = (await response.json()) as { runs: HistoryRun[] };
        setRuns(body.runs);
      })
      .catch((cause) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Reports unavailable.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [reload]);
  const visible = runs.filter((run) =>
    run.question.toLowerCase().includes(search),
  );
  return (
    <WorkspaceShell title="Reports">
      <div className="desk-library">
        <header>
          <h1>Your research, ready to revisit.</h1>
          <p>
            Search your 100 most recent completed reports. Original evidence
            stays connected to each brief.
          </p>
        </header>
        <label className="evidence-search">
          <Icon name="search" size={16} />
          <input
            type="search"
            aria-label="Search completed reports"
            placeholder="Find a completed report…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        {error ? (
          <Alert>
            {error}{" "}
            <Button
              variant="outline"
              onClick={() => setReload((value) => value + 1)}
            >
              Try again
            </Button>
          </Alert>
        ) : loading ? (
          <div role="status" aria-label="Loading reports">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </div>
        ) : visible.length ? (
          <ul className="desk-report-list">
            {visible.map((run) => (
              <li key={run.runId}>
                <Link href={`/research/${run.runId}`}>
                  <Icon name="book" size={20} />
                  <span>
                    <strong>{run.question}</strong>
                    <small>
                      {run.sourceCount} collected sources ·{" "}
                      {dateLabel(run.createdAt)}
                    </small>
                  </span>
                  <Icon name="arrow" size={17} />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            title={
              query
                ? "No matching reports"
                : "Your first brief starts with a question"
            }
          >
            {query ? (
              "Try another term or clear the search."
            ) : (
              <Link href="/research">Start new research</Link>
            )}
          </Empty>
        )}
      </div>
    </WorkspaceShell>
  );
}
