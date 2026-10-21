import { z } from "zod";
import { ResearchModeSchema } from "@research/contracts";

export const researchModes = [
  {
    mode: "focused",
    name: "Focused",
    sources: 6,
    operations: 6,
    minutes: 4,
    description:
      "A decision brief with analysis, trade-offs and cited findings.",
  },
  {
    mode: "balanced",
    name: "Balanced",
    sources: 12,
    operations: 12,
    minutes: 5,
    description:
      "A structured comparison with mechanisms, risks and implications.",
  },
  {
    mode: "deep",
    name: "Deep",
    sources: 20,
    operations: 20,
    minutes: 10,
    description:
      "A detailed investigation with broader evidence and cross-source analysis.",
  },
] as const;

export const MAX_REQUIREMENTS_TEXT = 10_020;
const accountSchema = z.string().min(1).max(128);
export const researchDraftSchema = z
  .object({
    question: z.string().max(1000),
    depth: ResearchModeSchema,
    requireApproval: z.boolean(),
    // Preserve unfinished/invalid lines so the user can correct them after navigation.
    requirementsText: z.string().max(MAX_REQUIREMENTS_TEXT),
  })
  .strict();
export type ResearchDraft = z.infer<typeof researchDraftSchema>;
export const emptyResearchDraft: ResearchDraft = {
  question: "",
  depth: "balanced",
  requireApproval: true,
  requirementsText: "",
};
const storedDraftSchema = z
  .object({
    version: z.literal(2),
    accountId: accountSchema,
    draft: researchDraftSchema,
  })
  .strict();
const legacyStoredDraftSchema = storedDraftSchema.extend({
  version: z.literal(1),
  draft: researchDraftSchema.extend({
    depth: z.enum(["Focused", "Balanced", "Deep"]),
  }),
});
type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const browserStorage = () => window.sessionStorage;

export function researchDraftKey(accountId: string) {
  return accountSchema.safeParse(accountId).success
    ? `research:draft:v2:${encodeURIComponent(accountId)}`
    : null;
}

function legacyDraftKey(accountId: string) {
  return `research:draft:v1:${encodeURIComponent(accountId)}`;
}

/** Explicit mode and independent ceilings; question wording never changes scope. */
export function createResearchRequest(draft: ResearchDraft) {
  const scope = researchModes.find((item) => item.mode === draft.depth)!;
  return {
    question: draft.question.trim(),
    mode: draft.depth,
    reportRequirements: parseReportRequirements(draft.requirementsText),
    requireApproval: draft.requireApproval,
    budgetOverrides: {
      maxProviderOperations: scope.operations,
      maxSources: scope.sources,
      maxWallClockMs: scope.minutes * 60_000,
    },
  };
}

export function parseReportRequirements(text: string): string[] {
  if (text.length > MAX_REQUIREMENTS_TEXT)
    throw new Error("Report requirements are too long.");
  const lines = text
    .split(/\r\n|\n|\r/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length > 20) throw new Error("Use at most 20 report requirements.");
  if (lines.some((line) => line.length > 500))
    throw new Error("Each report requirement must be at most 500 characters.");
  return lines;
}

export function readResearchDraft(
  accountId: string,
  storage: () => DraftStorage = browserStorage,
): ResearchDraft | null {
  try {
    const key = researchDraftKey(accountId);
    if (!key) return null;
    const target = storage();
    const raw = target.getItem(key);
    if (raw !== null) {
      if (raw.length > 70_000) return null;
      const result = storedDraftSchema.safeParse(JSON.parse(raw));
      return result.success && result.data.accountId === accountId
        ? result.data.draft
        : null;
    }
    const legacy = target.getItem(legacyDraftKey(accountId));
    if (!legacy || legacy.length > 70_000) return null;
    const result = legacyStoredDraftSchema.safeParse(JSON.parse(legacy));
    if (!result.success || result.data.accountId !== accountId) return null;
    const draft = researchDraftSchema.parse({
      ...result.data.draft,
      depth: result.data.draft.depth.toLowerCase(),
    });
    if (writeResearchDraft(accountId, draft, () => target)) {
      try {
        target.removeItem(legacyDraftKey(accountId));
      } catch {
        // The migrated draft is already saved; denied cleanup must not hide it.
      }
    }
    return draft;
  } catch {
    return null;
  }
}

export function writeResearchDraft(
  accountId: string,
  draft: ResearchDraft,
  storage: () => DraftStorage = browserStorage,
) {
  try {
    const key = researchDraftKey(accountId);
    const parsed = researchDraftSchema.safeParse(draft);
    if (!key || !parsed.success) return false;
    storage().setItem(
      key,
      JSON.stringify({ version: 2, accountId, draft: parsed.data }),
    );
    return true;
  } catch {
    return false;
  }
}

/** Call only after the create endpoint returns a successful run ID. */
export function clearResearchDraft(
  accountId: string,
  storage: () => DraftStorage = browserStorage,
) {
  try {
    const key = researchDraftKey(accountId);
    if (!key) return false;
    storage().removeItem(key);
    storage().removeItem(legacyDraftKey(accountId));
    return true;
  } catch {
    return false;
  }
}

/** Read only the public identity; never keep a session object or tokens. */
export function researchDraftAccount(body: unknown): string | null {
  return (
    z.object({ user: z.object({ id: accountSchema }) }).safeParse(body).data
      ?.user.id ?? null
  );
}
