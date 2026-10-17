import { expect, it } from "vitest";
import { researchSubmission } from "../lib/research-submission";
import {
  createResearchRequest,
  emptyResearchDraft,
} from "../lib/research-draft";
import { CreateResearchRunRequestSchema } from "@research/contracts";

it.each([
  ["focused", 6, 3],
  ["balanced", 12, 5],
  ["deep", 20, 10],
] as const)(
  "sends explicit %s for evergreen and complex questions",
  (depth, ceiling, minutes) => {
    for (const question of [
      "What is a database?",
      "Compare current database architectures and implementation risks",
    ]) {
      const request = createResearchRequest({
        ...emptyResearchDraft,
        depth,
        question: ` ${question} `,
        requireApproval: false,
        requirementsText: " Costs \n\n Risks ",
      });
      expect(request).toEqual({
        question,
        mode: depth,
        requireApproval: false,
        reportRequirements: ["Costs", "Risks"],
        budgetOverrides: {
          maxProviderOperations: ceiling,
          maxSources: ceiling,
          maxWallClockMs: minutes * 60_000,
        },
      });
      expect(CreateResearchRunRequestSchema.safeParse(request).success).toBe(
        true,
      );
    }
  },
);

it("changes the idempotency key when only explicit mode changes", () => {
  const draft = { ...emptyResearchDraft, question: "What is a database?" };
  const first = researchSubmission(
    null,
    JSON.stringify(createResearchRequest(draft)),
  );
  const changed = researchSubmission(
    first,
    JSON.stringify(createResearchRequest({ ...draft, depth: "deep" })),
  );
  expect(changed.key).not.toBe(first.key);
  expect(researchSubmission(changed, changed.body)).toBe(changed);
});

it("retains one idempotency key across retries of the same draft", () => {
  const first = researchSubmission(null, '{"question":"Fixture"}');
  expect(researchSubmission(first, first.body)).toBe(first);
});

it("changes the key when the question or effective scope changes", () => {
  const first = researchSubmission(null, '{"question":"Fixture","limit":6}');
  const changed = researchSubmission(
    first,
    '{"question":"Fixture","limit":12}',
  );
  expect(changed.key).not.toBe(first.key);
});

it("includes plan approval in the draft fingerprint", () => {
  const first = researchSubmission(
    null,
    JSON.stringify({ question: "Fixture", requireApproval: true }),
  );
  expect(researchSubmission(first, first.body)).toBe(first);
  const changed = researchSubmission(
    first,
    JSON.stringify({ question: "Fixture", requireApproval: false }),
  );
  expect(changed.key).not.toBe(first.key);
});
