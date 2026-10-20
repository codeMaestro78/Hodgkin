import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  ExecutionView,
  type RunInsights,
} from "../app/components/research-insights";

type NodeFixture =
  | string
  | {
      nodeId: string;
      status?: "paused" | "completed";
      attempt?: number;
    };

function view(nodes: NodeFixture[], runStatus = "completed") {
  const insights = {
    schemaVersion: "1.6",
    providerCalls: [],
    parentReportId: null,
    parentRunId: null,
    followupRuns: [],
    reportVersions: [],
    gaps: [],
    tasks: nodes.map((node, index) => ({
      id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      nodeId: typeof node === "string" ? node : node.nodeId,
      name: typeof node === "string" ? node : node.nodeId,
      status:
        typeof node === "string" ? "completed" : (node.status ?? "completed"),
      attempt: typeof node === "string" ? 1 : (node.attempt ?? 1),
      startedAt: `2026-10-17T10:00:0${typeof node === "string" ? 1 : (node.attempt ?? 1)}Z`,
      completedAt:
        typeof node !== "string" && node.status === "paused"
          ? null
          : "2026-10-17T10:00:02Z",
      errorCode: null,
      sourceIds: [],
      dependsOn: [],
    })),
  } as RunInsights;
  return renderToStaticMarkup(
    createElement(ExecutionView, {
      insights,
      runStatus,
      inspectSource: () => {},
    }),
  );
}

it("explains that approval-gated research did not run automatic repair", () => {
  const html = view([
    "planner",
    { nodeId: "approval_gate", status: "paused" },
    "approval_gate",
    "research_worker",
    "synthesizer",
  ]);
  expect(html).toContain(
    "Plan approval was required; automatic coverage repair was unavailable",
  );
  expect(html).not.toContain(
    "Coverage repair returns to the planner when budget allows",
  );
});

it("shows a resumed approval gate as historical, not still waiting", () => {
  const html = view(
    [
      { nodeId: "approval_gate", status: "paused", attempt: 1 },
      { nodeId: "approval_gate", status: "completed", attempt: 2 },
    ],
    "completed",
  );
  expect(html).toContain("Resumed · paused attempt 1 → attempt 2");
  expect(html).not.toContain("Paused · Started");
  expect(html).toContain('data-status="completed"');
  expect(html).toContain('data-status="queued" data-empty="true"');
});

it("resolves an old approval pause from the completed run outcome", () => {
  const html = view(
    [{ nodeId: "approval_gate", status: "paused", attempt: 1 }],
    "completed",
  );
  expect(html).toContain("Approval resolved · attempt 1");
  expect(html).not.toContain("Paused · Started");
});

it("explains that the current approval gate is waiting for the user's decision", () => {
  const html = view(
    [{ nodeId: "approval_gate", status: "paused", attempt: 1 }],
    "awaiting_approval",
  );
  expect(html).toContain("Awaiting plan approval · attempt 1");
  expect(html).not.toContain("Paused · Started");
  expect(html).toContain('data-status="queued" data-empty="false"');
});

it("does not imply repair ran when there is no recorded repair task", () => {
  const html = view([
    "planner",
    "approval_gate",
    "research_worker",
    "synthesizer",
  ]);
  expect(html).toContain("No coverage repair was recorded");
  expect(html).not.toContain("Plan approval was required");
});
