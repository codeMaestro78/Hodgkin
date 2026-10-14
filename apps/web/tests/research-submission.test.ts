import { expect, it } from "vitest";
import { researchSubmission } from "../lib/research-submission";

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
