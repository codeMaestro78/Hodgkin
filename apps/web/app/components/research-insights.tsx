"use client";
import { useEffect, useState } from "react";
import type { z } from "zod";
import type { RunInsightsSchema } from "@research/contracts";
import { Badge, Empty } from "./workbench-ui";

export type RunInsights = z.infer<typeof RunInsightsSchema>;
export function ExecutionView({
  insights,
  inspectSource,
}: {
  insights: RunInsights;
  inspectSource: (id: string) => void;
}) {
  const [view, setView] = useState<"graph" | "list">("graph");
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    if (window.matchMedia("(max-width: 760px)").matches) setView("list");
  }, []);
  const task = insights.tasks.find((item) => item.id === selected);
  const groups = [
    {
      title: "Plan",
      nodes: insights.tasks.filter((item) =>
        ["intake", "planner", "planner_delta"].includes(item.nodeId),
      ),
    },
    {
      title: "Collect in parallel",
      nodes: insights.tasks.filter((item) =>
        ["research_worker", "research_task"].includes(item.nodeId),
      ),
    },
    {
      title: "Assess and publish",
      nodes: insights.tasks.filter(
        (item) =>
          ![
            "intake",
            "planner",
            "planner_delta",
            "research_worker",
            "research_task",
          ].includes(item.nodeId),
      ),
    },
  ];
  if (!insights.tasks.length)
    return (
      <Empty title="No execution records">
        Older runs may have activity events but no persisted task attempts.
      </Empty>
    );
  const renderTask = (item: RunInsights["tasks"][number]) => (
    <button
      key={item.id}
      className="execution-node"
      data-status={item.status}
      aria-pressed={selected === item.id}
      onClick={() => setSelected(item.id)}
    >
      <span>{item.name}</span>
      <small>
        {item.status} · attempt {item.attempt}
      </small>
    </button>
  );
  return (
    <section className="execution-view" aria-label="Recorded orchestration">
      <div
        className="execution-view-switch"
        role="group"
        aria-label="Execution representation"
      >
        <button
          aria-pressed={view === "graph"}
          onClick={() => setView("graph")}
        >
          Graph
        </button>
        <button aria-pressed={view === "list"} onClick={() => setView("list")}>
          Task list
        </button>
      </div>
      <p className="desk-help">
        Persisted execution states. Collection tasks can run in parallel;
        assessment follows collection. Coverage repair loops back to the planner
        when the budget allows.
      </p>
      {view === "graph" ? (
        <div className="execution-graph">
          {groups.map((group) => (
            <section key={group.title} className="execution-stage">
              <h3>{group.title}</h3>
              <div>{group.nodes.map(renderTask)}</div>
            </section>
          ))}
        </div>
      ) : (
        <ol className="execution-list">
          {insights.tasks.map((item) => (
            <li key={item.id}>{renderTask(item)}</li>
          ))}
        </ol>
      )}
      {task && (
        <section
          className="execution-detail"
          aria-label="Selected task details"
        >
          <h3>{task.name}</h3>
          <Badge>{task.status}</Badge>
          <dl>
            <dt>Attempt</dt>
            <dd>{task.attempt}</dd>
            <dt>Started</dt>
            <dd>
              {task.startedAt
                ? new Date(task.startedAt).toLocaleString()
                : "Not started"}
            </dd>
            <dt>Finished</dt>
            <dd>
              {task.completedAt
                ? new Date(task.completedAt).toLocaleString()
                : "Not recorded"}
            </dd>
            <dt>Depends on</dt>
            <dd>
              {task.dependsOn
                .map(
                  (id) =>
                    insights.tasks.find((item) => item.id === id)?.name ?? id,
                )
                .join(", ") || "No prior stage recorded"}
            </dd>
          </dl>
          {task.errorCode && (
            <p role="status">
              {task.errorCode.replaceAll("_", " ")}. Retry the entire run using
              its existing retry action; per-task restart is not available.
            </p>
          )}
          <details className="execution-detail">
            <summary>
              Recorded provider calls · {insights.providerCalls?.length ?? 0}
            </summary>
            <p className="desk-help">
              Run-wide tool activity, not inferred attribution to a selected
              node. Model reservations are accounted separately.
            </p>
            <ul>
              {insights.providerCalls?.map((call) => (
                <li key={call.id}>
                  {call.provider} · {call.operation} · {call.outcome} ·{" "}
                  {new Date(call.startedAt).toLocaleTimeString()}
                </li>
              ))}
            </ul>
          </details>
          <p>
            {task.sourceIds.length
              ? `${task.sourceIds.length} collected source references`
              : "No source output is recorded for this task."}
          </p>
          {task.sourceIds.map((id, index) => (
            <button
              key={id}
              className="text-button"
              onClick={() => inspectSource(id)}
            >
              Inspect source {index + 1}
            </button>
          ))}
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
