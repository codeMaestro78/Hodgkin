import { z } from "zod";

export const MAX_REQUIREMENTS_TEXT = 10_020;
const accountSchema = z.string().min(1).max(128);
export const researchDraftSchema = z
  .object({
    question: z.string().max(1000),
    depth: z.enum(["Focused", "Balanced", "Deep"]),
    requireApproval: z.boolean(),
    // Preserve unfinished/invalid lines so the user can correct them after navigation.
    requirementsText: z.string().max(MAX_REQUIREMENTS_TEXT),
  })
  .strict();
export type ResearchDraft = z.infer<typeof researchDraftSchema>;
export const emptyResearchDraft: ResearchDraft = {
  question: "",
  depth: "Balanced",
  requireApproval: true,
  requirementsText: "",
};
const storedDraftSchema = z
  .object({
    version: z.literal(1),
    accountId: accountSchema,
    draft: researchDraftSchema,
  })
  .strict();
type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const browserStorage = () => window.sessionStorage;

export function researchDraftKey(accountId: string) {
  return accountSchema.safeParse(accountId).success
    ? `research:draft:v1:${encodeURIComponent(accountId)}`
    : null;
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
    const raw = storage().getItem(key);
    if (!raw || raw.length > 70_000) return null;
    const result = storedDraftSchema.safeParse(JSON.parse(raw));
    return result.success && result.data.accountId === accountId
      ? result.data.draft
      : null;
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
      JSON.stringify({ version: 1, accountId, draft: parsed.data }),
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
