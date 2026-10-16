import { z } from "zod";
import { RunStatusSchema } from "@research/contracts";

export const RESEARCH_HISTORY_EVENT = "research:history-snapshot";
const snapshotSchema = z
  .object({
    runId: z.string().min(1).max(128),
    status: RunStatusSchema,
    sourceCount: z.number().int().nonnegative().safe(),
  })
  .strict();
// Run projections currently expose status as a string; validate its value on publish/receive.
export type ResearchHistorySnapshot = {
  runId: string;
  status: string;
  sourceCount: number;
};

/** Local projection notification only: no storage, network, or durable event semantics. */
export function publishResearchHistorySnapshot(
  snapshot: ResearchHistorySnapshot,
  target: EventTarget = window,
) {
  const parsed = snapshotSchema.safeParse(snapshot);
  if (!parsed.success) return false;
  target.dispatchEvent(
    new CustomEvent(RESEARCH_HISTORY_EVENT, { detail: parsed.data }),
  );
  return true;
}

// Public integration name used by the run page.
export const publishResearchHistory = publishResearchHistorySnapshot;

export function subscribeResearchHistorySnapshots(
  listener: (snapshot: ResearchHistorySnapshot) => void,
  target: EventTarget = window,
) {
  const receive = (event: Event) => {
    const parsed = snapshotSchema.safeParse(
      (event as CustomEvent<unknown>).detail,
    );
    if (parsed.success) listener(parsed.data);
  };
  target.addEventListener(RESEARCH_HISTORY_EVENT, receive);
  return () => target.removeEventListener(RESEARCH_HISTORY_EVENT, receive);
}

/** Unknown runs need explicit invalidation; snapshots cannot invent history metadata. */
export function patchResearchHistory<
  T extends { runId: string; status: string; sourceCount: number },
>(history: T[], snapshot: ResearchHistorySnapshot): T[] {
  const index = history.findIndex((run) => run.runId === snapshot.runId);
  const current = history[index];
  if (
    !current ||
    (current.status === snapshot.status &&
      current.sourceCount === snapshot.sourceCount)
  )
    return history;
  return history.map((run, position) =>
    position === index ? { ...run, ...snapshot } : run,
  );
}
