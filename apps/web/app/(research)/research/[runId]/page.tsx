"use client";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import {
  answerSectionKind,
  followupSuggestions,
  hasNoVerifiedFindings,
  readingMinutes,
  reportDisplayMarkdown,
  reportSections,
} from "../../../../lib/report-presentation";
import { parseSourceList } from "../../../../lib/citation-format";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import {
  EditResearchPlanRequestSchema,
  EditResearchPlanResponseSchema,
  ReportDocumentV1Schema,
} from "@research/contracts";
import type { z } from "zod";
import { publishResearchHistory } from "../../../../lib/research-history-events";
import { reportExport } from "../../../../lib/report-export";
import {
  retryDeadline,
  runStage,
  runFailure,
  snapshotRefreshDelay,
  createSnapshotRefresh,
  runPhaseIndex,
  runPhases,
} from "../../../../lib/run-status";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { WorkspaceShell } from "../../../components/workspace-shell";
import { RunClock } from "../../../components/run-clock";
import { ResearchActivity } from "../../../components/research-activity";
import { SaveToLibrary } from "../../../components/save-to-library";
import { ReportActions } from "../../../components/report-actions";
import {
  EvidencePresets,
  EvidenceResizer,
  SourcesTable,
  useEvidenceLayout,
  type SourceRow,
} from "../../../components/research-workspace";
import {
  CitationPreview,
  FollowupSuggestions,
  MethodSummary,
  ReferenceList,
  ReportTable,
  type CitationPreviewData,
} from "../../../components/research-answer";
import {
  Badge,
  Button,
  Empty,
  Skeleton,
} from "../../../components/workbench-ui";
import {
  ExecutionView,
  OrchestrationSummary,
  settleInsights,
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
  mode?: "focused" | "balanced" | "deep" | null;
  modePolicyVersion?: string | null;
  status: string;
  originalQuestion: string;
  reportRequirements?: string[];
  approval?: {
    planId: string;
    state: "pending" | "approve" | "reject";
    editable: boolean;
    planVersion: number;
    maxQuestions: number;
    questions: { id: string; question: string }[];
    /** Closed plan-review waits, excluded from active run time. */
    waitedMs?: number;
    /** Start of the plan-review wait that is still open, if any. */
    waitStartedAt?: string | null;
  } | null;
  planVersion: number;
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
    maxProviderOperations?: number | null;
    maxSources?: number | null;
    maxEstimatedCostUsd: number;
    maxWallClockMs?: number;
  };
  usage: { searchCalls: number };
  report: {
    id: string;
    version: number;
    markdown: string;
    publishedAt: string;
    document?: z.infer<typeof ReportDocumentV1Schema> | null;
    answerQuality?:
      "answered" | "partial" | "insufficient_evidence" | "not_assessed";
  } | null;
  sources: Source[];
  subQuestions: { id: string; question: string; status: string }[];
  events: RunEvent[];
};
type MarkdownNode = {
  type: string;
  value?: string;
  url?: string;
  depth?: number;
  children?: MarkdownNode[];
  data?: { hName?: string; hProperties: Record<string, unknown> };
};
const terminal = ["failed", "completed", "cancelled"];
const labels = ["Plan", "Research", "Check", "Write", "Answer"];
const sourceLabel = (count: number) =>
  `${count} ${count === 1 ? "source" : "sources"}`;

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

function publicationLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }).format(date);
}

const plainText = (node: MarkdownNode): string =>
  node.value ?? (node.children ?? []).map(plainText).join("");

