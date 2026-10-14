"use client";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { WorkspaceShell } from "../../components/workspace-shell";
import { Icon } from "../../components/ui";
import { onboardingProfileSchema } from "../../../lib/onboarding";
import {
  researchSubmission,
  type ResearchSubmission,
} from "../../../lib/research-submission";
import {
  Alert,
  Badge,
  Button,
  Field,
  FieldGroup,
  FieldLabel,
  ToggleGroup,
  ToggleGroupItem,
} from "../../components/workbench-ui";

const depths = [
  {
    name: "Focused",
    sources: 6,
    minutes: 3,
    description:
      "A decision brief with analysis, trade-offs and cited findings.",
  },
  {
    name: "Balanced",
    sources: 12,
    minutes: 5,
    description:
      "A structured comparison with mechanisms, risks and implications.",
  },
  {
    name: "Deep",
    sources: 20,
    minutes: 10,
    description:
      "A detailed investigation with broader evidence and cross-source analysis.",
  },
] as const;
const examples = [
  {
    type: "Compare options",
    question:
      "Should a startup use Tavily, Serper, or a browser agent for research?",
  },
  {
    type: "Understand a topic",
    question: "How do research agents verify claims against source material?",
  },
  {
    type: "Explore a development",
    question: "What has changed in browser-agent security during 2026?",
  },
];

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [depth, setDepth] = useState("Balanced");
  const [requireApproval, setRequireApproval] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const editedQuestion = useRef(false);
  const editedDepth = useRef(false);
  const submission = useRef<ResearchSubmission | null>(null);
  const submitting = useRef(false);
  const defaultsFrozen = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    const handoff =
      new URLSearchParams(window.location.search).get("setup") === "ready";
    void fetch("/api/onboarding", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => (response.ok ? response.json() : null))
      .then((body: { profile?: unknown } | null) => {
        if (controller.signal.aborted || defaultsFrozen.current) return;
        const profile = onboardingProfileSchema.safeParse(body?.profile).data;
        if (!profile || profile.status !== "completed") return;
        if (!editedDepth.current) setDepth(profile.depth);
        if (handoff && !editedQuestion.current) setQuestion(profile.topic);
        if (handoff)
          window.history.replaceState(window.history.state, "", "/research");
      })
      .catch(() => {
        /* Optional defaults never block the composer. */
      });
    return () => controller.abort();
  }, []);
  const scope = depths.find((item) => item.name === depth) ?? depths[1];
  const simple =
    /^(what is|who is|define|explain)\s+.+\??$/i.test(question.trim()) &&
    question.trim().length <= 160 &&
    !/\b(latest|current|today|recent|news|price|stock|law|policy|\d{4})\b/i.test(
      question,
    );
  const limit = simple ? 2 : scope.sources;

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || submitting.current) return;
    if (question.trim().length < 5) {
      setNotice(
        "Add a little more detail—your question needs at least five characters.",
      );
      textarea.current?.focus();
      return;
    }
    defaultsFrozen.current = true;
    submitting.current = true;
    setBusy(true);
    setNotice("");
    try {
      submission.current = researchSubmission(
        submission.current,
        JSON.stringify({
          question: question.trim(),
          reportRequirements: [],
          requireApproval,
          budgetOverrides: {
            maxSearchCalls: limit,
            maxWallClockMs: (simple ? 2 : scope.minutes) * 60_000,
          },
        }),
      );
      const response = await fetch("/api/research/runs", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": submission.current.key,
        },
        body: submission.current.body,
      });
      const body = (await response.json()) as {
        runId?: string;
        error?: string;
        detail?: unknown;
      };
      if (!response.ok || !body.runId)
        throw new Error(
          body.error ??
            (typeof body.detail === "string"
              ? body.detail
              : "The research couldn’t be started. Please try again."),
        );
      router.push(`/research/${body.runId}`);
    } catch (error) {
      submitting.current = false;
      setNotice(
        error instanceof Error
          ? error.message
          : "The research service is unavailable.",
      );
      setBusy(false);
    }
  }

  return (
    <WorkspaceShell title="New research">
      <div className="desk-composer-scroll">
        <header className="desk-composer-heading">
          <h1>Start a research brief.</h1>
          <p>A question worth asking. Evidence you can inspect.</p>
        </header>
        <div className="desk-composer-layout">
          <div className="desk-composer-main">
            <form
              className="desk-composer"
              onSubmit={start}
              aria-busy={busy}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  event.currentTarget.requestSubmit();
                }
              }}
            >
              <FieldGroup>
                <Field invalid={Boolean(notice)}>
                  <div className="desk-input-label">
                    <FieldLabel htmlFor="question">
                      What do you need to understand?
                    </FieldLabel>
                    <span>{question.length}/1000</span>
                  </div>
                  <textarea
                    id="question"
                    ref={textarea}
                    value={question}
                    onChange={(event) => {
                      setQuestion(event.target.value);
                      editedQuestion.current = true;
                      if (notice) setNotice("");
                    }}
                    placeholder="Ask a question, compare alternatives, or investigate a decision…"
                    maxLength={1000}
                    rows={6}
                    required
                    disabled={busy}
                    aria-invalid={Boolean(notice)}
                    aria-describedby="scope-note"
                  />
                </Field>
                <Field>
                  <span className="desk-field-label">Research depth</span>
                  <ToggleGroup
                    value={depth}
                    onChange={(value) => {
                      editedDepth.current = true;
                      setDepth(value);
                    }}
                    label="Research depth"
                  >
                    {depths.map((item) => (
                      <ToggleGroupItem key={item.name} value={item.name}>
                        <span className="depth-title">
                          {item.name}
                          <Icon
                            name={item.name === "Deep" ? "layers" : "search"}
                            size={17}
                          />
                        </span>
                        <span className="depth-description">
                          {item.description}
                        </span>
                        <span className="depth-limit">
                          Up to {item.sources} sources · {item.minutes}-minute
                          active limit
                        </span>
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                  <p id="scope-note" className="desk-help">
                    Planning, collection and verification share this active-time
                    limit; waiting for approval does not count.{" "}
                    {simple
                      ? "This evergreen question uses a fast explainer with up to two sources, regardless of the selected depth."
                      : "Limits are ceilings, not quotas. Search and extraction both count toward the provider-call budget."}
                  </p>
                </Field>
                <Field>
                  <FieldLabel htmlFor="require-approval">
                    <input
                      id="require-approval"
                      type="checkbox"
                      checked={requireApproval}
                      onChange={(event) =>
                        setRequireApproval(event.target.checked)
                      }
                      disabled={busy}
                      aria-describedby="approval-note"
                    />{" "}
                    Review the plan before research starts
                  </FieldLabel>
                  <p id="approval-note" className="desk-help">
                    Approve the proposed questions to continue, or reject the
                    plan to stop the run.
                  </p>
                </Field>
              </FieldGroup>
              {notice && <Alert>{notice}</Alert>}
              <footer className="desk-composer-footer">
                <span>
                  <kbd>Ctrl / ⌘</kbd> + <kbd>Enter</kbd> to start
                </span>
                <Button
                  type="submit"
                  disabled={busy || question.trim().length < 5}
                >
                  {busy ? (
                    <span className="motion-spinner" aria-hidden="true" />
                  ) : (
                    <Icon name="arrow" size={17} />
                  )}{" "}
                  {busy ? "Starting research…" : "Start research"}
                </Button>
              </footer>
            </form>
            <section
              className="desk-templates"
              aria-label="Research starting points"
            >
              <h2>Find a starting point</h2>
              <div>
                {examples.map((example) => (
                  <button
                    type="button"
                    key={example.type}
                    disabled={busy}
                    onClick={() => {
                      editedQuestion.current = true;
                      setQuestion(example.question);
                      setNotice("");
                      textarea.current?.focus();
                    }}
                  >
                    <strong>
                      {example.type}
                      <Icon name="arrow" size={16} />
                    </strong>
                    <span>{example.question}</span>
                  </button>
                ))}
              </div>
            </section>
          </div>
          <aside className="desk-scope" aria-label="Research scope">
            <div className="desk-scope-title">
              <Icon name="layers" size={20} />
              <h2>Research scope</h2>
            </div>
            <Badge>{simple ? "Fast explainer" : scope.name}</Badge>
            <dl>
              <div>
                <dt>Source ceiling</dt>
                <dd>{limit}</dd>
              </div>
              <div>
                <dt>Provider-call ceiling</dt>
                <dd>{limit}</dd>
              </div>
              <div>
                <dt>Search provider</dt>
                <dd>Tavily</dd>
              </div>
            </dl>
            <p>
              {simple
                ? "A compact evidence pass for an evergreen explanation."
                : scope.description}
            </p>
            <section>
              <h3>A traceable answer</h3>
              <ol>
                <li>Plan the questions to explore.</li>
                <li>Collect and preserve source material.</li>
                <li>Check quoted evidence against claims.</li>
                <li>Write the brief with references.</li>
              </ol>
            </section>
            <p className="desk-help">
              Collected sources may be fewer than the ceiling. No run-time
              estimate is shown until it can be measured reliably.
            </p>
          </aside>
        </div>
      </div>
    </WorkspaceShell>
  );
}
