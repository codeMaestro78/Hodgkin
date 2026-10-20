export function modeDeadline(calls: number) {
  return calls <= 2
    ? 120_000
    : calls <= 6
      ? 180_000
      : calls <= 12
        ? 300_000
        : 600_000;
}

/** Recorded limits win, even when tighter than the selected mode's defaults. */
export function retryDeadline(run: {
  mode?: "focused" | "balanced" | "deep" | null;
  modePolicyVersion?: string | null;
  budget: { maxWallClockMs?: number | null; maxSearchCalls: number };
}) {
  const recorded = run.budget.maxWallClockMs;
  if (typeof recorded === "number" && Number.isFinite(recorded) && recorded > 0)
    return recorded;
  if (run.mode && run.modePolicyVersion === "research-mode-policy-v1") {
    const minutes = { focused: 3, balanced: 5, deep: 10 };
    return minutes[run.mode] * 60_000;
  }
  return modeDeadline(run.budget.maxSearchCalls);
}

export const runPhases = [
  "planning",
  "researching",
  "verifying",
  "writing",
  "completed",
] as const;

/**
 * Index of the visible phase for a recorded status. Reflection loops back into
 * collection, so it stays in the research phase. Queued and stopped runs return
 * -1: their position in the lifecycle is not recorded, so none is implied.
 */
export function runPhaseIndex(status: string) {
  const phase: Record<string, number> = {
    planning: 0,
    awaiting_approval: 0,
    researching: 1,
    reflecting: 1,
    verifying: 2,
    writing: 3,
    completed: 4,
  };
  return phase[status] ?? -1;
}

export function runStage(status: string) {
  const stages: Record<string, string> = {
    queued: "Queued",
    planning: "Planning",
    awaiting_approval: "Review plan",
    researching: "Collecting evidence",
    reflecting: "Reviewing coverage",
    verifying: "Checking evidence",
    writing: "Writing report",
    completed: "Complete",
    failed: "Research failed",
    cancelled: "Research stopped",
  };
  return stages[status] ?? "Updating status";
}

/** Apply only the phase explicitly recorded by a durable graph-node event. */
export function statusForNodeStart(nodeId: string): string | null {
  const statuses: Record<string, string> = {
    intake: "planning",
    planner: "planning",
    planner_delta: "planning",
    research_worker: "researching",
    research_task: "researching",
    assess_evidence: "reflecting",
    reflector: "reflecting",
    verifier: "verifying",
    synthesizer: "writing",
  };
  return statuses[nodeId] ?? null;
}

/** Bound full-snapshot reads during event bursts; terminal feedback must not wait. */
export function snapshotRefreshDelay(
  eventType?: string,
  lastSnapshotFinishedAt = 0,
  now = Date.now(),
) {
  if (
    ["run.failed", "run.cancelled", "run.completed"].includes(eventType ?? "")
  )
    return 0;
  const preferredDelay = eventType === "node.started" ? 1000 : 5000;
  const cadenceDelay = Math.max(0, lastSnapshotFinishedAt + 5000 - now);
  return Math.max(preferredDelay, cadenceDelay);
}

/** Polling outages do not imply that the durable research run has failed. */
export function isTransientSnapshotFailure(status: number | undefined) {
  return status === undefined || (status >= 500 && status < 600);
}

/** Bounded exponential retry for a temporarily unavailable run snapshot. */
export function snapshotRetryDelay(attempt: number) {
  const safeAttempt = Math.max(1, Math.floor(attempt));
  return Math.min(1000 * 2 ** (safeAttempt - 1), 10_000);
}

export const SNAPSHOT_RECONNECTING_MESSAGE =
  "We temporarily couldn’t refresh the run status. Your research may still be running; reconnecting…";

