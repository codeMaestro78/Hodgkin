import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  ExecutionView,
  type RunInsights,
} from "../app/components/research-insights";

function view(nodes: Array<string | { nodeId: string; status: "paused" }>) {
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
      status: typeof node === "string" ? "completed" : node.status,
      attempt: 1,
      startedAt: "2026-10-17T10:00:00Z",
      completedAt: "2026-10-17T10:00:01Z",
      errorCode: null,
      sourceIds: [],
      dependsOn: [],
    })),
  } as RunInsights;
  return renderToStaticMarkup(
    createElement(ExecutionView, { insights, inspectSource: () => {} }),
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
