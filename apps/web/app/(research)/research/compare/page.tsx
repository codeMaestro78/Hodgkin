"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ComparedReportListSchema,
  ReportComparisonRequestSchema,
  ReportComparisonSchema,
  UuidSchema,
} from "@research/contracts";
import type { z } from "zod";
import { WorkspaceShell } from "../../../components/workspace-shell";
import {
  Alert,
  Button,
  Empty,
  Skeleton,
} from "../../../components/workbench-ui";
import "../../../comparison.css";

type Report = z.infer<typeof ComparedReportListSchema>["reports"][number];
type Comparison = z.infer<typeof ReportComparisonSchema>;

export default function ComparePage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [result, setResult] = useState<Comparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const active = useRef<AbortController | null>(null);
  const more = useRef<AbortController | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const requestedLeft = UuidSchema.safeParse(query.get("leftReportId"));
    const requestedRight = UuidSchema.safeParse(query.get("rightReportId"));
    if (requestedLeft.success) setLeft(requestedLeft.data);
    if (requestedRight.success) setRight(requestedRight.data);
    return () => {
      active.current?.abort();
      more.current?.abort();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetch("/api/research/reports", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Reports couldn’t be loaded. Try again.");
        const data = ComparedReportListSchema.parse(await response.json());
        if (controller.signal.aborted) return;
        setReports(data.reports);
        setCursor(data.nextCursor);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Reports couldn’t be loaded. Try again.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [revision]);

  async function loadMore() {
    if (!cursor || loadingMore) return;
    const controller = new AbortController();
    more.current = controller;
    setLoadingMore(true);
    setError("");
    try {
      const response = await fetch(
        `/api/research/reports?after=${encodeURIComponent(cursor)}`,
        { signal: controller.signal, cache: "no-store" },
      );
      if (!response.ok) throw new Error();
      const data = ComparedReportListSchema.parse(await response.json());
      if (controller.signal.aborted) return;
      setReports((previous) => [
        ...new Map(
          [...previous, ...data.reports].map((item) => [item.id, item]),
        ).values(),
      ]);
      setCursor(data.nextCursor);
    } catch {
      if (!controller.signal.aborted)
        setError("More reports couldn’t be loaded. Try again.");
    } finally {
      if (!controller.signal.aborted) setLoadingMore(false);
    }
  }

  function select(side: "left" | "right", value: string) {
    active.current?.abort();
    setBusy(false);
    setResult(null);
    setError("");
    if (side === "left") setLeft(value);
    else setRight(value);
  }

  async function compare() {
    const payload = ReportComparisonRequestSchema.safeParse({
      leftReportId: left,
      rightReportId: right,
    });
    if (!payload.success || busy) return;
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setResult(null);
    setError("");
    try {
      const response = await fetch("/api/research/reports/compare", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload.data),
        signal: controller.signal,
      });
      if (!response.ok)
        throw new Error(
          response.status === 404
            ? "One of these reports is unavailable to your account. Choose another report."
            : "The comparison couldn’t be completed. Try again.",
        );
      const data = ReportComparisonSchema.parse(await response.json());
      if (!controller.signal.aborted) setResult(data);
    } catch (cause) {
      if (!controller.signal.aborted)
        setError(
          cause instanceof Error ? cause.message : "Comparison unavailable.",
        );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return (
    <WorkspaceShell title="Compare reports">
      <div className="report-comparison">
        <header>
          <h1>See what changed.</h1>
          <p>
            Compare two published report versions and follow the evidence behind
            their findings.
          </p>
        </header>
        {error ? (
          <Alert>
            {error}{" "}
            <Button
              variant="outline"
              onClick={() => setRevision((value) => value + 1)}
            >
              Reload reports
            </Button>
          </Alert>
        ) : null}
        {loading ? (
          <div role="status" aria-label="Loading reports">
            <Skeleton />
            <Skeleton />
          </div>
        ) : reports.length === 0 && !left ? (
          <Empty title="Publish a report to start comparing">
            <Link href="/research">Start research</Link>
          </Empty>
        ) : (
          <>
            <form
              className="comparison-controls"
              onSubmit={(event) => {
                event.preventDefault();
                void compare();
              }}
            >
              {(["left", "right"] as const).map((side) => {
                const value = side === "left" ? left : right;
                return (
                  <label key={side}>
                    {side === "left" ? "Earlier report" : "Later report"}
                    <select
                      value={value}
                      onChange={(event) => select(side, event.target.value)}
                      required
                    >
                      <option value="">Choose a report</option>
                      {value &&
                      !reports.some((report) => report.id === value) ? (
                        <option value={value}>Selected report version</option>
                      ) : null}
                      {reports.map((report) => (
                        <option key={report.id} value={report.id}>
                          {report.title} — v{report.version}
                        </option>
                      ))}
                    </select>
                  </label>
                );
              })}
              <Button
                type="submit"
                disabled={!left || !right || left === right || busy}
              >
                {busy ? "Comparing…" : "Compare reports"}
              </Button>
            </form>
            {left && right && left === right ? (
              <p role="status">
                Choose two different report versions to compare.
              </p>
            ) : null}
            {cursor ? (
              <Button
                variant="outline"
                disabled={loadingMore}
                onClick={() => void loadMore()}
              >
                {loadingMore ? "Loading more…" : "Load more report choices"}
              </Button>
            ) : null}
          </>
        )}
        {busy ? (
          <p role="status">Comparing findings and preserved evidence…</p>
        ) : null}
        {result ? (
          <section className="comparison-result" aria-label="Report comparison">
            <div className="comparison-reports">
              {[result.left, result.right].map((report, index) => (
                <article key={`${index}-${report.id}`}>
                  <p>
                    {index === 0 ? "Earlier" : "Later"} · Version{" "}
                    {report.version}
                  </p>
                  <h2>{report.title}</h2>
                  <p>Answer quality: {report.quality.replaceAll("_", " ")}</p>
                  <Link
                    href={`/research/${report.runId}?reportVersion=${report.version}`}
                  >
                    Open this report version
                  </Link>
                </article>
              ))}
            </div>
            <div className="comparison-counts">
              <span>
                <strong>{result.added.length}</strong> added findings
              </span>
              <span>
                <strong>{result.removed.length}</strong> removed findings
              </span>
              <span>
                <strong>{result.retained.length}</strong> retained findings
              </span>
              <span>
                <strong>{result.sources.sharedUrls}</strong> shared source URLs
              </span>
            </div>
            <div className="comparison-limitations">
              {result.limitations.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </div>
            {result.findingsAvailable ? (
              <>
                <div className="comparison-findings">
                  {[
                    {
                      title: "Added findings",
                      findings: result.added,
                      report: result.right,
                    },
                    {
                      title: "Removed findings",
                      findings: result.removed,
                      report: result.left,
                    },
                  ].map(({ title, findings, report }) => (
                    <section key={title}>
                      <h2>{title}</h2>
                      {findings.length ? (
                        <ul>
                          {findings.map((finding) => (
                            <li key={finding.id}>
                              <p>{finding.text}</p>
                              <small>
                                {finding.section} · {finding.citationIds.length}{" "}
                                recorded citations
                              </small>
                              <Link
                                href={`/research/${report.runId}?reportVersion=${report.version}#report-article`}
                              >
                                Inspect in report
                              </Link>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p>No literal finding changes in this direction.</p>
                      )}
                    </section>
                  ))}
                </div>
                {result.retained.length ? (
                  <details>
                    <summary>
                      {result.retained.length} retained findings
                    </summary>
                    <ul>
                      {result.retained.map((finding) => (
                        <li
                          key={`${finding.leftFindingId}-${finding.rightFindingId}`}
                        >
                          {finding.text}
                          <small>
                            {finding.sourceEvidenceChanged
                              ? "Linked source evidence changed"
                              : "Linked source URLs and content match"}
                          </small>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </>
            ) : null}
            <details>
              <summary>Report text diff</summary>
              {result.textDiff.status === "size_limit" ? (
                <p>
                  These reports exceed the text comparison limit. Open each
                  report version to inspect the full text.
                </p>
              ) : result.textDiff.unified ? (
                <pre tabIndex={0} aria-label="Report text changes">
                  {result.textDiff.unified}
                </pre>
              ) : (
                <p>The report text is identical.</p>
              )}
            </details>
          </section>
        ) : null}
      </div>
    </WorkspaceShell>
  );
}