/** One pending refresh. Important state changes can preempt a source burst. */
export function createSnapshotRefresh(refresh: () => void) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let due = Infinity;
  const cancel = () => {
    clearTimeout(timer);
    timer = undefined;
    due = Infinity;
  };
  return {
    get scheduled() {
      return timer !== undefined;
    },
    schedule(delay: number) {
      const next = Date.now() + delay;
      if (timer !== undefined && next >= due) return;
      cancel();
      due = next;
      timer = setTimeout(() => {
        timer = undefined;
        due = Infinity;
        refresh();
      }, delay);
    },
    cancel,
  };
}

export function runFailure(code: string | null) {
  const messages: Record<string, string> = {
    wall_clock_limit_exceeded:
      "The active-time limit was reached before the report was ready.",
    budget_exhausted:
      "The run reached its usage budget before the report was ready.",
    recovery_limit:
      "Automatic recovery stopped after repeated interruptions. Review the activity before starting again.",
    graph_version_incompatible:
      "This run needs an operator review after a runtime update.",
    writer_output_limit_reached:
      "The report writer reached its configured output limit before it could return a complete, verifiable response. No report was published; collected sources remain available. Try a new run with a shorter scope, or retry after the writer limit is adjusted.",
    model_output_incomplete:
      "A model response ended before it could be validated. No unverified answer was published; collected evidence remains available.",
    model_refused_output:
      "A model could not complete a required research step. No unverified answer was published; collected evidence remains available.",
    model_output_invalid:
      "A model response could not be validated for this research step. No unverified answer was published; collected evidence remains available.",
  };
  return (
    (code && messages[code]) ||
    "The run stopped at an execution step. Review the recorded activity for details."
  );
}

export function modeAccessMessage(
  mode: "focused" | "balanced" | "deep",
  allowedModes: readonly string[] | undefined,
): string | null {
  if (!allowedModes || allowedModes.includes(mode)) return null;
  const available =
    allowedModes.length > 0
      ? allowedModes
          .map((value) => value.charAt(0).toUpperCase() + value.slice(1))
          .join(" and ")
      : "no research modes";
  if (mode === "deep") {
    return `Deep mode requires the Investigator plan. Your current plan includes ${available}. View plans to unlock Deep.`;
  }
  return `Your current plan includes ${available}, not ${mode}. View plans to unlock this mode.`;
}

export function researchStartFailure(
  status: number,
  detail: unknown,
  mode: "focused" | "balanced" | "deep",
  allowedModes?: readonly string[],
): string | null {
  if (status !== 403) return null;
  const message =
    typeof detail === "string"
      ? detail
      : detail &&
          typeof detail === "object" &&
          "message" in detail &&
          typeof detail.message === "string"
        ? detail.message
        : "";
  if (!message.toLowerCase().includes("mode is not available")) return null;
  return (
    modeAccessMessage(mode, allowedModes) ??
    (mode === "deep"
      ? "Deep mode isn't included in your current plan. Upgrade to Investigator to use it."
      : `${mode.charAt(0).toUpperCase() + mode.slice(1)} mode isn't included in your current plan. View plans to unlock it.`)
  );
}

export type ResearchBudgetFailure = {
  requiredUnits: number;
  availableUnits: number;
  periodEnd: string | null;
};

/** Recognize only the backend's explicit monthly-entitlement admission error. */
export function researchBudgetFailure(
  status: number,
  detail: unknown,
): ResearchBudgetFailure | null {
  if (
    status !== 402 ||
    detail === null ||
    typeof detail !== "object" ||
    !("message" in detail) ||
    detail.message !== "insufficient research units"
  )
    return null;
  const requiredUnits = "requiredUnits" in detail ? detail.requiredUnits : null;
  const availableUnits = "availableUnits" in detail ? detail.availableUnits : null;
  const periodEnd = "periodEnd" in detail ? detail.periodEnd : null;
  if (
    typeof requiredUnits !== "number" ||
    !Number.isInteger(requiredUnits) ||
    requiredUnits < 1 ||
    typeof availableUnits !== "number" ||
    !Number.isInteger(availableUnits) ||
    availableUnits < 0 ||
    (periodEnd !== null && typeof periodEnd !== "string")
  )
    return null;
  return { requiredUnits, availableUnits, periodEnd };
}
