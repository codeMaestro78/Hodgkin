"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { WorkspaceShell } from "../../components/workspace-shell";
import { Icon } from "../../components/ui";
import { Critter } from "../../components/crew/critter";
import {
  ResearchQuestionField,
  ResearchRequirementsField,
} from "../../components/research-draft-fields";
import { onboardingProfileSchema } from "../../../lib/onboarding";
import {
  clearResearchDraft,
  createResearchRequest,
  emptyResearchDraft,
  readResearchDraft,
  researchDraftAccount,
  researchDraftSchema,
  researchModes,
  writeResearchDraft,
  type ResearchDraft,
} from "../../../lib/research-draft";
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

function ResearchComposer() {
  const [draft, setDraft] = useState<ResearchDraft>(emptyResearchDraft);
  const { question, depth, requireApproval, requirementsText } = draft;
  const draftRef = useRef(draft);
  const accountId = useRef<string | null>(null);
  const accountGeneration = useRef(0);
  const checkingAccount = useRef(true);
  const [draftReady, setDraftReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const editedFields = useRef(new Set<keyof ResearchDraft>());
  const created = useRef(false);
  const persistDraftPatch = useCallback(
    (patch: Partial<ResearchDraft>, userEdit = true) => {
      if (userEdit) {
        for (const key of Object.keys(patch) as (keyof ResearchDraft)[])
          editedFields.current.add(key);
      }
      draftRef.current = { ...draftRef.current, ...patch };
      if (accountId.current && !created.current)
        writeResearchDraft(accountId.current, draftRef.current);
    },
    [],
  );
  function updateDraft(patch: Partial<ResearchDraft>, userEdit = true) {
    persistDraftPatch(patch, userEdit);
    setDraft(draftRef.current);
  }
  const setQuestion = useCallback(
    (question: string) => {
      editedQuestion.current = true;
      persistDraftPatch({ question });
      if (notice) setNotice("");
    },
    [notice, persistDraftPatch],
  );
  const setRequirementsText = useCallback(
    (requirementsText: string) => persistDraftPatch({ requirementsText }),
    [persistDraftPatch],
  );
  const setDepth = (depth: string) => {
    if (depth === "focused" || depth === "balanced" || depth === "deep")
      updateDraft({ depth });
  };
  const setRequireApproval = (requireApproval: boolean) =>
    updateDraft({ requireApproval });
  const textarea = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const editedQuestion = useRef(false);
  const editedDepth = useRef(false);
  const submission = useRef<ResearchSubmission | null>(null);
  const submitting = useRef(false);
  const defaultsFrozen = useRef(false);
  useEffect(() => {
    let controller = new AbortController();
    const handoff =
      new URLSearchParams(window.location.search).get("setup") === "ready";
    const hydrate = async () => {
      controller.abort();
      controller = new AbortController();
      const { signal } = controller;
      // A focus recheck must not blank a ready composer. The POST still binds
      // to the expected account, while a changed identity resets the draft below.
      if (!accountId.current) {
        checkingAccount.current = true;
        setDraftReady(false);
      }
      try {
        const response = await fetch("/api/auth/session", {
          cache: "no-store",
          signal,
        });
        // A failed probe says nothing about identity: a transient 401/503 while
        // the session refreshes must not read as an account switch and blank
        // the composer. Only a successful probe may confirm or change the id.
        if (!response.ok) return;
        const id = researchDraftAccount(await response.json());
        if (signal.aborted) return;
        const previousId = accountId.current;
        if (previousId && previousId === id) return;
        if (previousId !== id) accountGeneration.current++;
        accountId.current = id;
        if (previousId) {
          // Never carry the previous account's in-memory text into a new scope.
          checkingAccount.current = true;
          setDraftReady(false);
          draftRef.current = { ...emptyResearchDraft };
          editedFields.current.clear();
          editedQuestion.current = false;
          editedDepth.current = false;
          defaultsFrozen.current = false;
          submission.current = null;
          created.current = false;
          submitting.current = false;
          setBusy(false);
          setNotice("");
          setDraft(draftRef.current);
        }
        if (!id) return;
        const recovered = readResearchDraft(id);
        if (recovered) {
          const patch: Partial<ResearchDraft> = {};
          for (const key of Object.keys(recovered) as (keyof ResearchDraft)[]) {
            if (!editedFields.current.has(key))
              Object.assign(patch, { [key]: recovered[key] });
          }
          updateDraft(patch, false);
        } else writeResearchDraft(id, draftRef.current);
        // Identity and account-scoped draft are ready. Optional defaults must not
        // keep the composer locked behind another network round trip.
        checkingAccount.current = false;
        setDraftReady(true);
        const defaults = await fetch("/api/onboarding", {
          cache: "no-store",
          signal,
        });
        const body = defaults.ok ? await defaults.json() : null;
        if (
          signal.aborted ||
          defaultsFrozen.current ||
          accountId.current !== id
        )
          return;
        const profile = onboardingProfileSchema.safeParse(body?.profile).data;
        if (profile?.status === "completed" && !recovered) {
          const patch: Partial<ResearchDraft> = {};
          if (!editedDepth.current)
            patch.depth = researchDraftSchema.shape.depth.parse(
              profile.depth.toLowerCase(),
            );
          if (handoff && !editedQuestion.current)
            patch.question = profile.topic;
          updateDraft(patch, false);
        }
        if (handoff)
          window.history.replaceState(window.history.state, "", "/research");
      } catch {
        // Unavailable identity/storage/defaults must not block composing.
      } finally {
        if (!signal.aborted) {
          checkingAccount.current = false;
          setDraftReady(true);
        }
      }
    };
    void hydrate();
    window.addEventListener("focus", hydrate);
    return () => {
      controller.abort();
      window.removeEventListener("focus", hydrate);
    };
  }, []);
  const scope =
    researchModes.find((item) => item.mode === depth) ?? researchModes[1];

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || submitting.current || !draftReady || checkingAccount.current)
      return;
    if (!accountId.current) {
      setNotice(
        "Verify your account before starting research. Please try again.",
      );
      window.dispatchEvent(new Event("focus"));
      return;
    }
    const currentDraft = draftRef.current;
    if (currentDraft.question.trim().length < 5) {
      setNotice(
        "Add a little more detail—your question needs at least five characters.",
      );
      textarea.current?.focus();
      return;
    }
    let request: ReturnType<typeof createResearchRequest>;
    try {
      request = createResearchRequest(currentDraft);
    } catch (error) {
      setNotice(
        error instanceof Error ? error.message : "Check report requirements.",
      );
      return;
    }
    defaultsFrozen.current = true;
    submitting.current = true;
    setBusy(true);
    setNotice("");
    const submissionAccountId = accountId.current;
    const submissionGeneration = accountGeneration.current;
    try {
      submission.current = researchSubmission(
        submission.current,
        JSON.stringify(request),
      );
      const response = await fetch("/api/research/runs", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": submission.current.key,
          "x-research-account-id": submissionAccountId,
        },
        body: submission.current.body,
      });
      const body = (await response.json()) as {
        runId?: string;
        error?: string;
        detail?: unknown;
      };
      // A previous account's request must never mutate a newly hydrated composer.
      if (submissionGeneration !== accountGeneration.current) return;
      if (response.status === 409) window.dispatchEvent(new Event("focus"));
      if (!response.ok || !body.runId)
        throw new Error(
          body.error ??
            (typeof body.detail === "string"
              ? body.detail
              : "The research couldn’t be started. Please try again."),
        );
      created.current = true;
      if (submissionAccountId) clearResearchDraft(submissionAccountId);
      router.push(`/research/${body.runId}`);
    } catch (error) {
      if (submissionGeneration !== accountGeneration.current) return;
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
    <div className="desk-composer-scroll">
      <header className="desk-composer-heading">
        <h1>Start a research brief.</h1>
        <p>A question worth asking. Evidence you can inspect.</p>
      </header>
      <div className="desk-composer-layout">
        <div className="desk-composer-main">
          <div className="desk-perch" aria-hidden="true">
            <Critter kind="lens" size={44} delay={400} />
            <Critter kind="folio" size={48} />
            <Critter kind="quill" size={40} delay={900} />
          </div>
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
              <ResearchQuestionField
                value={question}
                disabled={busy}
                invalid={Boolean(notice)}
                textareaRef={textarea}
                onValueChange={setQuestion}
              />
              <ResearchRequirementsField
                value={requirementsText}
                disabled={busy}
                onValueChange={setRequirementsText}
              />
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
                  {researchModes.map((item) => (
                    <ToggleGroupItem key={item.mode} value={item.mode}>
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
                        Up to {item.sources} sources · {item.operations}{" "}
                        provider operations · {item.minutes}-minute active limit
                      </span>
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p id="scope-note" className="desk-help">
                  Planning, collection and verification share this active-time
                  limit; waiting for approval does not count. Limits are
                  ceilings, not quotas. Search and extraction both count toward
                  the provider-operation budget.
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
                  Approve the proposed questions to continue, or reject the plan
                  to stop the run.
                </p>
              </Field>
            </FieldGroup>
            {notice && <Alert>{notice}</Alert>}
            <footer className="desk-composer-footer">
              <span>
                <kbd>Ctrl / ⌘</kbd> + <kbd>Enter</kbd> to start
              </span>
              <Button type="submit" disabled={busy || !draftReady}>
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
          <Badge>{scope.name}</Badge>
          <dl>
            <div>
              <dt>Source ceiling</dt>
              <dd>{scope.sources} sources</dd>
            </div>
            <div>
              <dt>Provider-operation ceiling</dt>
              <dd>{scope.operations} operations</dd>
            </div>
            <div>
              <dt>Active-time ceiling</dt>
              <dd>{scope.minutes} minutes</dd>
            </div>
            <div>
              <dt>Search provider</dt>
              <dd>Tavily</dd>
            </div>
          </dl>
          <p>{scope.description}</p>
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
  );
}

export default function ResearchPage() {
  return (
    <WorkspaceShell title="New research">
      <ResearchComposer />
    </WorkspaceShell>
  );
}
