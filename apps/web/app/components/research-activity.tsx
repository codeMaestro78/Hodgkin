import { runStage } from "../../lib/run-status";

const descriptions: Record<string, string> = {
  queued: "Your request is saved and waiting for a worker.",
  planning: "Organizing your question into bounded research tasks.",
  researching: "Collecting evidence for the research questions below.",
  reflecting: "Reviewing coverage and remaining evidence gaps.",
  verifying: "Checking quoted passages and their support before publication.",
  writing: "Organizing supported findings into your report.",
};

/** Public persisted activity only: no invented thoughts or estimated percentages. */
export function ResearchActivity({
  status,
  events,
}: {
  status: string;
  events: { sequence: number; label: string | null; occurredAt: string }[];
}) {
  const recent = events
    .filter((event) => event.label?.trim())
    .slice(-3)
    .reverse();
  return (
    <section
      className="research-activity"
      aria-label="Latest recorded activity"
    >
      <div className="research-activity-heading">
        <span className="research-activity-dot" aria-hidden="true" />
        <strong key={status} className="research-stage-label">
          {runStage(status)}
        </strong>
        <small>Recorded activity</small>
      </div>
      <p>{descriptions[status] ?? "Waiting for the next recorded update."}</p>
      <ol>
        {recent.length ? (
          recent.map((event) => (
            <li key={event.sequence}>
              <span title={event.label ?? undefined}>{event.label}</span>
              <time dateTime={event.occurredAt}>
                {Number.isNaN(Date.parse(event.occurredAt))
                  ? "Recorded"
                  : new Date(event.occurredAt).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
              </time>
            </li>
          ))
        ) : (
          <li>
            <span>Waiting for the first activity record.</span>
          </li>
        )}
      </ol>
      <small>
        Recorded actions, not private reasoning. Full history is in Methodology.
      </small>
    </section>
  );
}