/** Wrap each level-2 heading and its body in a section tagged with its role. */
function remarkAnswerSections() {
  return (tree: MarkdownNode) => {
    if (!tree.children) return;
    const out: MarkdownNode[] = [];
    let current: MarkdownNode | null = null;
    for (const child of tree.children) {
      if (child.type === "heading" && child.depth === 2) {
        current = {
          type: "answerSection",
          children: [child],
          data: {
            hName: "section",
            hProperties: {
              className: ["answer-section"],
              dataKind: answerSectionKind(plainText(child)),
            },
          },
        };
        out.push(current);
      } else if (current) current.children?.push(child);
      else out.push(child);
    }
    tree.children = out;
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
  const [editingPlan, setEditingPlan] = useState(false);
  const [draftQuestions, setDraftQuestions] = useState<string[]>([]);
  const [planSaving, setPlanSaving] = useState(false);
  const [planEditError, setPlanEditError] = useState("");
  const [editBaseVersion, setEditBaseVersion] = useState<number | null>(null);
  const [editBasePlanId, setEditBasePlanId] = useState<string | null>(null);
  const [planStale, setPlanStale] = useState(false);
  const [savedPlanVersion, setSavedPlanVersion] = useState<number | null>(null);
  const [tab, setTab] = useState<"sources" | "checks" | "method">("sources");
  const [mobileView, setMobileView] = useState<"report" | "evidence">("report");
  const [evidenceVisible, setEvidenceVisible] = useState(true);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [sourceQuery, setSourceQuery] = useState("");
  const [claimFilter, setClaimFilter] = useState("all");
  const [followupQuestion, setFollowupQuestion] = useState("");
  const [reportVersion, setReportVersion] = useState<number | null>(null);
  const sourceQueryApplied = useRef<string | null>(null);
  useEffect(() => {
    const version = new URLSearchParams(window.location.search).get(
      "reportVersion",
    );
    setReportVersion(
      version && /^[1-9]\d{0,3}$|^10000$/.test(version)
        ? Number(version)
        : null,
    );
    sourceQueryApplied.current = null;
  }, [runId]);
  useEffect(() => {
    if (!run || run.runId !== runId || sourceQueryApplied.current === runId)
      return;
    const sourceId = new URLSearchParams(window.location.search).get(
      "sourceId",
    );
    sourceQueryApplied.current = runId;
    if (!sourceId || !run.sources.some((source) => source.id === sourceId))
      return;
    setActiveSource(sourceId);
    setEvidenceVisible(true);
    setMobileView("evidence");
  }, [run, runId]);
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
  const grid = useRef<HTMLDivElement>(null);
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
    if (!run?.approval) return;
    const planChangedSinceEdit =
      editBaseVersion !== null &&
      (run.planVersion !== editBaseVersion ||
        (editBasePlanId !== null && run.approval.planId !== editBasePlanId));
    if (!editingPlan) {
      setDraftQuestions(run.approval.questions.map(({ question }) => question));
      setEditBaseVersion(run.planVersion);
      setEditBasePlanId(run.approval.planId);
      if (!planStale || planChangedSinceEdit) {
        setPlanEditError("");
        setPlanStale(false);
      }
      return;
    }
    if (planChangedSinceEdit) {
      setPlanStale(true);
      setPlanEditError(
        "This plan changed in another tab. Refresh the run, review the latest questions, then edit again.",
      );
    }
  }, [
    run?.approval,
    run?.planVersion,
    editingPlan,
    editBaseVersion,
    editBasePlanId,
    planStale,
  ]);

  useEffect(() => {
    if (versionRun.current === runId) return;
    versionRun.current = runId;
    setReportVersion(null);
    setClaimFilter("all");
    setFollowupQuestion("");
    setApprovalFeedback("");
    setEditingPlan(false);
    setDraftQuestions([]);
    setPlanEditError("");
    setEditBaseVersion(null);
    setEditBasePlanId(null);
    setPlanStale(false);
    setSavedPlanVersion(null);
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
                refresh.cancel();
              }
            } catch {
              /* Keep the last valid snapshot. */
            }
            // Coalesce source bursts instead of refetching the full report per event.
            refresh.schedule(refreshDelay);
          };
          stream.onerror = () => {
            // Native EventSource reconnects; refresh once to catch a missed terminal event.
            if (
              active &&
              terminalSnapshot.current?.runId !== runId &&
              !refresh.scheduled
            )
              refresh.schedule(1000);
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
          refresh.schedule(delay);
        }
      }
    };
    const refresh = createSnapshotRefresh(() => void load());
    void load();
    return () => {
      active = false;
      controller.abort();
      refresh.cancel();
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
          ? `?maxWallClockMs=${retryDeadline(run)}`
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
      planSaving ||
      planVersionConflict ||
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
      // Retire the decided plan locally so its controls cannot be submitted twice
      // while the refreshed run is loading.
      setRun((previous) =>
        previous?.approval
          ? {
              ...previous,
              status: decision === "approve" ? "queued" : "cancelled",
              updatedAt: new Date().toISOString(),
              approval: {
                ...previous.approval,
                state: decision,
                // Close the wait locally so the clock resumes before the refresh.
                waitedMs:
                  (previous.approval.waitedMs ?? 0) +
                  (previous.approval.waitStartedAt
                    ? Math.max(
                        0,
                        Date.now() -
                          Date.parse(previous.approval.waitStartedAt),
                      )
                    : 0),
                waitStartedAt: null,
              },
            }
          : previous,
      );
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
  async function savePlanQuestions() {
    const approval = run?.approval;
    if (
      planSaving ||
      busy ||
      run?.status !== "awaiting_approval" ||
      approval?.state !== "pending" ||
      editBaseVersion === null ||
      editBasePlanId === null ||
      planVersionConflict
    )
      return;

    setPlanSaving(true);
    setPlanEditError("");
    try {
      const request = EditResearchPlanRequestSchema.parse({
        planId: editBasePlanId,
        expectedPlanVersion: editBaseVersion,
        questions: draftQuestions,
      });
      const response = await fetch(`/api/research/runs/${runId}/plan`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(request),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409 || response.status === 412) {
          setPlanStale(true);
          setReload((value) => value + 1);
          throw new Error(
            "This plan was updated elsewhere. Refresh the run and review the latest questions before saving again.",
          );
        }
        const detail =
          typeof body.error === "string"
            ? body.error
            : typeof body.detail === "string"
              ? body.detail
              : "The edited plan could not be saved. Check the question count and wording, then try again.";
        throw new Error(detail);
      }
      const updated = EditResearchPlanResponseSchema.parse(body);
      if (
        updated.runId !== runId ||
        updated.planId === editBasePlanId ||
        updated.planVersion !== editBaseVersion + 1 ||
        updated.status !== "awaiting_approval"
      ) {
        throw new Error(
          "The saved plan response did not match this run. Refresh and review the current plan.",
        );
      }
      setDraftQuestions(updated.questions.map(({ question }) => question));
      setEditingPlan(false);
      setEditBaseVersion(updated.planVersion);
      setEditBasePlanId(updated.planId);
      setSavedPlanVersion(updated.planVersion);
      setApprovalFeedback(
        "Plan updated. Review the questions before approving.",
      );
      setReload((value) => value + 1);
    } catch (cause) {
      setPlanEditError(
        cause instanceof Error
          ? cause.message
          : "The edited plan could not be saved. Please try again.",
      );
    } finally {
      setPlanSaving(false);
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
  const markdown = reportDisplayMarkdown(
    run?.report?.markdown.split(/^## Sources\s*$/im)[0] ?? "",
  );
  const sections = useMemo(() => reportSections(markdown), [markdown]);
  const refs = useMemo(
    () => referenceMap(run?.report?.markdown ?? "", run?.sources ?? []),
    [run?.report?.markdown, run?.sources],
  );
  const references = useMemo(
    () =>
      parseSourceList(run?.report?.markdown ?? "").map((item) => {
        const source = refs.get(item.number);
        return {
          number: item.number,
          title: source?.title || item.title,
          url: source?.url ?? item.url,
          publisher: source?.assessment?.publisher,
          publishedAt: source?.assessment?.publishedAt,
          retrievedAt: source?.assessment?.retrievedAt,
          sourceId: source?.id,
        };
      }),
    [run?.report?.markdown, refs],
  );
  function citationPreview(number: number): CitationPreviewData | null {
    const source = refs.get(number);
    if (!source) return null;
    const published = (run?.claimChecks ?? []).filter(
      (claim) => claim.publishedInReport !== false,
    );
    const citations = published.flatMap((claim) =>
      claim.citations.filter((citation) => citation.sourceId === source.id),
    );
    const best =
      citations.find((citation) => citation.exactSpanVerified) ?? citations[0];
    const publishedAt = source.assessment?.publishedAt;
    return {
      title: source.title || domain(source.url),
      site: source.assessment?.publisher || domain(source.url),
      kind:
        source.sourceClass === "unknown"
          ? "Web source"
          : source.sourceClass.charAt(0).toUpperCase() +
            source.sourceClass.slice(1),
      published: publishedAt ? publicationLabel(publishedAt) : null,
      quote: best?.quote ?? null,
      verified: best?.exactSpanVerified ?? false,
      claims: published.filter((claim) =>
        claim.citations.some((citation) => citation.sourceId === source.id),
      ).length,
    };
  }
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
  const layout = useEvidenceLayout(grid, panel, Boolean(run));
  const sourceRows = useMemo<SourceRow[]>(() => {
    const numbers = new Map(
      Array.from(refs, ([number, source]) => [source.id, number]),
    );
    const published = (run?.claimChecks ?? []).filter(
      (claim) => claim.publishedInReport !== false,
    );
    return visibleSources.map((source) => {
      const extracts = published
        .flatMap((claim) => claim.citations)
        .filter((citation) => citation.sourceId === source.id && citation.quote)
        .sort(
          (a, b) => Number(b.exactSpanVerified) - Number(a.exactSpanVerified),
        )
        .map((citation) => ({
          id: citation.id,
          quote: citation.quote,
          verified: citation.exactSpanVerified,
        }));
      return {
        id: source.id,
        title: source.title || domain(source.url),
        url: safeUrl(source.url),
        domain: domain(source.url),
        citation: numbers.get(source.id) ?? null,
        publisher: source.assessment?.publisher ?? null,
        publishedAt: source.assessment?.publishedAt ?? null,
        kind:
          source.sourceClass === "unknown"
            ? "Web source"
            : source.sourceClass.charAt(0).toUpperCase() +
              source.sourceClass.slice(1),
        repeated: (source.assessment?.sameMaterialCount ?? 0) > 1,
        extracts,
      };
    });
  }, [visibleSources, refs, run?.claimChecks]);
  const activePhase = run ? runPhaseIndex(run.status) : -1;
  const planQuestionLimit = Math.min(8, run?.approval?.maxQuestions ?? 8);
  const planVersionConflict =
    planStale ||
    (savedPlanVersion !== null && (run?.planVersion ?? 0) < savedPlanVersion) ||
    (editingPlan &&
      editBaseVersion !== null &&
      (run?.planVersion !== editBaseVersion ||
        (editBasePlanId !== null && run?.approval?.planId !== editBasePlanId)));
  const planQuestionsValid = EditResearchPlanRequestSchema.safeParse({
    planId: run?.approval?.planId ?? "00000000-0000-4000-8000-000000000000",
    expectedPlanVersion: run?.planVersion ?? 0,
    questions: draftQuestions,
  }).success;
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
  const selectCitationRef = useRef(selectCitation);
  useEffect(() => {
    selectCitationRef.current = selectCitation;
  });
  // Memoised so polling and layout measurement never remount citation chips.
  const reportBody = useMemo(
    () => (
      <ReactMarkdown
        remarkPlugins={[
          remarkGfm,
          [remarkMath, { singleDollarTextMath: false }],
          remarkCitations,
          remarkAnswerSections,
        ]}
        rehypePlugins={[
          [
            rehypeKatex,
            {
              throwOnError: false,
              strict: "ignore",
              trust: false,
              maxExpand: 200,
              maxSize: 20,
            },
          ],
        ]}
        components={{
          a: ({ href, children }) =>
            href?.startsWith("#source-") ? (
              <button
                className="citation-chip"
                data-ref={href.slice(8)}
                aria-label={`Open source ${href.slice(8)}`}
                onClick={(event) =>
                  selectCitationRef.current(
                    Number(href.slice(8)),
                    event.currentTarget,
                  )
                }
              >
                {children}
              </button>
            ) : (
              <a href={safeUrl(href ?? "")} target="_blank" rel="noreferrer">
                {children}
              </a>
            ),
          table: ({ children, node }) => (
            <ReportTable node={node}>{children}</ReportTable>
          ),
        }}
      >
        {markdown}
      </ReactMarkdown>
    ),
    [markdown],
  );
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
  const documentResult = useMemo(
    () => ReportDocumentV1Schema.safeParse(run?.report?.document),
    [run?.report?.document],
  );
  const reportDocument = documentResult.success ? documentResult.data : null;
  const stopped = run?.status === "failed" || run?.status === "cancelled";
  const limitedReport =
    run?.status === "completed" &&
    run.report &&
    hasNoVerifiedFindings(reportDocument, run.claimChecks);
  useEffect(() => {
    if (run)
      publishResearchHistory({
        runId: run.runId,
        status: run.status,
        sourceCount: run.sourceCount,
      });
  }, [run?.runId, run?.status, run?.sourceCount]);
  const working =
    run && !terminal.includes(run.status) && run.status !== "awaiting_approval";
  const settledInsights = run?.insights
    ? settleInsights(run.insights, run.status)
    : null;

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
              <SaveToLibrary
                key={`save-${run.report.id}`}
                reportId={run.report.id}
              />
              <ReportActions
                key={`actions-${run.report.id}`}
                reportId={run.report.id}
              />
              <Link
                className="text-button toolbar-action"
                href={`/research/compare?leftReportId=${encodeURIComponent(run.report.id)}`}
                aria-label="Compare with another report"
              >
                <Icon name="columns" size={16} />
                <span className="toolbar-label">Compare</span>
              </Link>
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
                className="text-button toolbar-action"
                onClick={() => window.print()}
                aria-label="Print or save report as PDF"
              >
                <Icon name="print" size={16} />
                <span className="toolbar-label">PDF</span>
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
                    ? "Research finished—answer not established"
                    : run.status === "completed" &&
                        reportDocument?.quality.status === "partial"
                      ? "Research finished — review coverage"
                      : runStage(run.status)}
              </strong>
              <p>
                {error
                  ? `${error} Last recorded state: ${runStage(run.status)}.`
                  : run.status === "failed"
                    ? `${runFailure(run.errorCode)} ${sourceLabel(run.sourceCount).replace(" source", " collected source")} ${run.sourceCount === 1 ? "remains" : "remain"} available.`
                    : run.status === "cancelled"
                      ? "This run was stopped. Collected evidence is preserved."
                      : run.status === "awaiting_approval"
                        ? "Review the plan below to continue. Waiting here does not use the active-time budget."
                        : run.status === "completed"
                          ? limitedReport
                            ? "No findings passed the evidence checks. Collected sources are available; review Checks and research gaps to choose a follow-up question."
                            : reportDocument?.quality.status === "partial"
                              ? "Evidence-checked findings are ready. Answer completeness has not been established; review requirements and limitations."
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
                      ? `Retry · ${retryDeadline(run) / 60_000}-min limit`
                      : "Start fresh attempt"}
                </Button>
                <small>New run; provider costs may apply.</small>
              </div>
            ) : (
              <span>{sourceLabel(run.sourceCount)}</span>
            )}
            {working ? (
              <div className="run-busy-track" aria-hidden="true">
                <span />
              </div>
            ) : null}
          </section>
          <div
            ref={grid}
            className="report-grid"
            data-mobile-view={mobileView}
            data-evidence-visible={evidenceVisible}
            data-evidence-wide={layout.wide || undefined}
            style={
              {
                "--evidence-width": `${layout.width}px`,
              } as CSSProperties
            }
          >
            <div
              ref={report}
              className="report-scroll"
              data-answer-ready={run.report ? true : undefined}
            >
              <header className="report-header">
                <div className="report-meta">
                  <Status status={run.status} />
                  <span>{sourceLabel(run.sourceCount)}</span>
                  <span>{dateLabel(run.createdAt)}</span>
                  <RunClock
                    startedAt={run.createdAt}
                    endedAt={
                      terminal.includes(run.status)
                        ? (run.updatedAt ?? run.report?.publishedAt)
                        : undefined
                    }
                    pausedMs={run.approval?.waitedMs}
                    pausedSince={run.approval?.waitStartedAt}
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
              {run.report && (
                <section
                  className="desk-composer report-quality"
                  data-quality={
                    reportDocument?.quality.status ?? "not_assessed"
                  }
                  aria-labelledby="answer-quality-title"
                >
                  <h2 id="answer-quality-title">
                    {limitedReport
                      ? "Answer not established"
                      : reportDocument?.quality.status === "answered"
                        ? "Answer assessed"
                        : reportDocument
                          ? "Partial answer — review coverage"
                          : "Coverage not assessed"}
                  </h2>
                  <p className="desk-help">
                    {limitedReport
                      ? "The collected evidence does not yet support a verified answer to this question. Review the recorded checks before continuing the investigation."
                      : (reportDocument?.quality.reason ??
                        "This historical report has no structured coverage assessment. Its existing evidence checks remain available.")}
                  </p>
                  {limitedReport && (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setMobileView("evidence");
                        setEvidenceVisible(true);
                        changeTab("checks");
                      }}
                    >
                      Review evidence checks
                    </Button>
                  )}
                  {reportDocument && (
                    <details>
                      <summary>Question and report requirements</summary>
                      <p className="desk-help">
                        Evidence links are not proof that a requirement is fully
                        satisfied.
                      </p>
                      <ul>
                        {reportDocument.requirements.map((requirement) => (
                          <li key={requirement.id}>
                            <strong>{requirement.text}</strong>
                            {" — "}
                            {requirement.status === "addressed"
                              ? "Evidence linked; completeness not established"
                              : "Unresolved"}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </section>
              )}
              <div className="research-signal" aria-label="Research overview">
                <div>
                  <span>Evidence collected</span>
                  <strong>
                    {run.sourceCount}
                    <small>
                      {run.sourceLimit !== undefined &&
                      run.sourceCount <= run.sourceLimit
                        ? ` / ${run.sourceLimit}`
                        : run.sourceCount === 1
                          ? " source"
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
                  <span>
                    {limitedReport
                      ? "Verified findings"
                      : run.report
                        ? "Reading time"
                        : "Current step"}
                  </span>
                  <strong>
                    {limitedReport
                      ? "0"
                      : run.report
                        ? `${readingMinutes(markdown)} min`
                        : run.status === "awaiting_approval"
                          ? "Review plan"
                          : runStage(run.status)}
                  </strong>
                </div>
              </div>
              {approvalFeedback &&
              ["planning", "queued", "awaiting_approval"].includes(
                run.status,
              ) ? (
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
                  {!!run.reportRequirements?.length && (
                    <details>
                      <summary>Requested report requirements</summary>
                      <ul>
                        {run.reportRequirements.map((requirement, index) => (
                          <li key={index}>{requirement}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {editingPlan ? (
                    <div className="desk-plan-editor" aria-busy={planSaving}>
                      <p className="desk-help">
                        Edit the questions this run will investigate. Changes
                        are saved to this plan before approval.
                      </p>
                      <ol>
                        {draftQuestions.map((question, index) => (
                          <li
                            key={`${index}-${run.approval?.questions[index]?.id ?? "new"}`}
                          >
                            <label htmlFor={`plan-question-${index}`}>
                              Question {index + 1}
                            </label>
                            <textarea
                              id={`plan-question-${index}`}
                              value={question}
                              minLength={5}
                              maxLength={1000}
                              rows={3}
                              disabled={planSaving || busy}
                              onChange={(event) =>
                                setDraftQuestions((current) =>
                                  current.map((item, itemIndex) =>
                                    itemIndex === index
                                      ? event.target.value
                                      : item,
                                  ),
                                )
                              }
                            />
                            <Button
                              type="button"
                              variant="quiet"
                              disabled={
                                planSaving || busy || draftQuestions.length <= 1
                              }
                              aria-label={`Remove question ${index + 1}`}
                              onClick={() =>
                                setDraftQuestions((current) =>
                                  current.filter(
                                    (_, itemIndex) => itemIndex !== index,
                                  ),
                                )
                              }
                            >
                              Remove
                            </Button>
                          </li>
                        ))}
                      </ol>
                      <p className="desk-help" aria-live="polite">
                        {draftQuestions.length} of {planQuestionLimit} questions
                        · Each question must be 5–1,000 characters.
                      </p>
                      {planEditError ? (
                        <div role="alert" className="desk-error">
                          <p>{planEditError}</p>
                          {planStale ? (
                            <Button
                              type="button"
                              variant="outline"
                              disabled={planSaving || busy}
                              onClick={() => setReload((value) => value + 1)}
                            >
                              Refresh latest plan
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                      <div className="desk-inline-actions">
                        <Button
                          type="button"
                          variant="outline"
                          disabled={
                            planSaving ||
                            busy ||
                            draftQuestions.length >= planQuestionLimit
                          }
                          onClick={() =>
                            setDraftQuestions((current) => [...current, ""])
                          }
                        >
                          Add question
                        </Button>
                        <Button
                          type="button"
                          variant="quiet"
                          disabled={planSaving || busy}
                          onClick={() => {
                            setDraftQuestions(
                              run.approval?.questions.map(
                                ({ question }) => question,
                              ) ?? [],
                            );
                            setEditBaseVersion(run.planVersion);
                            setEditBasePlanId(run.approval?.planId ?? null);
                            setPlanEditError("");
                            if (
                              run.planVersion !== editBaseVersion ||
                              run.approval?.planId !== editBasePlanId
                            )
                              setPlanStale(false);
                            else if (planStale) setReload((value) => value + 1);
                            setEditingPlan(false);
                          }}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          disabled={
                            planSaving ||
                            busy ||
                            !planQuestionsValid ||
                            planVersionConflict
                          }
                          onClick={() => void savePlanQuestions()}
                        >
                          {planSaving ? "Saving plan…" : "Save questions"}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <ol>
                        {run.approval.questions.map((question) => (
                          <li key={question.id}>{question.question}</li>
                        ))}
                      </ol>
                      {planEditError ? (
                        <div role="alert" className="desk-error">
                          <p>{planEditError}</p>
                          {planStale ? (
                            <Button
                              type="button"
                              variant="outline"
                              disabled={busy}
                              onClick={() => setReload((value) => value + 1)}
                            >
                              Refresh latest plan
                            </Button>
                          ) : null}
                        </div>
                      ) : null}
                      {run.approval.editable ? (
                        <div className="desk-inline-actions">
                          <Button
                            type="button"
                            variant="outline"
                            disabled={busy || planSaving || planStale}
                            onClick={() => {
                              setDraftQuestions(
                                run.approval?.questions.map(
                                  ({ question }) => question,
                                ) ?? [],
                              );
                              setEditBaseVersion(run.planVersion);
                              setEditBasePlanId(run.approval?.planId ?? null);
                              setPlanEditError("");
                              setPlanStale(false);
                              setEditingPlan(true);
                            }}
                          >
                            Edit questions
                          </Button>
                        </div>
                      ) : null}
                    </>
                  )}
                  <div className="desk-inline-actions">
                    <Button
                      variant="outline"
                      disabled={busy || planSaving || planVersionConflict}
                      onClick={() => void decidePlan("reject")}
                    >
                      {approvalDecision === "reject"
                        ? "Rejecting…"
                        : "Reject plan"}
                    </Button>
                    <Button
                      disabled={busy || planSaving || planVersionConflict}
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
                data-stopped={stopped || undefined}
              >
                {runPhases.map((phase, index) => {
                  const done =
                    run.status === "completed" ||
                    (activePhase >= 0 && index < activePhase);
                  const current = !done && index === activePhase;
                  const last = index === runPhases.length - 1;
                  return (
                    <span
                      key={phase}
                      className={
                        done ? "phase-done" : current ? "phase-current" : ""
                      }
                      aria-current={current ? "step" : undefined}
                    >
                      <i>
                        {done ? <Icon name="check" size={12} /> : index + 1}
                      </i>
                      {last && stopped
                        ? run.status === "cancelled"
                          ? "Stopped"
                          : "Failed"
                        : labels[index]}
                    </span>
                  );
                })}
              </div>
              {settledInsights && (
                <details className="report-orchestration">
                  <summary>
                    <OrchestrationSummary insights={settledInsights} />
                  </summary>
                  <h2 className="sr-only">Live orchestration</h2>
                  <ExecutionView
                    insights={settledInsights}
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
                <article className="report-article" id="report-article">
                  {!limitedReport && sections.length > 1 && (
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
                  {limitedReport ? (
                    <details>
                      <summary>Collected sources ({run.sourceCount})</summary>
                      <ReferenceList
                        references={references}
                        onOpen={selectCitation}
                      />
                    </details>
                  ) : (
                    <>
                      {reportBody}
                      <ReferenceList
                        references={references}
                        onOpen={selectCitation}
                      />
                    </>
                  )}
                  <div className="report-end">
                    <span className="end-mark">
                      <Icon
                        name={limitedReport ? "layers" : "check"}
                        size={15}
                      />
                    </span>
                    <span>
                      {limitedReport
                        ? "Evidence record preserved"
                        : "End of research brief"}
                    </span>
                    <span className="report-end-actions">
                      <button
                        type="button"
                        className="answer-icon"
                        onClick={() => void copyReport()}
                        aria-label="Copy answer"
                        title="Copy answer"
                      >
                        <Icon name="copy" size={15} />
                      </button>
                      <button
                        type="button"
                        className="answer-icon"
                        onClick={downloadReport}
                        aria-label="Download answer as Markdown"
                        title="Download Markdown"
                      >
                        <Icon name="download" size={15} />
                      </button>
                    </span>
                    <span>{sourceLabel(run.sourceCount)} collected</span>
                  </div>
                </article>
              ) : !stopped && run.status !== "awaiting_approval" ? (
                <div className="report-pending">
                  <ResearchActivity status={run.status} events={run.events} />
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
              {run.report &&
                run.insights &&
                (limitedReport ? (
                  <details>
                    <summary>
                      Review {run.insights.gaps.length} research gaps
                    </summary>
                    <GapView
                      gaps={run.insights.gaps}
                      busy={busy}
                      investigate={(question, gapId) =>
                        void investigate(question, gapId)
                      }
                    />
                  </details>
                ) : (
                  <GapView
                    gaps={run.insights.gaps}
                    busy={busy}
                    investigate={(question, gapId) =>
                      void investigate(question, gapId)
                    }
                  />
                ))}
              {run.status === "completed" && (
                <form
                  className="report-followup"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void investigate(followupQuestion);
                  }}
                >
                  <FollowupSuggestions
                    suggestions={followupSuggestions({
                      gaps: limitedReport ? undefined : run.insights?.gaps,
                      questionCoverage:
                        reportDocument?.questionCoverage ??
                        (limitedReport
                          ? run.subQuestions.map((item) => ({
                              text: item.question,
                              status: "unresolved",
                            }))
                          : undefined),
                    })}
                    disabled={busy}
                    choose={(question) => {
                      setFollowupQuestion(question.slice(0, 1000));
                      const field =
                        document.getElementById("followup-question");
                      field?.focus({ preventScroll: true });
                      field?.scrollIntoView({
                        block: "nearest",
                        behavior: window.matchMedia(
                          "(prefers-reduced-motion: reduce)",
                        ).matches
                          ? "instant"
                          : "smooth",
                      });
                    }}
                  />
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
            {evidenceVisible && (
              <EvidenceResizer
                grid={grid}
                panelWidth={layout.panelWidth}
                gridWidth={layout.gridWidth}
                onCommit={layout.commit}
              />
            )}
            <aside
              id="research-evidence"
              className="evidence-panel"
              ref={panel}
              aria-label="Research evidence"
            >
              <EvidencePresets
                active={layout.preset}
                onPreset={layout.applyPreset}
                onCollapse={() => setEvidenceVisible(false)}
              />
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
                        <SaveToLibrary
                          key={selected.id}
                          sourceId={selected.id}
                        />
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
                        {layout.wide ? (
                          <SourcesTable
                            rows={sourceRows}
                            activeSource={activeSource}
                            onSelect={setActiveSource}
                          />
                        ) : (
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
                                    <strong>
                                      {source.title || source.url}
                                    </strong>
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
                                      source.assessment.sameMaterialCount >
                                        1 && (
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
                        )}
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
                    <MethodSummary
                      sources={run.sources}
                      subQuestions={run.subQuestions}
                      calls={run.usage.searchCalls}
                      callLimit={
                        run.budget.maxProviderOperations ??
                        run.budget.maxSearchCalls
                      }
                      statusLabel={(status) => <Status status={status} />}
                      inspect={(id) => {
                        setActiveSource(id);
                        changeTab("sources");
                      }}
                    />
                    {settledInsights && (
                      <ExecutionView
                        insights={settledInsights}
                        inspectSource={(id) => {
                          setActiveSource(id);
                          changeTab("sources");
                        }}
                      />
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
          <CitationPreview root={report} resolve={citationPreview} />
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
