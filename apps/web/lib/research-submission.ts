export type ResearchSubmission = { body: string; key: string };

/** A network retry of the same draft must not become a second research run. */
export function researchSubmission(
  previous: ResearchSubmission | null,
  body: string,
): ResearchSubmission {
  return previous?.body === body
    ? previous
    : { body, key: crypto.randomUUID() };
}
