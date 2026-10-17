export type RepairOutcomeData = {
  status: "repaired" | "stopped";
  reason?: string;
  newSourceCount?: number;
  verifiedFindingCount?: number;
};

const repairReasonLabels: Record<string, string> = {
  claim_capacity_exhausted:
    "No capacity remained for additional verified findings.",
  failed: "Repair could not be verified; the original report was kept.",
  insufficient_time:
    "Not enough time remained to finish verification; the original report was kept.",
  no_delta_claims: "No new claims were produced; the original report was kept.",
  no_new_evidence:
    "No distinct evidence was found; the original report was kept.",
  no_verified_delta_claims:
    "New claims did not pass evidence checks; the original report was kept.",
  timeout: "Repair reached its time limit; the original report was kept.",
};

export function RepairOutcome({
  outcome,
}: {
  outcome: RepairOutcomeData | null;
}) {
  if (!outcome) return null;
  const repaired = outcome.status === "repaired";
  const counts = [
    outcome.newSourceCount !== undefined
      ? `${outcome.newSourceCount} new ${outcome.newSourceCount === 1 ? "source" : "sources"}`
      : null,
    outcome.verifiedFindingCount !== undefined
      ? `${outcome.verifiedFindingCount} verified ${outcome.verifiedFindingCount === 1 ? "finding" : "findings"}`
      : null,
  ].filter(Boolean);
  return (
    <aside
      className="repair-outcome"
      data-status={outcome.status}
      aria-live="polite"
    >
      <strong>
        {repaired ? "Coverage gap repaired" : "Coverage repair stopped"}
      </strong>
      <p>
        {repaired
          ? `The report now includes ${counts.join(" and ") || "additional verified evidence"}.`
          : (repairReasonLabels[outcome.reason ?? ""] ??
            "The original verified report was kept; no repair result was published.")}
      </p>
    </aside>
  );
}
