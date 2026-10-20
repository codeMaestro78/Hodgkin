"use client";
import { useEffect, useState, type CSSProperties } from "react";
import type { z } from "zod";
import type { RunInsightsSchema } from "@research/contracts";
import { runFailure } from "../../lib/run-status";
import { Badge, Empty } from "./workbench-ui";
import "../orchestration.css";

export type RunInsights = z.infer<typeof RunInsightsSchema>;
type Task = RunInsights["tasks"][number];
type Status = Task["status"];

const PLAN_NODES = ["intake", "planner", "approval_gate", "planner_delta"];
const COLLECT_NODES = ["research_worker", "research_task"];
const STATUS_LABEL: Record<Status, string> = {
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  skipped: "Skipped",
};

const ENDED_TASK_STATUS: Record<string, Status> = {
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

/**
 * A run that has ended has no live tasks. A record left "running" by an
 * interrupted write takes the run's outcome so its clock stops.
 */
export function settleInsights(
  insights: RunInsights,
  runStatus: string,
): RunInsights {
  const outcome = ENDED_TASK_STATUS[runStatus];
  if (!outcome || !insights.tasks.some((task) => task.status === "running"))
    return insights;
  return {
    ...insights,
    tasks: insights.tasks.map((task) =>
      task.status === "running" ? { ...task, status: outcome } : task,
    ),
  };
}

/** Persisted node ids like "planner_delta" read better as "Planner delta". */
function taskLabel(name: string) {
  if (!/^[a-z0-9_]+$/.test(name)) return name;
  const words = name.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatDuration(ms: number) {
  const seconds = Math.max(0, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** Isolated ticking leaf so a running task never re-renders the whole graph. */
function Elapsed({ task }: { task: Task }) {
  const live = task.status === "running" && !task.completedAt;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [live]);
  if (!task.startedAt) return <>Not started</>;
  const end = task.completedAt
    ? Date.parse(task.completedAt)
    : live
      ? now
      : null;
  if (end === null) return <>Started</>;
  return <>{formatDuration(end - Date.parse(task.startedAt))}</>;
}

function StatusGlyph({ status }: { status: Status }) {
  return (
    <span className="orch-glyph" data-status={status} aria-hidden="true">
      <svg viewBox="0 0 16 16" width="16" height="16">
        <circle className="orch-glyph-track" cx="8" cy="8" r="6.5" />
        {status === "completed" && <path d="m5 8.2 2 2 4-4.4" />}
        {(status === "failed" || status === "cancelled") && (
          <path d="m5.6 5.6 4.8 4.8m0-4.8-4.8 4.8" />
        )}
        {status === "running" && (
          <circle className="orch-glyph-arc" cx="8" cy="8" r="6.5" />
        )}
        {status === "paused" && <path d="M6.5 5.5v5m3-5v5" />}
        {status === "skipped" && <path d="M5 8h6" />}
      </svg>
    </span>
  );
}

function stageState(nodes: Task[]): "idle" | "active" | "done" | "failed" {
  if (!nodes.length) return "idle";
  if (nodes.some((node) => node.status === "failed")) return "failed";
  if (nodes.every((node) => ["completed", "skipped"].includes(node.status)))
    return "done";
  if (nodes.some((node) => node.status !== "queued")) return "active";
  return "idle";
}

type TaskPresentation = {
  status: Status;
  label: string;
  timelineLabel: string;
  timelineValue: string;
  timelineDone: boolean;
};

/** Translate an approval interrupt into the run-level state it represents. */
function approvalTaskPresentation(
  task: Task,
  tasks: Task[],
  runStatus: string,
): TaskPresentation | null {
  if (task.nodeId !== "approval_gate" || task.status !== "paused") return null;

  const resumedAttempt = tasks
    .filter(
      (candidate) =>
        candidate.nodeId === task.nodeId && candidate.attempt > task.attempt,
    )
    .sort((left, right) => right.attempt - left.attempt)[0];
  if (resumedAttempt) {
    return {
      status: "completed",
      label: `Resumed · paused attempt ${task.attempt} → attempt ${resumedAttempt.attempt}`,
      timelineLabel: "Resumed",
      timelineValue: resumedAttempt.startedAt
        ? new Date(resumedAttempt.startedAt).toLocaleString()
        : `Attempt ${resumedAttempt.attempt}`,
      timelineDone: true,
    };
  }

  if (runStatus === "awaiting_approval") {
    return {
      status: "paused",
      label: `Awaiting plan approval · attempt ${task.attempt}`,
      timelineLabel: "Waiting",
      timelineValue: "Your plan decision",
      timelineDone: false,
    };
  }

  if (runStatus === "completed") {
    return {
      status: "completed",
      label: `Approval resolved · attempt ${task.attempt}`,
      timelineLabel: "Resolved",
      timelineValue: "Research continued",
      timelineDone: true,
    };
  }

  if (runStatus === "failed" || runStatus === "cancelled") {
    return {
      status: runStatus === "failed" ? "failed" : "cancelled",
      label: `Run ${runStatus} · approval attempt ${task.attempt}`,
      timelineLabel: "Run ended",
      timelineValue: `Research ${runStatus}`,
      timelineDone: true,
    };
  }

  return {
    status: "completed",
    label: `Approval recorded · attempt ${task.attempt}`,
    timelineLabel: "Next",
    timelineValue: "Research is resuming",
    timelineDone: true,
  };
}

function presentationStatus(task: Task, tasks: Task[], runStatus: string) {
  return (
    approvalTaskPresentation(task, tasks, runStatus)?.status ?? task.status
  );
}

export function OrchestrationSummary({
  insights,
  runStatus,
}: {
  insights: RunInsights;
  runStatus: string;
}) {
  const taskStatus = (task: Task) =>
    presentationStatus(task, insights.tasks, runStatus);
  const total = insights.tasks.length;
  const done = insights.tasks.filter((task) =>
    ["completed", "skipped"].includes(taskStatus(task)),
  ).length;
  const running = insights.tasks.filter(
    (task) => taskStatus(task) === "running",
  ).length;
  const failed = insights.tasks.filter(
    (task) => taskStatus(task) === "failed",
  ).length;
  return (
    <span className="orch-summary">
      <span className="orch-summary-title">
        <span
          className="orch-summary-pulse"
          data-live={running > 0}
          aria-hidden="true"
        />
        <span>Inspect live orchestration</span>
      </span>
      <span className="orch-summary-meta">
        {total} recorded {total === 1 ? "task" : "tasks"}
        {running > 0 && ` · ${running} running`}
        {failed > 0 && ` · ${failed} failed`}
        <span
          className="orch-summary-rail"
          aria-hidden="true"
          style={
            { "--orch-progress": total ? done / total : 0 } as CSSProperties
          }
        />
      </span>
      <svg
        className="orch-summary-chevron"
        viewBox="0 0 16 16"
        width="14"
        height="14"
        aria-hidden="true"
      >
        <path d="m4 6 4 4 4-4" />
      </svg>
    </span>
  );
}

export function ExecutionView({
  insights,
  runStatus,
  inspectSource,
}: {
  insights: RunInsights;
  runStatus: string;
  inspectSource: (id: string) => void;
}) {
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (window.matchMedia("(max-width: 760px)").matches) setView("list");
  }, []);
  const tasks = insights.tasks;
  const task = tasks.find((item) => item.id === selected);
  const taskPresentation = task
    ? approvalTaskPresentation(task, tasks, runStatus)
    : null;
  const groups = [
    {
      title: "Plan",
      waiting: "Waiting for the planner to record its first attempt.",
      nodes: tasks.filter((item) => PLAN_NODES.includes(item.nodeId)),
    },
    {
      title: "Collect in parallel",
      waiting: "Collection starts once the plan is set.",
      nodes: tasks.filter((item) => COLLECT_NODES.includes(item.nodeId)),
    },
    {
      title: "Assess and publish",
      waiting: "Assessment begins after collection finishes.",
      nodes: tasks.filter(
        (item) => ![...PLAN_NODES, ...COLLECT_NODES].includes(item.nodeId),
      ),
    },
  ];
  const counts = (["completed", "running", "queued", "failed"] as const).map(
    (status) => ({
      status,
      count: tasks.filter((item) =>
        status === "queued"
          ? ["queued", "paused"].includes(
              presentationStatus(item, tasks, runStatus),
            )
          : status === "failed"
            ? ["failed", "cancelled"].includes(
                presentationStatus(item, tasks, runStatus),
              )
            : presentationStatus(item, tasks, runStatus) === status,
      ).length,
    }),
  );
  const sourceTotal = new Set(tasks.flatMap((item) => item.sourceIds)).size;
  const repairs = tasks.filter(
    (item) => item.nodeId === "planner_delta" && item.status !== "queued",
  ).length;
  const requiredApproval = tasks.some(
    (item) => item.nodeId === "approval_gate" && item.status === "paused",
  );
  const published = tasks.some(
    (item) => item.nodeId === "synthesizer" && item.status === "completed",
  );
  const repairCaption =
    repairs > 0
      ? `Coverage repair returned to the planner ${repairs === 1 ? "once" : `${repairs} times`}`
      : requiredApproval
        ? "Plan approval was required; automatic coverage repair was unavailable for this run"
        : published
          ? "No coverage repair was recorded for this run"
          : "Coverage repair has not been recorded yet";
  if (!tasks.length)
    return (
      <Empty title="No execution records">
        Older runs may have activity events but no persisted task attempts.
      </Empty>
    );
  const dependencyTask = (id: string) =>
    tasks.find((item) => item.id === id) ??
    tasks.find((item) => item.nodeId === id);
  const renderTask = (item: Task, index: number) => {
    const presentation = approvalTaskPresentation(item, tasks, runStatus);
    const status = presentation?.status ?? item.status;
    return (
      <button
        key={item.id}
        type="button"
        className="execution-node"
        data-status={status}
        aria-pressed={selected === item.id}
        onClick={() => setSelected(selected === item.id ? null : item.id)}
        style={{ "--n": index } as CSSProperties}
      >
        <StatusGlyph status={status} />
        <span className="execution-node-name">{taskLabel(item.name)}</span>
        <small>
          {presentation?.label ?? (
            <>
              {STATUS_LABEL[item.status]} · <Elapsed task={item} />
              {item.attempt > 1 && ` · attempt ${item.attempt}`}
            </>
          )}
          {item.sourceIds.length > 0 &&
            ` · ${item.sourceIds.length} ${item.sourceIds.length === 1 ? "source" : "sources"}`}
        </small>
      </button>
    );
  };
  return (
    <section className="execution-view" aria-label="Recorded orchestration">
      <div className="orch-toolbar">
        <div
          className="execution-view-switch"
          role="group"
          aria-label="Execution representation"
          data-view={view}
        >
          <button
            type="button"
            aria-pressed={view === "graph"}
            onClick={() => setView("graph")}
          >
            Graph
          </button>
          <button
            type="button"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            Task list
          </button>
        </div>
        <dl className="orch-stats">
          {counts.map(({ status, count }) => (
            <div key={status} data-status={status} data-empty={count === 0}>
              <dt>{status === "queued" ? "Waiting" : STATUS_LABEL[status]}</dt>
              <dd>{count}</dd>
            </div>
          ))}
          <div data-status="sources">
            <dt>Sources</dt>
            <dd>{sourceTotal}</dd>
          </div>
        </dl>
      </div>
      <p className="desk-help">
        Persisted execution states. Collection tasks can run in parallel;
        assessment follows collection.
      </p>
      {view === "graph" ? (
        <div className="execution-graph">
          <ol className="orch-lanes">
            {groups.map((group, index) => {
              const state = stageState(
                group.nodes.map((node) => ({
                  ...node,
                  status: presentationStatus(node, tasks, runStatus),
                })),
              );
              const finished = group.nodes.filter((node) =>
                ["completed", "skipped"].includes(
                  presentationStatus(node, tasks, runStatus),
                ),
              ).length;
              return (
                <li
                  key={group.title}
                  className="execution-stage"
                  data-state={state}
                  style={{ "--n": index } as CSSProperties}
                >
                  <header>
                    <span className="orch-step">{index + 1}</span>
                    <h3>{group.title}</h3>
                    <span className="orch-stage-count">
                      {group.nodes.length
                        ? `${finished}/${group.nodes.length}`
                        : "—"}
                    </span>
                  </header>
                  <div className="orch-stage-nodes">
                    {group.nodes.length ? (
                      group.nodes.map(renderTask)
                    ) : (
                      <p className="orch-waiting">{group.waiting}</p>
                    )}
                  </div>
                  {index < groups.length - 1 && (
                    <span
                      className="orch-connector"
                      data-flow={
                        state === "done"
                          ? "done"
                          : state === "active"
                            ? "active"
                            : "idle"
                      }
                      aria-hidden="true"
                    />
                  )}
                </li>
              );
            })}
          </ol>
          <div
            className="orch-loop"
            data-taken={repairs > 0}
            aria-hidden="true"
          >
            <svg viewBox="0 0 400 28" preserveAspectRatio="none">
              <path d="M392 2 V14 Q392 24 382 24 H18 Q8 24 8 14 V6" />
              <path className="orch-loop-head" d="m3 10 5-6 5 6" />
            </svg>
            <span>{repairCaption}</span>
          </div>
        </div>
      ) : (
        <ol className="execution-list">
          {tasks.map((item, index) => (
            <li
              key={item.id}
              data-status={presentationStatus(item, tasks, runStatus)}
            >
              {renderTask(item, index)}
            </li>
          ))}
        </ol>
      )}
      {task && (
        <section
          key={task.id}
          className="execution-detail"
          aria-label="Selected task details"
        >
          <header>
            <StatusGlyph status={taskPresentation?.status ?? task.status} />
            <div>
              <h3>{taskLabel(task.name)}</h3>
              <p>
                {taskPresentation?.label ?? (
                  <>
                    {STATUS_LABEL[task.status]} · attempt {task.attempt} ·{" "}
                    <Elapsed task={task} />
                  </>
                )}
              </p>
            </div>
            <button
              type="button"
              className="orch-detail-close"
              aria-label="Close task details"
              onClick={() => setSelected(null)}
            >
              <svg
                viewBox="0 0 16 16"
                width="14"
                height="14"
                aria-hidden="true"
              >
                <path d="m4 4 8 8m0-8-8 8" />
              </svg>
            </button>
          </header>
          <ol className="orch-timeline">
            <li data-done={Boolean(task.startedAt)}>
              <span>Started</span>
              <time>
                {task.startedAt
                  ? new Date(task.startedAt).toLocaleString()
                  : "Not started"}
              </time>
            </li>
            <li
              data-done={
                taskPresentation?.timelineDone ?? Boolean(task.completedAt)
              }
            >
              <span>{taskPresentation?.timelineLabel ?? "Finished"}</span>
              <time>
                {taskPresentation?.timelineValue ??
                  (task.completedAt
                    ? new Date(task.completedAt).toLocaleString()
                    : "Not recorded")}
              </time>
            </li>
          </ol>
          <dl>
            <dt>Depends on</dt>
            <dd className="orch-deps">
              {task.dependsOn.length
                ? task.dependsOn.map((id) => {
                    const dependency = dependencyTask(id);
                    return dependency ? (
                      <button
                        key={id}
                        type="button"
                        data-status={dependency.status}
                        onClick={() => setSelected(dependency.id)}
                      >
                        {taskLabel(dependency.name)}
                      </button>
                    ) : (
                      <span key={id}>{taskLabel(id)}</span>
                    );
                  })
                : "No prior stage recorded"}
            </dd>
            <dt>Output</dt>
            <dd>
              {task.sourceIds.length
                ? `${task.sourceIds.length} collected source ${task.sourceIds.length === 1 ? "reference" : "references"}`
                : "No source output is recorded for this task."}
            </dd>
          </dl>
          {task.errorCode && (
            <p role="status" className="orch-error">
              {runFailure(task.errorCode)} Retry the entire run using its
              existing retry action; per-task restart is not available.
            </p>
          )}
          {task.sourceIds.length > 0 && (
            <div className="orch-sources">
              {task.sourceIds.map((id, index) => (
                <button
                  key={id}
                  type="button"
                  className="text-button"
                  onClick={() => inspectSource(id)}
                >
                  Inspect source {index + 1}
                </button>
              ))}
            </div>
          )}
          <details className="orch-calls">
            <summary>
              Recorded provider calls · {insights.providerCalls?.length ?? 0}
            </summary>
            <p className="desk-help">
              Run-wide tool activity, not inferred attribution to a selected
              node. Model reservations are accounted separately.
            </p>
            {insights.providerCalls?.length ? (
              <ul>
                {insights.providerCalls.map((call) => (
                  <li key={call.id} data-outcome={call.outcome}>
                    <span>{call.provider}</span>
                    <span>{call.operation}</span>
                    <span>{call.outcome}</span>
                    <time>{new Date(call.startedAt).toLocaleTimeString()}</time>
                  </li>
                ))}
              </ul>
            ) : null}
          </details>
          <p className="desk-help">
            Tool arguments and private reasoning are not shown. Source links are
            recorded outputs, not a fabricated agent summary.
          </p>
        </section>
      )}
    </section>
  );
}

export function GapView({
  gaps,
  investigate,
  busy,
}: {
  gaps: RunInsights["gaps"];
  investigate: (question: string, gapId?: string) => void;
  busy: boolean;
}) {
  return (
    <section className="research-gaps" aria-label="Research gaps">
      <h2>Open research questions</h2>
      <p className="desk-help">
        Recorded evidence and coverage limitations—not speculative claims of
        missing facts.
      </p>
      {gaps.length ? (
        gaps.map((gap) => (
          <article className="desk-claim" key={gap.id}>
            <Badge>{gap.status}</Badge>
            <h3>{gap.description}</h3>
            <p>{gap.why}</p>
            {gap.suggestedQuery && (
              <button
                className="desk-button desk-button-outline"
                disabled={busy || gap.status !== "open"}
                onClick={() => investigate(gap.suggestedQuery!, gap.id)}
              >
                {gap.status === "investigating"
                  ? "Investigation created"
                  : "Investigate gap"}
              </button>
            )}
          </article>
        ))
      ) : (
        <p>
          No unresolved gaps were recorded. This does not prove complete
          coverage.
        </p>
      )}
    </section>
  );
}
