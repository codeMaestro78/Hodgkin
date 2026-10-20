"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Dialog } from "@base-ui/react/dialog";
import {
  WorkspaceShell,
  useWorkspaceEntitlement,
} from "../../components/workspace-shell";
import { Icon } from "../../components/ui";
import { ResearchCreditTopUp } from "../../components/research-credit-topup";
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
import {
  modeAccessMessage,
  researchBudgetFailure,
  type ResearchBudgetFailure,
  researchStartFailure,
} from "../../../lib/run-status";

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
  const { entitlement, unavailable: entitlementUnavailable } =
    useWorkspaceEntitlement();
  const [draft, setDraft] = useState<ResearchDraft>(emptyResearchDraft);
  const { question, depth, requireApproval, requirementsText } = draft;
  const draftRef = useRef(draft);
  const accountId = useRef<string | null>(null);
  const accountGeneration = useRef(0);
  const checkingAccount = useRef(true);
  const [draftReady, setDraftReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [budgetFailure, setBudgetFailure] =
    useState<ResearchBudgetFailure | null>(null);
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
  const allowedModes =
    !entitlementUnavailable && entitlement?.status === "active"
      ? entitlement.allowedModes
      : undefined;
  const selectedModeNotice = modeAccessMessage(depth, allowedModes);

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
    const accessNotice = modeAccessMessage(currentDraft.depth, allowedModes);
    if (accessNotice) {
      setNotice(accessNotice);
      return;
    }
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
      if (!response.ok || !body.runId) {
        const exhausted = researchBudgetFailure(response.status, body.detail);
        if (exhausted) {
          submitting.current = false;
          setBusy(false);
          setBudgetFailure(exhausted);
          return;
        }
        throw new Error(
          researchStartFailure(
            response.status,
            body.detail,
            currentDraft.depth,
            allowedModes,
          ) ??
            body.error ??
            (typeof body.detail === "string"
              ? body.detail
              : "The research couldn’t be started. Please try again."),
        );
      }
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
    <>
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
                    <ToggleGroupItem
                      key={item.mode}
                      value={item.mode}
                      disabled={Boolean(
                        modeAccessMessage(item.mode, allowedModes),
                      )}
                    >
                      <span className="depth-title">
                        {item.name}
                        {modeAccessMessage(item.mode, allowedModes) && (
                          <span className="depth-access-badge">
                            {item.mode === "deep" ? "Investigator" : "Upgrade"}
                          </span>
                        )}
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
                {selectedModeNotice && (
                  <p className="desk-help" role="status">
                    {selectedModeNotice} <Link href="/pricing">View plans</Link>
                  </p>
                )}
                {entitlementUnavailable && (
                  <p className="desk-help" role="status">
                    Plan access could not be checked right now. Your plan will
                    be verified securely before a run starts.
                  </p>
                )}
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
    <Dialog.Root
      open={budgetFailure !== null}
      onOpenChange={(open) => {
        if (!open) setBudgetFailure(null);
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="research-budget-backdrop" />
        <Dialog.Popup
          className="research-budget-dialog"
          aria-describedby="research-budget-description"
        >
          <div className="research-budget-mark" aria-hidden="true">
            <Icon name="layers" size={22} />
          </div>
          <Dialog.Title className="research-budget-title">
            {budgetFailure?.availableUnits === 0
              ? "Your research units are used up"
              : "Not enough units for this run"}
          </Dialog.Title>
          <Dialog.Description
            id="research-budget-description"
            className="research-budget-description"
          >
            {budgetFailure &&
              `This ${depth} run needs ${budgetFailure.requiredUnits} ${budgetFailure.requiredUnits === 1 ? "unit" : "units"}. You have ${budgetFailure.availableUnits} ${budgetFailure.availableUnits === 1 ? "unit" : "units"} available to start a new run.`}
          </Dialog.Description>
          <section className="research-budget-breakdown" aria-label="Research unit balance">
            <div className="research-budget-balance-row">
              <span>{entitlement?.planKey === "free"
                ? "Free monthly allowance"
                : entitlement?.planKey === "scholar"
                  ? "Scholar monthly allowance"
                  : entitlement?.planKey === "investigator"
                    ? "Investigator monthly allowance"
                    : "Monthly plan allowance"}</span>
              <strong>
                {typeof entitlement?.availableUnits === "number"
                  ? `${entitlement.availableUnits} left`
                  : "Balance unavailable"}
              </strong>
            </div>
            {typeof entitlement?.allowanceUnits === "number" ? (
              <p>
                {Math.max(0, entitlement.consumedUnits ?? 0)} of {entitlement.allowanceUnits} monthly units used
              </p>
            ) : null}
            {entitlement?.planKey === "free" ? (
              <p className="research-budget-plan-note">
                Upgrade your plan for a larger monthly allowance and access to the modes included with that plan.
              </p>
            ) : entitlement?.planKey === "scholar" || entitlement?.planKey === "investigator" ? (
              <p className="research-budget-plan-note">
                Add purchased credits for eligible runs. Credits are separate from your monthly allowance and do not unlock modes excluded from your plan.
              </p>
            ) : (
              <p className="research-budget-plan-note">
                Purchased credits are separate from your monthly allowance; plan access still determines which research modes you can use.
              </p>
            )}
          </section>
          {entitlement?.reservedUnits ? (
            <p className="research-budget-reserved">
              {entitlement.reservedUnits} {entitlement.reservedUnits === 1 ? "unit is" : "units are"} reserved for other research runs and are not available for a new run.
            </p>
          ) : null}
          {(budgetFailure?.periodEnd || entitlement?.periodEnd) &&
          Number.isFinite(
            Date.parse(budgetFailure?.periodEnd ?? entitlement?.periodEnd ?? ""),
          ) ? (
            <p className="research-budget-reset">
              Allowance resets {new Intl.DateTimeFormat(undefined, {
                dateStyle: "medium",
                timeZone: "UTC",
              }).format(
                new Date(budgetFailure?.periodEnd ?? entitlement?.periodEnd ?? ""),
              )}.
            </p>
          ) : null}
          <ResearchCreditTopUp
            revision={0}
            expanded
            summaryLabel="Add purchased credits"
          />
          <div className="research-budget-actions">
            <Dialog.Close className="desk-button desk-button-outline">
              Keep editing
            </Dialog.Close>
            <Link className="desk-button desk-button-primary" href="/pricing">
              {entitlement?.planKey === "free" ? "Explore plans" : "Plan details"}
              <Icon name="arrow" size={16} />
            </Link>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
    </>
  );
}

export default function ResearchPage() {
  return (
    <WorkspaceShell title="New research">
      <ResearchComposer />
    </WorkspaceShell>
  );
}
