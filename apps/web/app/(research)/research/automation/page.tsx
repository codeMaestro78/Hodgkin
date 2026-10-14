"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { WorkspaceShell } from "../../../components/workspace-shell";
import {
  Alert,
  Badge,
  Button,
  Empty,
  Field,
  FieldGroup,
  FieldLabel,
} from "../../../components/workbench-ui";
import {
  researchSubmission,
  type ResearchSubmission,
} from "../../../../lib/research-submission";

type Batch = { batchId: string; runIds: string[] };
type Schedule = {
  id: string;
  question: string;
  intervalMinutes: number;
  enabled: boolean;
  nextRunAt: string | null;
};

async function readResponse(response: Response) {
  const body = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      body?.error ??
        (typeof body?.detail === "string"
          ? body.detail
          : "The request couldn’t be completed. Try again."),
    );
  return body;
}

export default function AutomationPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [reload, setReload] = useState(0);
  const [questions, setQuestions] = useState("");
  const [question, setQuestion] = useState("");
  const [interval, setInterval] = useState("1440");
  const [batchApproval, setBatchApproval] = useState(true);
  const [scheduleApproval, setScheduleApproval] = useState(true);
  const [batchLimit, setBatchLimit] = useState("");
  const [scheduleLimit, setScheduleLimit] = useState("");
  const [batchBusy, setBatchBusy] = useState(false);
  const [scheduleBusy, setScheduleBusy] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [scheduleError, setScheduleError] = useState("");
  const [batchNotice, setBatchNotice] = useState("");
  const [scheduleNotice, setScheduleNotice] = useState("");
  const [disabling, setDisabling] = useState<string | null>(null);
  const [disableError, setDisableError] = useState("");
  const batchSubmission = useRef<ResearchSubmission | null>(null);
  const scheduleSubmission = useRef<ResearchSubmission | null>(null);
  const posting = useRef({ batch: false, schedule: false, disable: false });
  const batchQuestions = questions
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setListError("");
    void Promise.allSettled([
      fetch("/api/research/batches", {
        cache: "no-store",
        signal: controller.signal,
      }).then(readResponse),
      fetch("/api/research/schedules", {
        cache: "no-store",
        signal: controller.signal,
      }).then(readResponse),
    ]).then(([batchResult, scheduleResult]) => {
      if (controller.signal.aborted) return;
      const errors: string[] = [];
      if (
        batchResult.status === "fulfilled" &&
        Array.isArray(batchResult.value?.batches)
      )
        setBatches(batchResult.value.batches);
      else errors.push("Batches couldn’t be loaded.");
      if (
        scheduleResult.status === "fulfilled" &&
        Array.isArray(scheduleResult.value?.schedules)
      )
        setSchedules(scheduleResult.value.schedules);
      else errors.push("Schedules couldn’t be loaded.");
      setListError(errors.join(" "));
      setLoading(false);
    });
    return () => controller.abort();
  }, [reload]);

  async function createBatch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (posting.current.batch) return;
    setBatchError("");
    setBatchNotice("");
    if (
      batchQuestions.length < 1 ||
      batchQuestions.length > 20 ||
      batchQuestions.some((value) => value.length < 5 || value.length > 10000)
    ) {
      setBatchError(
        "Enter 1–20 questions, one per line, each between 5 and 10,000 characters.",
      );
      return;
    }
    posting.current.batch = true;
    setBatchBusy(true);
    try {
      batchSubmission.current = researchSubmission(
        batchSubmission.current,
        JSON.stringify({
          questions: batchQuestions,
          requireApproval: batchApproval,
          ...(batchLimit
            ? { budgetOverrides: { maxSearchCalls: Number(batchLimit) } }
            : {}),
        }),
      );
      const body = await readResponse(
        await fetch("/api/research/batches", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            ...JSON.parse(batchSubmission.current.body),
            idempotencyKey: batchSubmission.current.key,
          }),
        }),
      );
      if (typeof body?.batchId !== "string" || !Array.isArray(body.runIds))
        throw new Error(
          "The batch response was incomplete. Retry to retrieve the same batch.",
        );
      setBatches((previous) => [
        body as Batch,
        ...previous.filter((item) => item.batchId !== body.batchId),
      ]);
      setBatchNotice(`Batch created with ${body.runIds.length} runs.`);
      setQuestions("");
      batchSubmission.current = null;
    } catch (cause) {
      setBatchError(
        cause instanceof Error
          ? cause.message
          : "The batch couldn’t be created.",
      );
    } finally {
      posting.current.batch = false;
      setBatchBusy(false);
    }
  }

  async function createSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (posting.current.schedule) return;
    setScheduleError("");
    setScheduleNotice("");
    if (
      question.trim().length < 5 ||
      !Number.isInteger(Number(interval)) ||
      Number(interval) < 60
    ) {
      setScheduleError(
        "Enter a question of at least five characters and an interval of at least 60 whole minutes.",
      );
      return;
    }
    posting.current.schedule = true;
    setScheduleBusy(true);
    try {
      scheduleSubmission.current = researchSubmission(
        scheduleSubmission.current,
        JSON.stringify({
          question: question.trim(),
          intervalMinutes: Number(interval),
          requireApproval: scheduleApproval,
          ...(scheduleLimit
            ? { budgetOverrides: { maxSearchCalls: Number(scheduleLimit) } }
            : {}),
        }),
      );
      await readResponse(
        await fetch("/api/research/schedules", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            ...JSON.parse(scheduleSubmission.current.body),
            idempotencyKey: scheduleSubmission.current.key,
          }),
        }),
      );
      setScheduleNotice("Schedule created.");
      setQuestion("");
      scheduleSubmission.current = null;
      setReload((value) => value + 1);
    } catch (cause) {
      setScheduleError(
        cause instanceof Error
          ? cause.message
          : "The schedule couldn’t be created.",
      );
    } finally {
      posting.current.schedule = false;
      setScheduleBusy(false);
    }
  }

  async function disableSchedule(id: string) {
    if (posting.current.disable) return;
    posting.current.disable = true;
    setDisabling(id);
    setDisableError("");
    setScheduleNotice("");
    try {
      await readResponse(
        await fetch(
          `/api/research/schedules/${encodeURIComponent(id)}/disable`,
          {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: "{}",
          },
        ),
      );
      setSchedules((previous) =>
        previous.map((item) =>
          item.id === id ? { ...item, enabled: false } : item,
        ),
      );
      setScheduleNotice("Schedule disabled.");
    } catch (cause) {
      setDisableError(
        cause instanceof Error
          ? cause.message
          : "The schedule couldn’t be disabled.",
      );
    } finally {
      posting.current.disable = false;
      setDisabling(null);
    }
  }

  return (
    <WorkspaceShell title="Automation">
      <div className="desk-composer-scroll desk-automation">
        <header className="desk-composer-heading">
          <h1>Research in batches or on a schedule.</h1>
          <p>
            Group questions into separate runs, or repeat a brief at a set
            interval.
          </p>
        </header>
        <div className="desk-field-group">
          <section aria-labelledby="batch-title">
            <form
              className="desk-composer"
              onSubmit={createBatch}
              aria-busy={batchBusy}
            >
              <h2 id="batch-title">Create a batch</h2>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="batch-questions">
                    Questions, one per line
                  </FieldLabel>
                  <textarea
                    id="batch-questions"
                    value={questions}
                    onChange={(event) => setQuestions(event.target.value)}
                    rows={6}
                    required
                    disabled={batchBusy}
                    aria-describedby="batch-help"
                  />
                  <p id="batch-help" className="desk-help">
                    {batchQuestions.length}/20 questions. Each question creates
                    its own run.
                  </p>
                </Field>
                <Field>
                  <FieldLabel htmlFor="batch-limit">
                    Search call limit per run (optional)
                  </FieldLabel>
                  <input
                    id="batch-limit"
                    type="number"
                    min={2}
                    max={50}
                    step={1}
                    value={batchLimit}
                    onChange={(event) => setBatchLimit(event.target.value)}
                    disabled={batchBusy}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="batch-approval">
                    <input
                      id="batch-approval"
                      type="checkbox"
                      checked={batchApproval}
                      onChange={(event) =>
                        setBatchApproval(event.target.checked)
                      }
                      disabled={batchBusy}
                    />{" "}
                    Review each plan before research starts
                  </FieldLabel>
                </Field>
              </FieldGroup>
              {batchError ? <Alert>{batchError}</Alert> : null}
              {batchNotice ? <p role="status">{batchNotice}</p> : null}
              <footer className="desk-inline-actions">
                <span>Up to 20 questions</span>
                <Button type="submit" disabled={batchBusy}>
                  {batchBusy ? "Creating batch…" : "Create batch"}
                </Button>
              </footer>
            </form>
          </section>
          <section aria-labelledby="schedule-title">
            <form
              className="desk-composer"
              onSubmit={createSchedule}
              aria-busy={scheduleBusy}
            >
              <h2 id="schedule-title">Create a schedule</h2>
              <FieldGroup>
                <Field>
                  <FieldLabel htmlFor="schedule-question">
                    Research question
                  </FieldLabel>
                  <textarea
                    id="schedule-question"
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    minLength={5}
                    maxLength={10000}
                    rows={3}
                    required
                    disabled={scheduleBusy}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="schedule-interval">
                    Repeat every (minutes)
                  </FieldLabel>
                  <input
                    id="schedule-interval"
                    type="number"
                    min={60}
                    max={43200}
                    step={1}
                    value={interval}
                    onChange={(event) => setInterval(event.target.value)}
                    required
                    disabled={scheduleBusy}
                    aria-describedby="schedule-help"
                  />
                  <p id="schedule-help" className="desk-help">
                    At least 60 minutes. For daily research, use 1440.
                  </p>
                </Field>
                <Field>
                  <FieldLabel htmlFor="schedule-limit">
                    Search call limit per run (optional)
                  </FieldLabel>
                  <input
                    id="schedule-limit"
                    type="number"
                    min={2}
                    max={50}
                    step={1}
                    value={scheduleLimit}
                    onChange={(event) => setScheduleLimit(event.target.value)}
                    disabled={scheduleBusy}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="schedule-approval">
                    <input
                      id="schedule-approval"
                      type="checkbox"
                      checked={scheduleApproval}
                      onChange={(event) =>
                        setScheduleApproval(event.target.checked)
                      }
                      disabled={scheduleBusy}
                    />{" "}
                    Review each plan before research starts
                  </FieldLabel>
                </Field>
              </FieldGroup>
              {scheduleError ? <Alert>{scheduleError}</Alert> : null}
              {scheduleNotice ? <p role="status">{scheduleNotice}</p> : null}
              <footer className="desk-inline-actions">
                <span>Repeated research briefs</span>
                <Button type="submit" disabled={scheduleBusy}>
                  {scheduleBusy ? "Creating schedule…" : "Create schedule"}
                </Button>
              </footer>
            </form>
          </section>
          <section
            aria-labelledby="automation-history-title"
            aria-busy={loading}
          >
            <h2 id="automation-history-title">Your automation</h2>
            <Button
              variant="outline"
              disabled={loading || disabling !== null}
              onClick={() => setReload((value) => value + 1)}
            >
              Refresh lists
            </Button>
            {listError ? (
              <Alert>{listError} Refresh the lists to try again.</Alert>
            ) : null}
            {loading ? (
              <p role="status">Loading batches and schedules…</p>
            ) : null}
            <h3>Batches</h3>
            {batches.length ? (
              <ul className="desk-report-list">
                {batches.map((batch) => (
                  <li key={batch.batchId}>
                    <details>
                      <summary>
                        Batch {batch.batchId} · {batch.runIds.length} runs
                      </summary>
                      <ul>
                        {batch.runIds.map((id) => (
                          <li key={id}>
                            <Link href={`/research/${encodeURIComponent(id)}`}>
                              Open run {id}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </details>
                  </li>
                ))}
              </ul>
            ) : !loading && !listError ? (
              <Empty title="No batches yet">
                Create a batch to research several questions.
              </Empty>
            ) : null}
            <h3>Schedules</h3>
            {disableError ? <Alert>{disableError}</Alert> : null}
            {schedules.length ? (
              <ul className="desk-report-list">
                {schedules.map((schedule) => (
                  <li key={schedule.id}>
                    <div className="desk-composer">
                      <strong style={{ overflowWrap: "anywhere" }}>
                        {schedule.question}
                      </strong>{" "}
                      <Badge>{schedule.enabled ? "Enabled" : "Disabled"}</Badge>
                      <p className="desk-help">
                        Every {schedule.intervalMinutes} minutes.{" "}
                        {schedule.enabled && schedule.nextRunAt ? (
                          <>
                            Next run:{" "}
                            <time dateTime={schedule.nextRunAt}>
                              {schedule.nextRunAt}
                            </time>
                          </>
                        ) : (
                          "No next run scheduled."
                        )}
                      </p>
                      <Button
                        variant="outline"
                        disabled={
                          !schedule.enabled || disabling !== null || loading
                        }
                        onClick={() => void disableSchedule(schedule.id)}
                        aria-label={`Disable schedule: ${schedule.question}`}
                      >
                        {disabling === schedule.id
                          ? "Disabling…"
                          : "Disable schedule"}
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : !loading && !listError ? (
              <Empty title="No schedules yet">
                Create a schedule to repeat a research question.
              </Empty>
            ) : null}
          </section>
        </div>
      </div>
    </WorkspaceShell>
  );
}
