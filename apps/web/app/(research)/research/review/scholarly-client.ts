// Scholarly BFF contract. Keep endpoint names and response normalization here while
// the research API contract is being finalized.
const ROOT = "/api/research/scholarly/reviews";
export const PDF_LIMIT = 4 * 1024 * 1024;

export type Review = { reviewId: string; title: string; question: string };
export type RecordRow = {
  record_id: string; search_id: string; provider: string; provider_record_id: string;
  title: string; abstract: string | null; doi: string | null; locator_url: string | null;
};
export type Decision = {
  record_id: string; stage: "title_abstract" | "full_text";
  outcome: "include" | "exclude" | "maybe";
  exclusion_reason: string | null; source_id: string | null;
};
export type Retrieval = { record_id: string; status: "retrieved" | "not_retrieved"; source_id: string | null };
export type Evidence = { id: string; recordId: string; artifactId: string; sourceId: string; claim: string; quote: string; pageAnchor: string | null };
export type ReviewDetail = Review & { records: RecordRow[]; decisions: Decision[]; retrievals: Retrieval[]; evidence: Evidence[] };
export type Flow = Record<string, number | [string, number][]>;

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Research service returned an invalid response.");
  return value as Record<string, unknown>;
}
function string(value: unknown): string { return typeof value === "string" ? value : ""; }
function items(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.map(object);
}
function review(value: unknown): Review {
  const raw = object(value);
  const reviewId = string(raw.reviewId ?? raw.review_id ?? raw.id);
  if (!reviewId) throw new Error("Research service returned a review without an id.");
  return { reviewId, title: string(raw.title ?? raw.name) || "Untitled review", question: string(raw.question) };
}
function detail(base: Review, recordsRaw: unknown, decisionsRaw: unknown, retrievalsRaw: unknown, evidenceRaw: unknown): ReviewDetail {
  const raw = { records: recordsRaw, decisions: decisionsRaw, retrievals: retrievalsRaw };
  return {
    ...base,
    records: items(raw.records).map((row) => ({
      record_id: string(row.recordId ?? row.record_id), search_id: string(row.searchId ?? row.search_id),
      provider: string(row.provider), provider_record_id: string(row.providerRecordId ?? row.provider_record_id),
      title: string(row.title), abstract: string(row.abstract) || null,
      doi: string(row.doi) || null, locator_url: string(row.locatorUrl ?? row.locator_url) || null,
    })).filter((row) => row.record_id && row.title),
    decisions: items(raw.decisions).map((row) => ({
      record_id: string(row.recordId ?? row.record_id),
      stage: row.stage === "full_text" ? "full_text" as const : "title_abstract" as const,
      outcome: row.outcome === "exclude" ? "exclude" as const : row.outcome === "include" ? "include" as const : "maybe" as const,
      exclusion_reason: string(row.exclusionReason ?? row.exclusion_reason) || null,
      source_id: string(row.sourceId ?? row.source_id) || null,
    })),
    retrievals: items(raw.retrievals).map((row) => ({
      record_id: string(row.recordId ?? row.record_id),
      status: row.status === "retrieved" ? "retrieved" as const : "not_retrieved" as const,
      source_id: string(row.sourceId ?? row.source_id) || null,
    })),
    evidence: items(evidenceRaw).map((row) => ({
      id: string(row.id), recordId: string(row.recordId ?? row.record_id),
      artifactId: string(row.artifactId ?? row.artifact_id),
      sourceId: string(row.sourceId ?? row.source_id),
      claim: string(row.claim), quote: string(row.quote),
      pageAnchor: string(row.pageAnchor ?? row.page_anchor) || null,
    })),
  };
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${ROOT}${path}`, { cache: "no-store", ...init });
  let body: unknown;
  try { body = await response.json(); } catch { throw new Error("Research service returned an invalid response."); }
  if (!response.ok) {
    const message = body && typeof body === "object" ? (body as Record<string, unknown>).error : null;
    throw new Error(typeof message === "string" ? message : "Research request failed. Please try again.");
  }
  return body;
}
const post = (path: string, body: unknown) => request(path, {
  method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});
const reviewPath = (reviewId: string) => `/${encodeURIComponent(reviewId)}`;

export async function listReviews(): Promise<Review[]> {
  const body = await request("");
  if (!Array.isArray(body)) throw new Error("Research service returned an invalid review list.");
  return body.map(review);
}
export async function createReview(title: string, question: string): Promise<Review> { return review(await post("", { title, question })); }
export async function getReview(reviewId: string): Promise<ReviewDetail> {
  const path = reviewPath(reviewId);
  const [metadata, records, decisions, retrievals, evidence] = await Promise.all([
    request(path), request(`${path}/records`), request(`${path}/decisions`),
    request(`${path}/retrievals`), request(`${path}/evidence`),
  ]);
  return detail(review(metadata), records, decisions, retrievals, evidence);
}
export async function importRecords(reviewId: string, execution: unknown, records: unknown[]): Promise<void> {
  const path = reviewPath(reviewId);
  await post(`${path}/searches`, execution);
  for (const record of records) await post(`${path}/records`, record);
}
export async function importDoi(reviewId: string, doi: string): Promise<void> {
  await post(`${reviewPath(reviewId)}/imports/doi`, { doi });
}
export async function saveDecision(reviewId: string, decision: Decision): Promise<void> {
  const { record_id, ...body } = decision;
  await post(`${reviewPath(reviewId)}/records/${encodeURIComponent(record_id)}/decisions`, body);
}
export async function saveRetrieval(reviewId: string, receipt: Retrieval): Promise<void> {
  const { record_id, ...body } = receipt;
  await post(`${reviewPath(reviewId)}/records/${encodeURIComponent(record_id)}/retrievals`, body);
}
export async function addEvidence(reviewId: string, recordId: string, body: {
  artifactId: string; sourceId: string; claim: string; quote: string;
  pageNumber: number; start: number; end: number;
}): Promise<void> {
  await post(`${reviewPath(reviewId)}/records/${encodeURIComponent(recordId)}/evidence`, body);
}
export async function getFlow(reviewId: string): Promise<Flow> {
  const raw = object(await request(`${reviewPath(reviewId)}/prisma`));
  const result: Flow = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) result[key] = value;
    else if (Array.isArray(value)) result[key] = value.filter((row): row is [string, number] =>
      Array.isArray(row) && typeof row[0] === "string" && typeof row[1] === "number");
  }
  return result;
}
export async function importPdf(reviewId: string, title: string, file: File): Promise<{ recordId: string; artifactId: string }> {
  if (file.size > PDF_LIMIT) throw new Error("PDF must be 4 MiB or smaller.");
  const response = await fetch(`${ROOT}${reviewPath(reviewId)}/imports/pdf?title=${encodeURIComponent(title)}`, {
    method: "POST", headers: { "content-type": "application/pdf" }, body: file,
  });
  let body: unknown;
  try { body = await response.json(); } catch { throw new Error("Research service returned an invalid response."); }
  if (!response.ok) {
    const message = body && typeof body === "object" ? (body as Record<string, unknown>).error : null;
    throw new Error(typeof message === "string" ? message : "PDF import failed. Please try again.");
  }
  const imported = object(body);
  const recordId = string(imported.recordId ?? imported.record_id);
  const artifactId = string(imported.sourceArtifactId ?? imported.source_artifact_id);
  if (!recordId || !artifactId) throw new Error("Research service did not return the PDF locator.");
  return { recordId, artifactId };
}
