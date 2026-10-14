export function modeDeadline(calls: number) {
  return calls <= 2
    ? 120_000
    : calls <= 6
      ? 180_000
      : calls <= 12
        ? 300_000
        : 600_000;
}

export function runStage(status: string) {
  const stages: Record<string, string> = {
    queued: "Queued",
    planning: "Planning",
    awaiting_approval: "Review plan",
    researching: "Collecting evidence",
    verifying: "Checking evidence",
    writing: "Writing report",
    completed: "Complete",
    failed: "Research failed",
    cancelled: "Research stopped",
  };
  return stages[status] ?? "Updating status";
}

/** Coalesce routine evidence bursts; terminal feedback must not wait. */
export function snapshotRefreshDelay(eventType?: string) {
  return ["run.failed", "run.cancelled", "run.completed"].includes(
    eventType ?? "",
  )
    ? 0
    : 1500;
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
  };
  return (
    (code && messages[code]) ||
    "The run stopped at an execution step. Review the recorded activity for details."
  );
}
