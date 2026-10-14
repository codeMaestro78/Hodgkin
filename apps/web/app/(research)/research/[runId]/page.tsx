"use client";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import {
  readingMinutes,
  reportSections,
} from "../../../../lib/report-presentation";
import { useParams, useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import { reportExport } from "../../../../lib/report-export";
import {
  modeDeadline,
  runStage,
  runFailure,
  snapshotRefreshDelay,
} from "../../../../lib/run-status";
import remarkGfm from "remark-gfm";
import { WorkspaceShell } from "../../../components/workspace-shell";
import { RunClock } from "../../../components/run-clock";
import {
  Badge,
  Button,
  Empty,
  Skeleton,
} from "../../../components/workbench-ui";
import {
  ExecutionView,
  GapView,
  type RunInsights,
} from "../../../components/research-insights";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "../../../components/tabs";
import {
  useEntrance,
  useSlidingIndicator,
} from "../../../components/workspace-motion";
import {
  dateLabel,
  domain,
  Icon,
  safeUrl,
  Status,
} from "../../../components/ui";

type Source = {
  id: string;
  title: string;
  url: string;
  provider: string;
  sourceClass: string;
  assessment?: {
    publisher: string | null;
    publishedAt: string | null;
    retrievedAt: string;
    independenceGroup: string;
    sameMaterialCount: number;
    reasons: string[];
  };
  discoveryPaths?: { subQuestionId: string; provider: string; url: string }[];
};
type RunEvent = {
  sequence: number;
  type: string;
  label: string | null;
  occurredAt: string;
};
type Run = {
  runId: string;
  status: string;
  originalQuestion: string;
  approval?: {
    planId: string;
    state: "pending" | "approve" | "reject";
    questions: { id: string; question: string }[];
  } | null;
  sourceCount: number;
  sourceLimit?: number;
  errorCode: string | null;
  quickMode: boolean;
  createdAt: string;
  updatedAt?: string;
  insights?: RunInsights;
  claimChecks?: {
    id: string;
    claim: string;
    caveats: string[];
    status?: string;
    section?: string | null;
    method?: string;
    publishedInReport?: boolean;
    supportingSourceIds?: string[];
    contradictingSourceIds?: string[];
    citations: {
      id: string;
      sourceId: string;
      quote: string;
      exactSpanVerified: boolean;
      verdict: string;
      context?: string | null;
    }[];
  }[];
  budget: {
    maxSearchCalls: number;
    maxEstimatedCostUsd: number;
    maxWallClockMs?: number;
  };
  usage: { searchCalls: number };
  report: {
    id: string;
    version: number;
    markdown: string;
    publishedAt: string;
  } | null;
  sources: Source[];
  subQuestions: { id: string; question: string; status: string }[];
  events: RunEvent[];
};
type MarkdownNode = {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
  data?: { hProperties: { id: string } };
};
const terminal = ["failed", "completed", "cancelled"];
const phases = ["planning", "researching", "verifying", "writing", "completed"];
const labels = ["Plan", "Research", "Check", "Write", "Answer"];

function remarkCitations() {
  return (tree: MarkdownNode) => {
    let heading = 0;
    const visit = (node: MarkdownNode) => {
      if (node.type === "heading")
        node.data = { hProperties: { id: `report-section-${heading++}` } };
      if (!node.children || ["link", "code", "inlineCode"].includes(node.type))
        return;
      node.children = node.children.flatMap((child) => {
        if (child.type !== "text" || !child.value) {
          visit(child);
          return [child];
        }
        const parts: MarkdownNode[] = [];
        let end = 0;
        for (const match of child.value.matchAll(/\[(\d+)\]/g)) {
          if (match.index > end)
            parts.push({
              type: "text",
              value: child.value.slice(end, match.index),
            });
          parts.push({
            type: "link",
            url: "#source-" + match[1],
            children: [{ type: "text", value: match[1] ?? "" }],
          });
          end = match.index + match[0].length;
        }
        if (end < child.value.length)
          parts.push({ type: "text", value: child.value.slice(end) });
        return parts.length ? parts : [child];
      });
    };
    visit(tree);
  };
}

function referenceMap(markdown: string, sources: Source[]) {
  const section = markdown.split(/^## Sources\s*$/im)[1] ?? "";
  const result = new Map<number, Source>();
  for (const match of section.matchAll(
    /^\s*(\d+)\.\s+\[[^\n]*?\]\((https?:\/\/[^\s)]+)\)/gm,
  )) {
    const url = safeUrl(match[2] ?? "");
    const source = sources.find((item) => safeUrl(item.url) === url);
    if (source && url) result.set(Number(match[1]), source);
  }
  return result;
}

export default function LiveRunWorkspace() {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const approving = useRef(false);
  const [approvalDecision, setApprovalDecision] = useState<
    "approve" | "reject" | null
  >(null);
  const [approvalFeedback, setApprovalFeedback] = useState("");
  const [tab, setTab] = useState<"sources" | "checks" | "method">("sources");
  const [mobileView, setMobileView] = useState<"report" | "evidence">("report");
  const [evidenceVisible, setEvidenceVisible] = useState(true);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [sourceQuery, setSourceQuery] = useState("");
  const [claimFilter, setClaimFilter] = useState("all");
  const [followupQuestion, setFollowupQuestion] = useState("");
  const [reportVersion, setReportVersion] = useState<number | null>(null);
  const followupKeys = useRef(new Map<string, string>());
  const deferredSourceQuery = useDeferredValue(
    sourceQuery.trim().toLowerCase(),
  );
  const [reload, setReload] = useState(0);
  const loadedRunId = useRef(runId);
  const terminalSnapshot = useRef<{ runId: string; status: string } | null>(
    null,
  );
  const [snapshotRefreshing, setSnapshotRefreshing] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const report = useRef<HTMLDivElement>(null);
  const tabList = useRef<HTMLDivElement>(null);
  const tabPositions = useRef({ sources: 0, checks: 0, method: 0 });
  useSlidingIndicator(tabList, `${runId}-${tab}-${Boolean(run)}`);
  useEntrance(
    report,
    `${runId}-${Boolean(run)}`,
    ".report-header, .report-progress, .report-article, .report-pending",
  );
  useEntrance(
    panel,
    `${runId}-${tab}-${Boolean(run)}`,
    '.evidence-scroll[data-state="active"]',
    tab === "method" ? "right" : "left",
  );
  useEntrance(panel, activeSource ?? "closed", ".selected-source");

  function changeTab(value: string) {
    if (value !== "sources" && value !== "checks" && value !== "method") return;
    const current = panel.current?.querySelector<HTMLElement>(
      '.evidence-scroll[data-state="active"]',
    );
    if (current) tabPositions.current[tab] = current.scrollTop;
    setTab(value);
    requestAnimationFrame(() => {
      const next = panel.current?.querySelector<HTMLElement>(
        '.evidence-scroll[data-state="active"]',
      );
      if (next) next.scrollTop = tabPositions.current[value];
    });
  }
  const citationOrigin = useRef<HTMLButtonElement | null>(null);
  const citationIndex = useRef(-1);
  const restoreCitation = useRef(false);
  const readingPosition = useRef(0);
  const watermark = useRef(0);
  const versionRun = useRef(runId);

  useEffect(() => {
    if (versionRun.current === runId) return;
    versionRun.current = runId;
    setReportVersion(null);
    setClaimFilter("all");
    setFollowupQuestion("");
    setApprovalFeedback("");
    followupKeys.current.clear();
  }, [runId]);

  useEffect(() => {
    if (activeSource !== null || !restoreCitation.current) return;
    restoreCitation.current = false;
    const grid = report.current;
    if (grid && citationIndex.current >= 0)
      grid.scrollTop = readingPosition.current;
    const target = citationOrigin.current?.isConnected
      ? citationOrigin.current
      : document.querySelectorAll<HTMLButtonElement>(".citation-chip")[
          citationIndex.current
        ];
    (
      target ??
      panel.current?.querySelector<HTMLButtonElement>("[aria-selected=true]")
    )?.focus({ preventScroll: true });
    citationOrigin.current = null;
    citationIndex.current = -1;
  }, [activeSource]);

  useEffect(() => {
    let active = true;
    let stream: EventSource | undefined;
    let fetching = false;
    let pending = false;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;
    let terminalRetries = 0;
    const controller = new AbortController();
    watermark.current = 0;
    if (loadedRunId.current !== runId) {
      setRun(null);
      setActiveSource(null);
      terminalSnapshot.current = null;
      loadedRunId.current = runId;
    }
    setError("");
    const load = async () => {
      if (fetching) {
        pending = true;
        return;
      }
      fetching = true;
      setSnapshotRefreshing(true);
      let retryTerminalSnapshot = false;
      try {
        const response = await fetch(
          `/api/research/runs/${runId}${reportVersion ? `?reportVersion=${reportVersion}` : ""}`,
          {
            cache: "no-store",
            signal: AbortSignal.any([
              controller.signal,
              AbortSignal.timeout(10_000),
            ]),
          },
        );
        const body = (await response.json()) as Run & { error?: string };
        if (!active) return;
        if (!response.ok)
          throw new Error(body.error ?? "This research couldn’t be opened.");
        if (body.runId !== runId)
          throw new Error("The recorded state did not match this research.");
        if (
          terminalSnapshot.current?.runId === runId &&
          body.status !== terminalSnapshot.current.status
        ) {
          retryTerminalSnapshot = true;
          if (terminalRetries >= 3)
            setError(
              "The final recorded state is still updating. Refresh to try again.",
            );
          return;
        }
        const snapshotWatermark = Math.max(
          watermark.current,
          ...body.events.map((event) => event.sequence),
        );
        setRun((previous) =>
          previous?.runId === body.runId &&
          terminal.includes(previous.status) &&
          !terminal.includes(body.status)
            ? previous
            : body,
        );
        setError("");
        terminalRetries = 0;
        if (terminal.includes(body.status))
          terminalSnapshot.current = { runId, status: body.status };
        watermark.current = snapshotWatermark;
        if (!terminal.includes(body.status) && !stream) {
          stream = new EventSource(
            `/api/research/runs/${runId}/events?after=${watermark.current}`,
          );
          stream.onmessage = (event) => {
            if (!active) return;
            let refreshDelay = snapshotRefreshDelay();
            try {
              const payload = JSON.parse(event.data) as {
                sequence?: number;
                type?: string;
                errorCode?: string | null;
                occurredAt?: string;
              };
              refreshDelay = snapshotRefreshDelay(payload.type);
              if (typeof payload.sequence === "number") {
                if (payload.sequence <= watermark.current) return;
                watermark.current = Math.max(
                  watermark.current,
                  payload.sequence,
                );
              }
              const nextStatus =
                payload.type === "run.failed"
                  ? "failed"
                  : payload.type === "run.cancelled"
                    ? "cancelled"
                    : payload.type === "run.completed"
                      ? "completed"
                      : null;
              if (nextStatus) {
                terminalSnapshot.current = { runId, status: nextStatus };
                setRun((previous) =>
                  previous?.runId === runId
                    ? {
                        ...previous,
                        status: nextStatus,
                        errorCode:
                          nextStatus === "failed"
                            ? (payload.errorCode ?? previous.errorCode)
                            : previous.errorCode,
                        ...(payload.occurredAt
                          ? { updatedAt: payload.occurredAt }
                          : {}),
                      }
                    : previous,
                );
                stream?.close();
                clearTimeout(refreshTimer);
                refreshTimer = undefined;
              }
            } catch {
              /* Keep the last valid snapshot. */
            }
            // Coalesce source bursts instead of refetching the full report per event.
            if (!refreshTimer)
              refreshTimer = setTimeout(() => {
                refreshTimer = undefined;
                void load();
              }, refreshDelay);
          };
          stream.onerror = () => {
            // Native EventSource reconnects; refresh once to catch a missed terminal event.
            if (
              active &&
              terminalSnapshot.current?.runId !== runId &&
              !refreshTimer
            )
              refreshTimer = setTimeout(() => {
                refreshTimer = undefined;
                void load();
              }, 1000);
          };
        }
        if (terminal.includes(body.status)) stream?.close();
      } catch (cause) {
        if (active) {
          retryTerminalSnapshot = terminalSnapshot.current?.runId === runId;
          setError(
            cause instanceof Error
              ? cause.message
              : "The research service is unavailable.",
          );
        }
      } finally {
        fetching = false;
        if (active) setSnapshotRefreshing(false);
        if (pending && active) {
          pending = false;
          void load();
        } else if (active && retryTerminalSnapshot && terminalRetries < 3) {
          const delay = 1000 * 2 ** terminalRetries++;
          refreshTimer = setTimeout(() => {
            refreshTimer = undefined;
            void load();
          }, delay);
        }
      }
    };
    void load();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(refreshTimer);
      stream?.close();
    };
  }, [runId, reload, reportVersion]);

  async function control(action: "cancel" | "retry") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const updatedLimit =
        action === "retry" && run?.errorCode === "wall_clock_limit_exceeded"
          ? `?maxWallClockMs=${Math.max(run.budget.maxWallClockMs ?? 0, modeDeadline(run.budget.maxSearchCalls))}`
          : "";
      const response = await fetch(
        `/api/research/runs/${runId}/${action}${updatedLimit}`,
        {
          method: "POST",
        },
      );
      const body = (await response.json()) as {
        runId?: string;
        error?: string;
      };
      if (!response.ok)
        throw new Error(body.error ?? "That action couldn’t be completed.");
      if (action === "retry" && body.runId)
        router.push(`/research/${body.runId}`);
      else
        setFeedback(
          "Cancellation requested. Waiting for the research to stop.",
        );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The action failed. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function decidePlan(decision: "approve" | "reject") {
    if (
      busy ||
      approving.current ||
      run?.status !== "awaiting_approval" ||
      run.approval?.state !== "pending"
    )
      return;
    approving.current = true;
    setBusy(true);
    setApprovalDecision(decision);
    setApprovalFeedback("");
    setError("");
    try {
      const response = await fetch(`/api/research/runs/${runId}/approve`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ planId: run.approval.planId, decision }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(
          body.error ??
            (typeof body.detail === "string"
              ? body.detail
              : "The plan decision couldn’t be saved. Try again."),
        );
      }
      setApprovalFeedback(
        decision === "approve"
          ? "Plan approved. Research is queued."
          : "Plan rejected. Research is cancelled.",
      );
      setReload((value) => value + 1);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The plan decision couldn’t be saved. Try again.",
      );
    } finally {
      approving.current = false;
      setApprovalDecision(null);
      setBusy(false);
    }
  }
  async function copyReport() {
    if (!run?.report) return;
    try {
      await navigator.clipboard.writeText(reportExport(run));
      setFeedback("Report copied.");
    } catch {
      setFeedback(
        "Copy is unavailable in this browser. You can download the report instead.",
      );
    }
  }
  function downloadReport() {
    if (!run?.report) return;
    const url = URL.createObjectURL(
      new Blob([reportExport(run)], { type: "text/markdown;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "research-" + runId + ".md";
    anchor.click();
    URL.revokeObjectURL(url);
    setFeedback("Report downloaded.");
  }
  const markdown = run?.report?.markdown.split(/^## Sources\s*$/im)[0] ?? "";
  const sections = useMemo(() => reportSections(markdown), [markdown]);
  const refs = useMemo(
    () => referenceMap(run?.report?.markdown ?? "", run?.sources ?? []),
    [run?.report?.markdown, run?.sources],
  );
  const selected = run?.sources.find((source) => source.id === activeSource);
  const visibleSources = useMemo(
    () =>
      run?.sources.filter((source) =>
        `${source.title} ${domain(source.url)}`
          .toLowerCase()
          .includes(deferredSourceQuery),
      ) ?? [],
    [run?.sources, deferredSourceQuery],
  );
  const activePhase =
    run?.status === "awaiting_approval"
      ? 0
      : run
        ? phases.indexOf(run.status)
        : -1;
  function selectCitation(number: number, origin: HTMLButtonElement) {
    const source = refs.get(number);
    if (!source) {
      setFeedback("Source details for this reference are unavailable.");
      return;
    }
    citationOrigin.current = origin;
    citationIndex.current = Array.from(
      document.querySelectorAll(".citation-chip"),
    ).indexOf(origin);
    readingPosition.current = report.current?.scrollTop ?? 0;
    setActiveSource(source.id);
    setMobileView("evidence");
    setEvidenceVisible(true);
    changeTab("sources");
    requestAnimationFrame(() =>
      panel.current
        ?.querySelector<HTMLElement>(".selected-source")
        ?.focus({ preventScroll: true }),
    );
  }
  function closeSource() {
    restoreCitation.current = true;
    setActiveSource(null);
    setMobileView("report");
  }
  async function investigate(question: string, gapId?: string) {
    if (busy || question.trim().length < 5) return;
    setBusy(true);
    setFeedback("");
    try {
      const requestQuestion = question.slice(0, 1000).trim();
      const key = JSON.stringify([
        requestQuestion,
        gapId ?? null,
        run?.report?.version ?? null,
      ]);
      if (!followupKeys.current.has(key))
        followupKeys.current.set(key, crypto.randomUUID());
      const response = await fetch(`/api/research/runs/${runId}/followups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: requestQuestion,
          ...(gapId ? { gapId } : {}),
          ...(run?.report ? { reportVersion: run.report.version } : {}),
          idempotencyKey: followupKeys.current.get(key),
        }),
      });
      const body = await response.json();
      if (!response.ok)
        throw new Error(
          typeof body.detail === "string"
            ? body.detail
            : "The investigation could not be created.",
        );
      router.push(`/research/${body.runId}`);
    } catch (cause) {
      setFeedback(
        cause instanceof Error
          ? cause.message
          : "The investigation could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }
  const stopped = run?.status === "failed" || run?.status === "cancelled";
  const limitedReport =
    run?.status === "completed" &&
    run.report &&
    run.claimChecks !== undefined &&
    !run.claimChecks.some((claim) => claim.publishedInReport);
  const working =
    run && !terminal.includes(run.status) && run.status !== "awaiting_approval";
  return (
    <WorkspaceShell
      activeRunId={runId}
      title="Research brief"
      toolbar={
        <>
          <button
            className="desk-evidence-toggle"
            onClick={() => {
              if (window.matchMedia("(max-width: 1100px)").matches)
                setMobileView((value) =>
                  value === "report" ? "evidence" : "report",
                );
              else setEvidenceVisible((value) => !value);
            }}
            aria-controls="research-evidence"
          >
            <Icon name="book" size={16} />
            <span className="desktop-only">
              {evidenceVisible ? "Hide evidence" : "Show evidence"}
            </span>
            <span className="mobile-evidence-label">
              {mobileView === "report" ? "Evidence" : "Report"}
            </span>
          </button>
          {run?.report ? (
            <>
              <button
                className="icon-button"
                onClick={() => void copyReport()}
                aria-label="Copy report"
              >
                <Icon name="copy" size={17} />
              </button>
              <button
                className="icon-button"
                onClick={downloadReport}
                aria-label="Download report"
              >
                <Icon name="download" size={17} />
              </button>
              <button
                className="text-button"
                onClick={() => window.print()}
                aria-label="Print or save report as PDF"
              >
                PDF
              </button>
            </>
          ) : null}
        </>
      }
    >
      {run ? (
        <>
          <section
            className="run-status-rail"
            data-status={error ? "failed" : run.status}
            role={run.status === "failed" || error ? "alert" : "status"}
            aria-live={
              run.status === "failed" || error ? "assertive" : "polite"
            }
            aria-atomic="true"
          >
            <div>
              <strong>
                {error
                  ? "Connection or action problem"
                  : limitedReport
                    ? "Evidence record ready"
                    : runStage(run.status)}
              </strong>
              <p>
                {error
                  ? `${error} Last recorded state: ${runStage(run.status)}.`
                  : run.status === "failed"
                    ? `${runFailure(run.errorCode)} ${run.sourceCount} collected sources remain available.`
                    : run.status === "cancelled"
                      ? "This run was stopped. Collected evidence is preserved."
                      : run.status === "awaiting_approval"
                        ? "Review the plan below to continue. Waiting here does not use the active-time budget."
                        : run.status === "completed"
                          ? limitedReport
                            ? "No finding passed the complete evidence checks. This is a limited result, not a full answer. Inspect Checks and research gaps before relying on it."
                            : "Your report and recorded evidence are ready."
                          : "Progress and sources below reflect recorded activity, not estimated completion."}
              </p>
            </div>
            {error ? (
              <Button
                variant="outline"
                disabled={snapshotRefreshing}
                onClick={() => setReload((value) => value + 1)}
              >
                {snapshotRefreshing
                  ? "Refreshing recorded state…"
                  : "Refresh recorded state"}
              </Button>
            ) : null}
            {stopped ? (
              <div className="run-status-actions">
                <Button disabled={busy} onClick={() => void control("retry")}>
                  {busy
                    ? "Starting…"
                    : run.errorCode === "wall_clock_limit_exceeded"
                      ? `Retry · ${Math.max(run.budget.maxWallClockMs ?? 0, modeDeadline(run.budget.maxSearchCalls)) / 60_000}-min limit`
                      : "Start fresh attempt"}
                </Button>
                <small>New run; provider costs may apply.</small>
              </div>
            ) : (
              <span>{run.sourceCount} sources</span>
            )}
            {working ? (
              <div className="run-busy-track" aria-hidden="true">
                <span />
              </div>
            ) : null}
          </section>
          <div
            className="report-grid"
            data-mobile-view={mobileView}
            data-evidence-visible={evidenceVisible}
          >
            <div ref={report} className="report-scroll">
              <header className="report-header">
                <div className="report-meta">
                  <Status status={run.status} />
                  <span>{run.sourceCount} sources</span>
                  <span>{dateLabel(run.createdAt)}</span>
                  <RunClock
                    startedAt={run.createdAt}
                    endedAt={
                      terminal.includes(run.status)
                        ? (run.updatedAt ?? run.report?.publishedAt)
                        : undefined
                    }
                  />
                </div>
                <h1>{run.originalQuestion}</h1>
                {run.insights && run.insights.reportVersions.length > 1 && (
                  <label className="desk-help report-version-control">
                    Report version{" "}
                    <select
                      value={run.report?.version ?? ""}
                      onChange={(event) =>
                        setReportVersion(Number(event.target.value))
                      }
                    >
                      {run.insights.reportVersions.map((version) => (
                        <option key={version.id} value={version.version}>
                          Version {version.version} ·{" "}
                          {dateLabel(version.createdAt)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {run.insights?.parentRunId && (
                  <a
                    className="text-button"
                    href={`/research/${run.insights.parentRunId}`}
                  >
                    Open preserved parent report
                  </a>
                )}
                {run.insights?.parentReportId && (
                  <p className="desk-help">
                    Follow-up investigation. Its parent report is preserved;
                    evidence is collected afresh.
                  </p>
                )}
              </header>
              <div className="research-signal" aria-label="Research overview">
                <div>
                  <span>Evidence collected</span>
                  <strong>
                    {run.sourceCount}
                    <small>
                      {run.sourceLimit !== undefined &&
                      run.sourceCount <= run.sourceLimit
                        ? ` / ${run.sourceLimit}`
                        : " sources"}
                    </small>
                  </strong>
                </div>
                <div>
                  <span>Questions explored</span>
                  <strong>
                    {
                      run.subQuestions.filter(
                        (item) => item.status === "complete",
                      ).length
                    }
                    <small> / {run.subQuestions.length}</small>
                  </strong>
                </div>
                <div>
                  <span>{run.report ? "Reading time" : "Current step"}</span>
                  <strong>
                    {run.report
                      ? `${readingMinutes(markdown)} min`
                      : run.status === "awaiting_approval"
                        ? "Review plan"
                        : runStage(run.status)}
                  </strong>
                </div>
              </div>
              {approvalFeedback &&
              ["planning", "queued"].includes(run.status) ? (
                <p role="status">{approvalFeedback}</p>
              ) : null}
              {run.status === "awaiting_approval" &&
              run.approval?.state === "pending" ? (
                <section
                  className="desk-composer"
                  aria-labelledby="plan-approval-title"
                  aria-busy={approvalDecision !== null}
                >
                  <h2 id="plan-approval-title">Review the research plan</h2>
                  <p className="desk-help">
                    Approve these questions to queue research. Rejecting the
                    plan cancels this run.
                  </p>
                  <ul>
                    {run.approval.questions.map((question) => (
                      <li key={question.id}>{question.question}</li>
                    ))}
                  </ul>
                  <div className="desk-inline-actions">
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => void decidePlan("reject")}
                    >
                      {approvalDecision === "reject"
                        ? "Rejecting…"
                        : "Reject plan"}
                    </Button>
                    <Button
                      disabled={busy}
                      onClick={() => void decidePlan("approve")}
                    >
                      {approvalDecision === "approve"
                        ? "Approving…"
                        : "Approve plan"}
                    </Button>
                  </div>
                </section>
              ) : null}
              <div
                className="report-progress"
                aria-label="Research progress"
                role="status"
                aria-live="polite"
              >
                {phases.map((phase, index) => (
                  <span
                    key={phase}
                    className={
                      run.status === "completed" ||
                      (activePhase >= 0 && index < activePhase)
                        ? "phase-done"
                        : index === activePhase
                          ? "phase-current"
                          : ""
                    }
                  >
                    <i>
                      {run.status === "completed" ||
                      (activePhase >= 0 && index < activePhase) ? (
                        <Icon name="check" size={12} />
                      ) : (
                        index + 1
                      )}
                    </i>
                    {labels[index]}
                  </span>
                ))}
              </div>
              {run.insights && (
                <details className="report-orchestration">
                  <summary>
                    Inspect live orchestration · {run.insights.tasks.length}{" "}
                    recorded tasks
                  </summary>
                  <ExecutionView
                    insights={run.insights}
                    inspectSource={(id) => {
                      setEvidenceVisible(true);
                      setMobileView("evidence");
                      setActiveSource(id);
                      changeTab("sources");
                    }}
                  />
                </details>
              )}
              {!terminal.includes(run.status) && (
                <div className="report-control">
                  <span>
                    {feedback.startsWith("Cancellation")
                      ? "Stop requested"
                      : run.status === "awaiting_approval"
                        ? "Waiting for plan approval"
                        : "Research in progress"}
                  </span>
                  <button
                    className="text-button"
                    disabled={busy || feedback.startsWith("Cancellation")}
                    onClick={() => void control("cancel")}
                  >
                    {busy
                      ? "Requesting…"
                      : feedback.startsWith("Cancellation")
                        ? "Stopping…"
                        : "Stop research"}
                  </button>
                </div>
              )}
              {stopped && (
                <div className="stopped-notice">
                  <Icon name="layers" />
                  <div>
                    <strong>Evidence kept for inspection</strong>
                    <p>
                      Collected sources and execution records remain available
                      in the Evidence and Methodology panels.
                    </p>
                  </div>
                </div>
              )}
              {run.report ? (
                <article className="report-article">
                  {sections.length > 1 && (
                    <nav
                      className="report-outline"
                      aria-label="Report sections"
                    >
                      <span>In this brief</span>
                      <div>
                        {sections.map((section) => (
                          <button
                            key={section.id}
                            onClick={(event) => {
                              const target =
                                report.current?.querySelector<HTMLElement>(
                                  `#${section.id}`,
                                );
                              if (!target) return;
                              target.tabIndex = -1;
                              target.focus({ preventScroll: true });
                              target.scrollIntoView({
                                block: "start",
                                behavior:
                                  event.detail === 0 ||
                                  window.matchMedia(
                                    "(prefers-reduced-motion: reduce)",
                                  ).matches
                                    ? "instant"
                                    : "smooth",
                              });
                            }}
                          >
                            {section.title}
                          </button>
                        ))}
                      </div>
                    </nav>
                  )}
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm, remarkCitations]}
                    components={{
                      a: ({ href, children }) =>
                        href?.startsWith("#source-") ? (
                          <button
                            className="citation-chip"
                            aria-label={`Open source ${href.slice(8)}`}
                            onClick={(event) =>
                              selectCitation(
                                Number(href.slice(8)),
                                event.currentTarget,
                              )
                            }
                          >
                            {children}
                          </button>
                        ) : (
                          <a
                            href={safeUrl(href ?? "")}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {children}
                          </a>
                        ),
                      table: ({ children }) => (
                        <div
                          className="report-table-wrap"
                          tabIndex={0}
                          role="region"
                          aria-label="Research comparison table"
                        >
                          <table>{children}</table>
                        </div>
                      ),
                    }}
                  >
                    {markdown}
                  </ReactMarkdown>
                  <div className="report-end">
                    <span className="end-mark">
                      <Icon name="check" size={15} />
                    </span>
                    <span>End of research brief</span>
                    <span>{run.sourceCount} sources collected</span>
                  </div>
                </article>
              ) : !stopped && run.status !== "awaiting_approval" ? (
                <div className="report-pending">
                  <span className="pending-symbol">
                    <Icon name="search" size={26} />
                  </span>
                  <h2>
                    {run.status === "writing"
                      ? "Bringing the findings together."
                      : "Following the evidence."}
                  </h2>
                  <p>
                    {run.status === "verifying"
                      ? "Reviewing the research before writing. Sources are available in the evidence panel."
                      : "Your answer will appear here when it’s ready. You can explore the sources and methodology as research develops."}
                  </p>
                  <div className="report-skeleton" aria-hidden="true">
                    <Skeleton />
                    <Skeleton />
                    <Skeleton />
                  </div>
                  {run.subQuestions.length > 0 && (
                    <ol
                      className="desk-working-questions"
                      aria-label="Questions being explored"
                    >
                      {run.subQuestions.map((item) => (
                        <li key={item.id}>
                          <Status status={item.status} />
                          <span>{item.question}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                  {run.sources.length > 0 && (
                    <div className="live-evidence">
                      <span>Evidence arriving</span>
                      {run.sources
                        .slice(-3)
                        .reverse()
                        .map((source) => (
                          <button
                            key={source.id}
                            onClick={() => {
                              setActiveSource(source.id);
                              setMobileView("evidence");
                              setEvidenceVisible(true);
                              changeTab("sources");
                            }}
                          >
                            <Icon name="book" size={16} />
                            <span>
                              <strong>
                                {source.title || domain(source.url)}
                              </strong>
                              <small>{domain(source.url)}</small>
                            </span>
                            <Icon name="arrow" size={14} />
                          </button>
                        ))}
                    </div>
                  )}
                </div>
              ) : null}
              {run.report && run.insights && (
                <GapView
                  gaps={run.insights.gaps}
                  busy={busy}
                  investigate={(question, gapId) =>
                    void investigate(question, gapId)
                  }
                />
              )}
              {run.status === "completed" && (
                <form
                  className="report-followup"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void investigate(followupQuestion);
                  }}
                >
                  <label htmlFor="followup-question">
                    Continue this research
                  </label>
                  <textarea
                    id="followup-question"
                    value={followupQuestion}
                    onChange={(event) =>
                      setFollowupQuestion(event.target.value)
                    }
                    minLength={5}
                    maxLength={1000}
                    required
                    placeholder="Ask a follow-up question…"
                  />
                  <p className="desk-help">
                    Creates a separate investigation with this report’s depth
                    budget. The original report is unchanged.
                  </p>
                  <button
                    className="desk-button desk-button-primary"
                    disabled={busy || followupQuestion.trim().length < 5}
                  >
                    {busy ? "Creating investigation…" : "Investigate"}
                  </button>
                </form>
              )}
              {!!run.insights?.followupRuns.length && (
                <nav
                  className="research-gaps"
                  aria-label="Related investigations"
                >
                  <h2>Follow-up investigations</h2>
                  {run.insights.followupRuns.map((item) => (
                    <a
                      className="text-button"
                      key={item.runId}
                      href={`/research/${item.runId}`}
                    >
                      {item.status} · {dateLabel(item.createdAt)}
                    </a>
                  ))}
                </nav>
              )}
              <p className="report-feedback" role="status">
                {feedback}
              </p>
              {run.report && (
                <section className="print-report">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {reportExport(run)}
                  </ReactMarkdown>
                </section>
              )}
            </div>
            <aside
              id="research-evidence"
              className="evidence-panel"
              ref={panel}
              aria-label="Research evidence"
            >
              <Tabs
                value={tab}
                onValueChange={changeTab}
                className="evidence-tab-root"
              >
                <TabsList
                  ref={tabList}
                  className="evidence-tabs"
                  aria-label="Evidence view"
                >
                  <TabsTrigger value="sources">
                    Sources<span>{run.sourceCount}</span>
                  </TabsTrigger>
                  <TabsTrigger value="method">Methodology</TabsTrigger>
                  <TabsTrigger value="checks">
                    Checks<span>{run.claimChecks?.length ?? 0}</span>
                  </TabsTrigger>
                  <i className="selection-marker" aria-hidden="true" />
                </TabsList>
                <TabsContent value="sources" className="evidence-scroll">
                  <>
                    {selected && (
                      <div className="selected-source" tabIndex={-1}>
                        <div className="selected-source-heading">
                          <span>Selected reference</span>
                          <button
                            className="icon-button"
                            aria-label="Close source details"
                            onClick={closeSource}
                          >
                            <Icon name="close" size={16} />
                          </button>
                        </div>
                        <h3>{selected.title || domain(selected.url)}</h3>
                        <p>{domain(selected.url)}</p>
                        {selected.assessment && (
                          <div className="source-assessment">
                            <p>
                              Publisher:{" "}
                              {selected.assessment.publisher ?? "Unknown"}
                            </p>
                            <p>
                              Publication date:{" "}
                              {selected.assessment.publishedAt
                                ? dateLabel(selected.assessment.publishedAt)
                                : "Unknown"}
                            </p>
                            <p>
                              Retrieved:{" "}
                              {dateLabel(selected.assessment.retrievedAt)}
                            </p>
                            <details>
                              <summary>
                                Source assessment and limitations
                              </summary>
                              <ul>
                                {selected.assessment.reasons.map((reason) => (
                                  <li key={reason}>{reason}</li>
                                ))}
                              </ul>
                              <p>
                                {selected.discoveryPaths?.length ?? 0} recorded
                                discovery paths
                              </p>
                            </details>
                          </div>
                        )}
                        <div className="source-detail-note">
                          This source was collected during the research. Open
                          the original to inspect its contents.
                        </div>
                        {run.claimChecks?.flatMap((claim) =>
                          claim.citations
                            .filter(
                              (citation) => citation.sourceId === selected.id,
                            )
                            .map((citation) => (
                              <div key={citation.id} className="desk-quote">
                                <Badge>
                                  {citation.exactSpanVerified
                                    ? "Exact quote matched"
                                    : "Quote check not recorded"}
                                </Badge>
                                <blockquote>{citation.quote}</blockquote>
                                {citation.context && (
                                  <details>
                                    <summary>
                                      Retrieved surrounding context
                                    </summary>
                                    <p>{citation.context}</p>
                                  </details>
                                )}
                                <p>{claim.claim}</p>
                                <small>
                                  Model review:{" "}
                                  {citation.verdict.replaceAll("_", " ")}
                                </small>
                              </div>
                            )),
                        )}
                        <a
                          href={safeUrl(selected.url)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open original source
                          <Icon name="external" size={14} />
                        </a>
                      </div>
                    )}
                    <div className="panel-intro">
                      <h2>The evidence behind the work.</h2>
                      <p>
                        Explore collected sources and follow references from the
                        report.
                      </p>
                    </div>
                    {run.sources.length ? (
                      <>
                        <label className="evidence-search">
                          <Icon name="search" size={16} />
                          <input
                            type="search"
                            value={sourceQuery}
                            onChange={(event) =>
                              setSourceQuery(event.target.value)
                            }
                            placeholder="Find in collected evidence…"
                            aria-label="Search collected evidence"
                          />
                        </label>
                        {visibleSources.length === 0 && (
                          <p role="status" className="panel-empty">
                            No sources match. Try a title or publisher.
                          </p>
                        )}
                        <ul className="evidence-list">
                          {visibleSources.map((source) => {
                            const citation = Array.from(refs).find(
                              ([, item]) => item.id === source.id,
                            )?.[0];
                            return (
                              <li
                                key={source.id}
                                className={
                                  activeSource === source.id
                                    ? "source-selected"
                                    : ""
                                }
                              >
                                <button
                                  onClick={() => setActiveSource(source.id)}
                                  aria-label={`Inspect ${source.title || domain(source.url)}`}
                                  aria-pressed={activeSource === source.id}
                                >
                                  <span className="source-domain">
                                    <span className="source-monogram">
                                      {domain(source.url)[0]?.toUpperCase()}
                                    </span>
                                    {domain(source.url)}
                                    {citation && (
                                      <span className="source-citation-number">
                                        [{citation}]
                                      </span>
                                    )}
                                  </span>
                                  <strong>{source.title || source.url}</strong>
                                  <span className="source-kind">
                                    {source.sourceClass === "unknown"
                                      ? "Web source"
                                      : source.sourceClass}
                                    <span>
                                      {citation
                                        ? "Cited in brief"
                                        : "Collected"}
                                    </span>
                                  </span>
                                  {source.assessment &&
                                    source.assessment.sameMaterialCount > 1 && (
                                      <small className="source-correlation">
                                        Repeated material · not independent
                                        corroboration
                                      </small>
                                    )}
                                </button>
                                <a
                                  className="source-external"
                                  href={safeUrl(source.url)}
                                  target="_blank"
                                  rel="noreferrer"
                                  aria-label={`Open ${source.title || domain(source.url)} in a new tab`}
                                >
                                  <Icon name="external" size={14} />
                                </a>
                              </li>
                            );
                          })}
                        </ul>
                      </>
                    ) : (
                      <div className="panel-empty">
                        <Icon name="book" size={28} />
                        <p>
                          {stopped
                            ? "No sources were collected for this run."
                            : "Sources appear here as research develops."}
                        </p>
                      </div>
                    )}
                  </>
                </TabsContent>
                <TabsContent value="checks" className="evidence-scroll">
                  <div className="panel-intro">
                    <h2>Claims and their evidence.</h2>
                    <p>
                      Stored quote checks and model support reviews—not a
                      guarantee of factual accuracy.
                    </p>
                  </div>
                  <label className="claim-filter">
                    Verification status
                    <select
                      value={claimFilter}
                      onChange={(event) => setClaimFilter(event.target.value)}
                    >
                      <option value="all">All claims</option>
                      {[
                        "supported",
                        "partially_supported",
                        "contradicted",
                        "insufficient_evidence",
                        "not_checked",
                      ].map((value) => (
                        <option key={value} value={value}>
                          {value.replaceAll("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                  {run.claimChecks?.length ? (
                    <>
                      {run.claimChecks
                        .filter(
                          (claim) =>
                            claimFilter === "all" ||
                            (claim.status ?? "not_checked") === claimFilter,
                        )
                        .map((claim) => (
                          <article key={claim.id} className="desk-claim">
                            <Badge>
                              {(claim.status ?? "not_checked").replaceAll(
                                "_",
                                " ",
                              )}
                            </Badge>
                            <h3>{claim.claim}</h3>
                            {claim.section && (
                              <p className="desk-help">
                                {claim.publishedInReport
                                  ? "Report section"
                                  : "Excluded draft section"}
                                : {claim.section}
                              </p>
                            )}
                            <p className="desk-help">
                              {claim.supportingSourceIds?.length ?? 0}{" "}
                              supporting sources ·{" "}
                              {claim.contradictingSourceIds?.length ?? 0}{" "}
                              conflicting sources
                            </p>
                            {claim.citations.length === 0 && (
                              <p>
                                No quoted evidence was recorded. This assertion
                                is not established.
                              </p>
                            )}
                            {run.status === "completed" && (
                              <button
                                className="text-button"
                                disabled={busy}
                                onClick={() =>
                                  void investigate(
                                    `Find original supporting and contradicting evidence for: ${claim.claim}`,
                                  )
                                }
                              >
                                Investigate assertion
                              </button>
                            )}
                            {claim.citations.map((citation) => (
                              <div className="desk-quote" key={citation.id}>
                                <Badge>
                                  {citation.exactSpanVerified
                                    ? "Exact quote matched"
                                    : "Not checked"}
                                </Badge>
                                <blockquote>{citation.quote}</blockquote>
                                <small>
                                  Model review:{" "}
                                  {citation.verdict.replaceAll("_", " ")}
                                </small>
                                <button
                                  className="text-button"
                                  onClick={() => {
                                    setActiveSource(citation.sourceId);
                                    changeTab("sources");
                                  }}
                                >
                                  Inspect source
                                </button>
                              </div>
                            ))}
                            {claim.caveats.length > 0 && (
                              <ul>
                                {claim.caveats.map((caveat, index) => (
                                  <li key={index}>{caveat}</li>
                                ))}
                              </ul>
                            )}
                          </article>
                        ))}
                      {!run.claimChecks.some(
                        (claim) =>
                          claimFilter === "all" ||
                          (claim.status ?? "not_checked") === claimFilter,
                      ) && (
                        <Empty title="No claims match">
                          Choose a different verification status.
                        </Empty>
                      )}
                    </>
                  ) : (
                    <Empty title="No claim checks recorded">
                      {terminal.includes(run.status)
                        ? "This run has no stored claim-level checks. Collected sources remain available."
                        : "Checks appear after synthesis and verification complete."}
                    </Empty>
                  )}
                </TabsContent>
                <TabsContent value="method" className="evidence-scroll">
                  <>
                    <div className="panel-intro">
                      <h2>How the research unfolded.</h2>
                      <p>The plan and activity recorded for this question.</p>
                    </div>
                    <div className="method-budget">
                      <span>Provider calls (search + extraction)</span>
                      <strong>
                        {run.usage.searchCalls} / {run.budget.maxSearchCalls}
                      </strong>
                    </div>
                    {run.insights && (
                      <ExecutionView
                        insights={run.insights}
                        inspectSource={(id) => {
                          setActiveSource(id);
                          changeTab("sources");
                        }}
                      />
                    )}
                    <h3 className="panel-section-title">Questions explored</h3>
                    {run.subQuestions.length ? (
                      <ol className="question-plan">
                        {run.subQuestions.map((item) => (
                          <li key={item.id}>
                            <p>{item.question}</p>
                            <Status status={item.status} />
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="panel-empty">
                        No research plan has been recorded yet.
                      </p>
                    )}
                    <h3 className="panel-section-title">Research activity</h3>
                    <ol className="activity-list">
                      {[...run.events]
                        .reverse()
                        .filter((event) => event.type !== "source.discovered")
                        .map((event) => (
                          <li key={event.sequence}>
                            <span className="activity-dot" />
                            <div>
                              <strong>
                                {event.label || event.type.replaceAll(".", " ")}
                              </strong>
                              <small>{dateLabel(event.occurredAt)}</small>
                            </div>
                          </li>
                        ))}
                    </ol>
                  </>
                </TabsContent>
              </Tabs>
            </aside>
          </div>
        </>
      ) : (
        <div className="run-opening">
          {error ? (
            <>
              <Icon name="book" size={36} />
              <h1>We couldn’t open this research.</h1>
              <p role="alert">{error}</p>
              <button
                className="action"
                onClick={() => setReload((value) => value + 1)}
              >
                Try again
                <Icon name="arrow" size={18} />
              </button>
            </>
          ) : (
            <>
              <div className="opening-placeholder" aria-hidden="true" />
              <h1 role="status">Opening your research…</h1>
              <p>Finding the question, sources, and research trail.</p>
            </>
          )}
        </div>
      )}
    </WorkspaceShell>
  );
}
