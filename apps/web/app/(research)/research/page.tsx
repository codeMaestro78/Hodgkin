"use client";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { WorkspaceShell } from "../../components/workspace-shell";
import { Icon } from "../../components/ui";
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
    description: "A specific question or quick decision.",
  },
  {
    name: "Balanced",
    sources: 12,
    description: "Broader coverage and considered comparisons.",
  },
  {
    name: "Deep",
    sources: 20,
    description: "More perspectives and supporting evidence.",
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
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const textarea = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
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
    if (busy) return;
    if (question.trim().length < 5) {
      setNotice(
        "Add a little more detail—your question needs at least five characters.",
      );
      textarea.current?.focus();
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const response = await fetch("/api/research/runs", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          question: question.trim(),
          reportRequirements: [],
          budgetOverrides: { maxSearchCalls: limit },
        }),
      });
      const body = (await response.json()) as {
        runId?: string;
        error?: string;
      };
      if (!response.ok || !body.runId)
        throw new Error(
          body.error ?? "The research couldn’t be started. Please try again.",
        );
      router.push(`/research/${body.runId}`);
    } catch (error) {
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
                    onChange={setDepth}
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
                          Up to {item.sources} sources
                        </span>
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                  <p id="scope-note" className="desk-help">
                    {simple
                      ? "This evergreen question uses a fast explainer with up to two sources, regardless of the selected depth."
                      : "Limits are ceilings, not quotas. Search and extraction both count toward the provider-call budget."}
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
