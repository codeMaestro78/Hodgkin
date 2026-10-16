import { z } from "zod";

export const onboardingDraftSchema = z
  .object({
    role: z.string().trim().max(120),
    field: z.string().trim().max(120),
    workplace: z.enum([
      "",
      "University",
      "Company",
      "Healthcare",
      "Research lab",
      "Government",
      "Independent",
    ]),
    workplaceName: z.string().trim().max(160),
    topic: z.string().trim().max(1000),
    depth: z.enum(["Focused", "Balanced", "Deep"]),
  })
  .strict();
export type OnboardingDraft = z.infer<typeof onboardingDraftSchema>;
export const emptyOnboarding: OnboardingDraft = {
  role: "",
  field: "",
  workplace: "",
  workplaceName: "",
  topic: "",
  depth: "Balanced",
};
export const onboardingProfileSchema = onboardingDraftSchema.extend({
  version: z.literal(1),
  step: z.number().int().min(1).max(6),
  status: z.enum(["in_progress", "completed", "skipped"]),
  updatedAt: z.iso.datetime(),
});
export type OnboardingProfile = z.infer<typeof onboardingProfileSchema>;
export const onboardingRequestSchema = z
  .object({
    action: z.enum(["save", "complete", "skip"]),
    step: z.number().int().min(1).max(6),
    draft: onboardingDraftSchema,
    next: z.string().max(200).optional(),
  })
  .strict();
export function readOnboarding(
  metadata: Record<string, unknown> | undefined,
): OnboardingProfile | null {
  return (
    onboardingProfileSchema.safeParse(metadata?.research_onboarding).data ??
    null
  );
}
export function needsOnboarding(metadata: Record<string, unknown> | undefined) {
  const profile = readOnboarding(metadata);
  return !profile || profile.status === "in_progress";
}
export function stepValid(step: number, draft: OnboardingDraft) {
  if (step === 1) return draft.role.trim().length > 0;
  if (step === 2) return draft.field.trim().length > 0;
  if (step === 3) return draft.workplace.length > 0;
  if (step === 4)
    return draft.topic.trim().length === 0 || draft.topic.trim().length >= 5;
  return true;
}
export function canComplete(draft: OnboardingDraft) {
  return [1, 2, 3, 4].every((step) => stepValid(step, draft));
}
/** A convenience redirect only; metadata never authorizes research or changes quotas. */
export function onboardingDestination(
  next: string,
  metadata: Record<string, unknown> | undefined,
) {
  return next !== "/reset-password" && needsOnboarding(metadata)
    ? `/onboarding?next=${encodeURIComponent(next)}`
    : next;
}
