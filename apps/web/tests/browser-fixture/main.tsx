/** Isolated test app only. No production route, auth bypass, or real provider requests. */
import { createRoot } from "react-dom/client";
import { usePathname } from "./navigation";
import Composer from "../../app/(research)/research/page";
import Report from "../../app/(research)/research/[runId]/page";
import Reports from "../../app/(research)/research/reports/page";
import { OnboardingFlow } from "../../app/components/onboarding-flow";
import { readOnboarding } from "../../lib/onboarding";
import "../../app/styles.css";
import "../../app/onboarding.css";

const options = new URLSearchParams(location.search);
const id = "11111111-1111-4111-8111-111111111111";
const state = options.get("state") ?? "completed";
const source = {
  id: "source-a",
  title: "Architecture and evidence verification",
  url: "https://example.test/evidence",
  sourceClass: "primary",
  provider: "tavily",
  assessment: {
    publisher: "example.test",
    publishedAt: null,
    retrievedAt: new Date().toISOString(),
    independenceGroup: "material-1",
    sameMaterialCount: 2,
    reasons: [
      "Publisher authority has not been independently assessed.",
      "Repeated material is not independent corroboration.",
    ],
  },
};
const body = {
  runId: id,
  status: state,
  originalQuestion:
    "How should a research platform connect answers to inspectable evidence?",
  sourceCount: state === "empty" ? 0 : 1,
  sourceLimit: 6,
  errorCode: state === "failed" ? "provider_unavailable" : null,
  createdAt: new Date(Date.now() - 60000).toISOString(),
  updatedAt: new Date().toISOString(),
  quickMode: false,
  insights: {
    schemaVersion: "1.2",
    providerCalls: [],
    parentReportId: null,
    parentRunId: null,
    followupRuns: [],
    reportVersions:
      state === "completed"
        ? [
            { id: "report-a", version: 1, createdAt: new Date().toISOString() },
            { id: "report-b", version: 2, createdAt: new Date().toISOString() },
          ]
        : [],
    gaps:
      state === "completed"
        ? [
            {
              id: "gap-a",
              description: "A material assertion has unresolved evidence",
              why: "A supporting passage was not established.",
              suggestedQuery:
                "Find primary evidence for the disputed assertion",
              status: "open",
              claimIds: ["claim-b"],
              subQuestionIds: ["question-a"],
            },
          ]
        : [],
    tasks: [
      {
        id: "task-a",
        nodeId: "planner",
        name: "Plan research",
        status: "completed",
        attempt: 1,
        startedAt: new Date().toISOString(),
        completedAt: new Date().toISOString(),
        errorCode: null,
        sourceIds: [],
        dependsOn: ["intake"],
      },
      {
        id: "task-b",
        nodeId: "research_task",
        name: "Find original evidence",
        status: state === "completed" ? "completed" : "running",
        attempt: 1,
        startedAt: new Date().toISOString(),
        completedAt: state === "completed" ? new Date().toISOString() : null,
        errorCode: null,
        sourceIds: [source.id],
        dependsOn: ["planner"],
      },
    ],
  },
  budget: { maxSearchCalls: 6, maxEstimatedCostUsd: 1 },
  usage: { searchCalls: 2 },
  report:
    state === "completed"
      ? {
          id: "report-a",
          version: 1,
          publishedAt: new Date().toISOString(),
          markdown:
            "## Direct answer\nKeep each claim connected to its preserved evidence. [1]\n\n## Findings\n" +
            "A report must remain readable while the source panel is explored.\n\n".repeat(
              25,
            ) +
            "## Limitations\nModel reviews are not guarantees of factual accuracy.\n\n## Sources\n1. [Architecture](https://example.test/evidence)",
        }
      : null,
  sources: state === "empty" ? [] : [source],
  subQuestions: [
    {
      id: "question-a",
      question: "Which evidence supports the report?",
      status: state === "completed" ? "complete" : "running",
    },
  ],
  events: [
    {
      sequence: 1,
      type: "research_worker.started",
      label: "Collecting preserved sources",
      occurredAt: new Date().toISOString(),
    },
  ],
  claimChecks:
    state === "completed"
      ? [
          {
            id: "claim-a",
            claim: "Each claim should remain connected to evidence.",
            status: "supported",
            section: "Direct answer",
            publishedInReport: true,
            supportingSourceIds: [source.id],
            contradictingSourceIds: [],
            caveats: ["This is an architectural recommendation."],
            citations: [
              {
                id: "citation-a",
                sourceId: source.id,
                quote: "Evidence must remain inspectable.",
                exactSpanVerified: true,
                verdict: "supports",
                context:
                  "Retrieved context. Evidence must remain inspectable. Additional source context.",
              },
            ],
          },
          {
            id: "claim-b",
            claim: "A draft assertion has insufficient evidence.",
            status: "insufficient_evidence",
            caveats: ["Excluded from the published report."],
            citations: [],
            supportingSourceIds: [],
            contradictingSourceIds: [],
          },
        ]
      : [],
};
const runs = Array.from({ length: 32 }, (_, i) => ({
  runId: i === 0 ? id : `fixture-${i}`,
  question:
    i === 0
      ? body.originalQuestion
      : `Research question ${i}: tracing source material and evaluating long evidence chains`,
  status: "completed",
  sourceCount: 6,
  createdAt: body.createdAt,
  quickMode: false,
  reportId: "report-a",
}));
window.fetch = async (input, init) => {
  const url = String(input);
  if (url === "/api/onboarding") {
    if (init?.method === "POST") {
      const payload = JSON.parse(String(init.body));
      (
        window as unknown as { fixtureOnboardingRequest: unknown }
      ).fixtureOnboardingRequest = payload;
      if (
        (window as unknown as { fixtureOnboardingFail?: boolean })
          .fixtureOnboardingFail
      )
        return Response.json(
          { error: "Fixture setup save failed. Retry your answers." },
          { status: 503 },
        );
      const profile = {
        ...payload.draft,
        version: 1,
        step: payload.step,
        status:
          payload.action === "complete"
            ? "completed"
            : payload.action === "skip"
              ? "skipped"
              : "in_progress",
        updatedAt: new Date().toISOString(),
      };
      sessionStorage.setItem("fixture-onboarding", JSON.stringify(profile));
      return Response.json({ profile, redirect: payload.next ?? "/research" });
    }
    return Response.json({
      profile: JSON.parse(
        sessionStorage.getItem("fixture-onboarding") ?? "null",
      ),
    });
  }
  if (url.includes("/api/auth/session"))
    return Response.json({
      user: { name: "Fixture researcher", email: "fixture@example.test" },
    });
  if (url.includes("/cancel")) return Response.json({ status: "stopping" });
  if (url.includes("/retry")) return Response.json({ runId: id });
  if (url.includes("/followups")) {
    (window as unknown as { fixtureFollowup: unknown }).fixtureFollowup =
      JSON.parse(String(init?.body));
    return Response.json(
      { detail: "Fixture investigation creation failed" },
      { status: 503 },
    );
  }
  if (url.startsWith("/api/research/runs")) {
    if (init?.method === "POST") {
      (window as unknown as { fixtureSubmission: unknown }).fixtureSubmission =
        JSON.parse(String(init.body));
      return Response.json(
        { error: "Fixture submission failure; your question is preserved." },
        { status: 503 },
      );
    }
    if (/\/runs\//.test(url))
      return Response.json(
        url.includes("reportVersion=2") && body.report
          ? {
              ...body,
              report: {
                ...body.report,
                version: 2,
                markdown:
                  "## Revised findings\nRevision two is preserved separately.\n## Sources\n1. [Architecture](https://example.test/evidence)",
              },
            }
          : body,
      );
    return Response.json({ runs: state === "empty" ? [] : runs });
  }
  return Response.json({});
};
class FixtureEventSource {
  constructor() {
    (window as unknown as { fixtureStream: unknown }).fixtureStream = this;
  }
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror = null;
  close() {}
}
(window as unknown as { EventSource: unknown }).EventSource =
  FixtureEventSource;
(window as unknown as { fixtureRun: unknown }).fixtureRun = body;
const view = options.get("view");
history.replaceState(
  {},
  "",
  view === "onboarding" || location.pathname === "/onboarding"
    ? "/onboarding"
    : view === "run"
      ? `/research/${id}`
      : view === "reports"
        ? "/research/reports"
        : options.get("setup") === "ready"
          ? "/research?setup=ready"
          : "/research",
);
function App() {
  const path = usePathname();
  if (path === "/onboarding")
    return (
      <OnboardingFlow
        initialProfile={readOnboarding({
          research_onboarding: JSON.parse(
            sessionStorage.getItem("fixture-onboarding") ?? "null",
          ),
        })}
      />
    );
  return path === "/research/reports" ? (
    <Reports />
  ) : path === "/research" ? (
    <Composer />
  ) : (
    <Report />
  );
}
createRoot(document.getElementById("root")!).render(<App />);
