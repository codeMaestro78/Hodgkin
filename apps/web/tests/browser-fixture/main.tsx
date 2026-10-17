/** Isolated test app only. No production route, auth bypass, or real provider requests. */
import { createRoot } from "react-dom/client";
import { usePathname } from "./navigation";
import Composer from "../../app/(research)/research/page";
import Report from "../../app/(research)/research/[runId]/page";
import Reports from "../../app/(research)/research/reports/page";
import { OnboardingFlow } from "../../app/components/onboarding-flow";
import { readOnboarding } from "../../lib/onboarding";
import { backendReportMarkdown } from "./backend-report";
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
const ago = (seconds: number) =>
  new Date(Date.now() - seconds * 1000).toISOString();
const stagedTask = (
  id: string,
  nodeId: string,
  name: string,
  status: string,
  start: number,
  end: number | null,
  extra: Record<string, unknown> = {},
) => ({
  id,
  nodeId,
  name,
  status,
  attempt: 1,
  startedAt: ago(start),
  completedAt: end === null ? null : ago(end),
  errorCode: null,
  sourceIds: [],
  dependsOn: [],
  ...extra,
});
/** Three populated stages, a failed collector and one coverage-repair loop. */
const stagedTasks = [
  stagedTask("staged-intake", "intake", "intake", "completed", 58, 57),
  stagedTask("staged-plan", "planner", "planner", "completed", 57, 52, {
    dependsOn: ["intake"],
  }),
  stagedTask(
    "staged-filings",
    "research_task",
    "Search regulatory filings",
    "failed",
    50,
    41,
    { errorCode: "provider_unavailable", dependsOn: ["planner"] },
  ),
  stagedTask(
    "staged-evidence",
    "research_task",
    "Find original evidence",
    "completed",
    50,
    38,
    { sourceIds: ["source-a"], dependsOn: ["planner"] },
  ),
  stagedTask("staged-reflect", "reflector", "reflector", "completed", 37, 33, {
    dependsOn: ["research_task"],
  }),
  stagedTask(
    "staged-repair",
    "planner_delta",
    "planner_delta",
    "completed",
    33,
    30,
    { dependsOn: ["reflector"] },
  ),
  stagedTask("staged-verify", "verifier", "verifier", "running", 12, null, {
    attempt: 2,
    dependsOn: ["reflector"],
  }),
];
const awaiting = state === "awaiting_approval";
const fixtureShares: {
  id: string;
  createdAt: string;
  expiresAt: string;
  revokedAt: string | null;
}[] = [];
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
  // Ran 20s, then has waited 40s for a plan decision.
  approval: awaiting
    ? {
        planId: "22222222-2222-4222-8222-222222222222",
        state: "pending",
        editable: false,
        planVersion: 1,
        maxQuestions: 6,
        questions: [
          { id: "q1", question: "Which evidence supports the report?" },
        ],
        waitedMs: 0,
        waitStartedAt: ago(40) as string | null,
      }
    : null,
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
    tasks:
      options.get("tasks") === "staged"
        ? stagedTasks
        : [
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
              completedAt:
                state === "completed" ? new Date().toISOString() : null,
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
/** Answer-first layout: lead, table, limitations, methodology, references. */
if (
  state === "completed" &&
  (options.get("answer") === "rich" || options.get("answer") === "backend")
) {
  const richSource = (
    sourceId: string,
    title: string,
    url: string,
    provider: string,
    publisher: string,
    publishedAt: string | null,
    paths: { subQuestionId: string; provider: string }[],
  ) => ({
    ...source,
    id: sourceId,
    title,
    url,
    provider,
    assessment: {
      ...source.assessment,
      publisher,
      publishedAt,
      retrievedAt: "2026-03-14T09:20:00Z",
      sameMaterialCount: 1,
    },
    discoveryPaths: paths.map((path) => ({ ...path, url })),
  });
  const sources = [
    richSource(
      "source-a",
      "Provenance tracking in retrieval-augmented systems",
      "https://www.provenance-lab.test/papers/tracking",
      "openalex",
      "Provenance Lab",
      "2024-06-11T00:00:00Z",
      [
        { subQuestionId: "question-a", provider: "openalex" },
        { subQuestionId: "question-b", provider: "openalex" },
      ],
    ),
    richSource(
      "source-b",
      "Why do readers trust cited answers?",
      "https://journal.reading-trust.test/articles/417",
      "semantic_scholar",
      "Journal of Reading Trust",
      "2023-09-02T00:00:00Z",
      [{ subQuestionId: "question-a", provider: "semantic_scholar" }],
    ),
    richSource(
      "source-c",
      "Span-level citation verification",
      "https://verify-notes.test/span-checks",
      "tavily",
      "verify-notes.test",
      null,
      [{ subQuestionId: "question-b", provider: "tavily" }],
    ),
  ];
  const richFinding = "44444444-4444-4444-8444-444444444444";
  const richMarkdown = [
    "## Executive summary",
    "Connect every published claim to a preserved, quoted passage, and show that passage where the claim is read. [1] Readers rely on citations most when they can check the exact span without leaving the answer. [2]",
    "## Comparison of approaches",
    "| Approach | Inspectable | Reader effort |\n| --- | --- | --- |\n| Exact quoted span | Yes [1] | Low [2] |\n| Page-level link | Partly [3] | High |",
    "## Implementation and decision implications",
    "Verify spans when the report is written, not when it is read. [3] Checking cost about $4 per report against $9 for manual review.",
    "| Verification | Span match rate | Reader checks |\n| --- | --- | --- |\n| Exact span | 91.4% [3] | 1,204 |\n| Sentence window | 63.8% | 846 |\n| Page link | 22.5% [2] | 311 |",
    "Precision is reported as $$P = \\frac{TP}{TP + FP}$$ over verified spans.",
    "$$\nF_1 = \\frac{2PR}{P + R}\n$$",
    "## Limitations",
    "Only three sources met the inclusion threshold, and none measured reader trust over time.",
    "## Methodology",
    "Two research questions were searched across three providers.",
    "## Sources",
    "1. [Provenance tracking in retrieval-augmented systems](https://www.provenance-lab.test/papers/tracking)",
    "2. [Why do readers trust cited answers?](https://journal.reading-trust.test/articles/417)",
    "3. [Span-level citation verification](https://verify-notes.test/span-checks)",
  ].join("\n\n");
  const markdown =
    options.get("answer") === "backend" ? backendReportMarkdown : richMarkdown;
  Object.assign(body, {
    sourceCount: sources.length,
    sources,
    usage: { searchCalls: 4 },
    insights: {
      ...body.insights,
      providerCalls: ["openalex", "openalex", "semantic_scholar", "tavily"].map(
        (provider) => ({ provider, operation: "search", outcome: "succeeded" }),
      ),
      gaps: [
        {
          ...body.insights.gaps[0],
          suggestedQuery: "Measure reader trust in cited answers over time",
        },
      ],
    },
    subQuestions: [
      {
        id: "question-a",
        question: "Which evidence links make answers inspectable?",
        status: "complete",
      },
      {
        id: "question-b",
        question: "How are quoted spans verified before publication?",
        status: "complete",
      },
    ],
    report: {
      ...body.report,
      markdown,
      document: {
        version: 1,
        assessmentVersion: "evidence-links-v1",
        mode: "balanced",
        title: body.originalQuestion,
        sections: [
          "overview",
          "mechanisms",
          "comparison",
          "risks",
          "implications",
        ].map((sectionId) => ({
          id: sectionId,
          title: sectionId,
          claimIds: sectionId === "overview" ? [richFinding] : [],
        })),
        findings: [
          {
            id: richFinding,
            text: "Each claim should remain connected to evidence.",
            section: "overview",
            citationIds: ["55555555-5555-4555-8555-555555555555"],
            sourceIds: ["66666666-6666-4666-8666-666666666666"],
          },
        ],
        requirements: [
          {
            id: "question",
            origin: "main_question",
            text: body.originalQuestion,
            status: "unresolved",
            claimIds: [],
            basis: "not_established",
          },
        ],
        questionCoverage: [
          {
            id: "77777777-7777-4777-8777-777777777777",
            text: "Does span verification change long-term reader trust?",
            status: "unresolved",
            claimIds: [],
            basis: "not_established",
          },
        ],
        quality: {
          status: "partial",
          reason: "Evidence is linked; long-term reader trust is not covered.",
          verifiedFindings: 1,
          excludedFindings: 0,
        },
      },
    },
    claimChecks: [
      {
        ...body.claimChecks[0],
        citations: [
          {
            ...body.claimChecks[0]!.citations[0],
            quote:
              "Each claim retains a pointer to the passage that supports it.",
          },
        ],
      },
      {
        ...body.claimChecks[0],
        id: "claim-c",
        claim: "Readers check citations they can see in place.",
        supportingSourceIds: ["source-b"],
        citations: [
          {
            id: "citation-b",
            sourceId: "source-b",
            quote: "Readers opened inline evidence four times as often.",
            exactSpanVerified: false,
            verdict: "supports",
            context: "Readers opened inline evidence four times as often.",
          },
        ],
      },
      body.claimChecks[1],
    ],
  });
}
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
      user: {
        id: "fixture-account",
        name: "Fixture researcher",
        email: "fixture@example.test",
      },
    });
  if (url.includes("/cancel")) return Response.json({ status: "stopping" });
  if (url.includes("/retry")) return Response.json({ runId: id });
  if (url.endsWith("/approve") && body.approval) {
    const decision = JSON.parse(String(init?.body)).decision;
    (window as unknown as { fixtureDecision: unknown }).fixtureDecision =
      decision;
    // Mirror the API: the decision closes the open wait.
    body.status = decision === "approve" ? "queued" : "cancelled";
    body.updatedAt = new Date().toISOString();
    body.approval = {
      ...body.approval,
      state: decision,
      waitedMs: Date.now() - Date.parse(body.approval.waitStartedAt!),
      waitStartedAt: null,
    };
    return Response.json({ runId: id });
  }
  if (url.includes("/followups")) {
    (window as unknown as { fixtureFollowup: unknown }).fixtureFollowup =
      JSON.parse(String(init?.body));
    return Response.json(
      { detail: "Fixture investigation creation failed" },
      { status: 503 },
    );
  }
  if (/\/api\/research\/reports\/[^/]+\/shares$/.test(url)) {
    if (init?.method !== "POST") return Response.json(fixtureShares);
    const share = {
      id: `share-${fixtureShares.length + 1}`,
      createdAt: new Date().toISOString(),
      expiresAt: ago(-168 * 3600),
      revokedAt: null as string | null,
    };
    fixtureShares.push(share);
    return Response.json({
      id: share.id,
      sharePath: `/shared/fixture-token-${share.id}`,
      expiresAt: share.expiresAt,
    });
  }
  const revoke = /\/shares\/([^/]+)\/revoke$/.exec(url);
  if (revoke) {
    const share = fixtureShares.find((item) => item.id === revoke[1]);
    if (share) share.revokedAt = new Date().toISOString();
    return Response.json({ revoked: Boolean(share) });
  }
  if (/\/api\/research\/reports\/[^/]+\/exports$/.test(url)) {
    const format = JSON.parse(String(init?.body)).format;
    if (format === "bibtex")
      return Response.json(
        { error: "Fixture BibTeX export failed. Retry the export." },
        { status: 503 },
      );
    return Response.json({
      id: "export-a",
      reportId: "report-a",
      reportVersion: 2,
      format,
      sha256:
        "3f9a51c2e07d4b6a8e11f0c9d2b7a6e5c4d3b2a1908f7e6d5c4b3a291807c21e",
      sizeBytes: 4198,
      downloadPath: "/api/research/reports/report-a/exports/export-a/download",
    });
  }
  if (url.endsWith("/exports/export-a/download")) {
    (window as unknown as { fixtureDownloads: number }).fixtureDownloads =
      ((window as unknown as { fixtureDownloads?: number }).fixtureDownloads ??
        0) + 1;
    return new Response("## Direct answer\n", {
      headers: { "content-type": "text/markdown" },
    });
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
