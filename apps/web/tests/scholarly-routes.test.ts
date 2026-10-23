import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({ getUser: vi.fn(), getSession: vi.fn() }));
vi.mock("../lib/auth/server", () => ({ createAuthClient: async () => ({ auth }) }));
import { GET, POST } from "../app/api/research/scholarly/[...path]/route";
import { POST as uploadPdf } from "../app/api/research/scholarly/reviews/[reviewId]/imports/pdf/route";
import { evidenceSourceForRecord, getArtifactPage, getReview, importDoi, importPdf, type ReviewDetail } from "../app/(research)/research/review/scholarly-client";

const reviewId = "11111111-1111-4111-8111-111111111111";
const context = (path: string[]) => ({ params: Promise.resolve({ path }) });

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_APP_URL", "http://localhost:3000");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://identity.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "fixture-public");
  vi.stubEnv("INTERNAL_SERVICE_AUTH", "fixture-service");
  vi.stubEnv("RESEARCH_API_URL", "http://backend.example.test/");
  const user = { id: "account", email_confirmed_at: "2026-10-16T10:00:00Z", is_anonymous: false };
  auth.getUser.mockResolvedValue({ data: { user }, error: null });
  auth.getSession.mockResolvedValue({ data: { session: { user, access_token: "fixture-token" } } });
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.restoreAllMocks(); });

it("forwards only the reviewed scholarly reads and normalizes the API base URL", async () => {
  const response = await GET(new NextRequest("http://localhost:3000/api/research/scholarly/reviews"), context(["reviews"]));
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith("http://backend.example.test/research/reviews", expect.objectContaining({ method: "GET" }));
  const denied = await GET(new NextRequest("http://localhost:3000/api/research/scholarly/admin"), context(["admin"]));
  expect(denied.status).toBe(404);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("forwards the owner-scoped artifact list used to restore PDF retrieval state", async () => {
  const response = await GET(new NextRequest(`http://localhost:3000/api/research/scholarly/reviews/${reviewId}/artifacts`),
    context(["reviews", reviewId, "artifacts"]));
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith(
    `http://backend.example.test/research/reviews/${reviewId}/artifacts`,
    expect.objectContaining({ method: "GET" }),
  );
});

it("forwards only valid owner-scoped extracted PDF page paths", async () => {
  const artifactId = "22222222-2222-4222-8222-222222222222";
  const path = ["reviews", reviewId, "artifacts", artifactId, "pages", "2"];
  const response = await GET(new NextRequest(`http://localhost:3000/api/research/scholarly/${path.join("/")}`), context(path));
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledWith(
    `http://backend.example.test/research/reviews/${reviewId}/artifacts/${artifactId}/pages/2`,
    expect.objectContaining({ method: "GET", cache: "no-store" }),
  );
  const denied = await GET(new NextRequest("http://localhost:3000/api/research/scholarly/reviews/x/artifacts/y/pages/1"),
    context(["reviews", reviewId, "artifacts", "../private", "pages", "1"]));
  expect(denied.status).toBe(404);
});

it("validates page identity before displaying extracted text", async () => {
  const artifactId = "22222222-2222-4222-8222-222222222222";
  vi.mocked(fetch).mockResolvedValue(Response.json({ artifactId, recordId: "paper", pageNumber: 2, text: "Exact passage", claimSupportVerified: false }));
  await expect(getArtifactPage(reviewId, artifactId, 2)).resolves.toMatchObject({ text: "Exact passage" });
  vi.mocked(fetch).mockResolvedValue(Response.json({ artifactId: "other", recordId: "paper", pageNumber: 2, text: "wrong", claimSupportVerified: false }));
  await expect(getArtifactPage(reviewId, artifactId, 2)).rejects.toThrow("invalid PDF page");
});

it("treats a repeated PDF import as reuse of the existing record", async () => {
  vi.mocked(fetch).mockResolvedValue(Response.json({ recordId: "existing", sourceArtifactId: "pdf-1", alreadyImported: true }, { status: 200 }));
  const imported = await importPdf(reviewId, "A paper", new File(["%PDF-fixture"], "paper.pdf", { type: "application/pdf" }));
  expect(imported).toEqual({ recordId: "existing", artifactId: "pdf-1", alreadyImported: true });
});

it("forwards record-scoped decisions through the authenticated proxy", async () => {
  await POST(new NextRequest("http://localhost:3000/api/research/scholarly/reviews/record", {
    method: "POST", headers: { origin: "http://localhost:3000", "content-type": "application/json" },
    body: JSON.stringify({ stage: "title_abstract", outcome: "include" }),
  }), context(["reviews", reviewId, "records", "record-1", "decisions"]));
  expect(fetch).toHaveBeenCalledWith(
    `http://backend.example.test/research/reviews/${reviewId}/records/record-1/decisions`,
    expect.objectContaining({ method: "POST" }),
  );
});

it("rejects cross-origin PDF writes and PDF bodies above the 4 MiB BFF limit", async () => {
  const url = `http://localhost:3000/api/research/scholarly/reviews/${reviewId}/imports/pdf?title=Report`;
  const originDenied = await uploadPdf(new NextRequest(url, {
    method: "POST", headers: { origin: "https://other.example", "content-type": "application/pdf" },
    body: "%PDF-example",
  }), { params: Promise.resolve({ reviewId }) });
  expect(originDenied.status).toBe(403);
  const tooLarge = await uploadPdf(new NextRequest(url, {
    method: "POST", headers: { origin: "http://localhost:3000", "content-type": "application/pdf", "content-length": String(4 * 1024 * 1024 + 1) },
    body: "%PDF-example",
  }), { params: Promise.resolve({ reviewId }) });
  expect(tooLarge.status).toBe(413);
  expect(fetch).not.toHaveBeenCalled();
});

it("sends validated raw PDF bytes to the backend with verified identity", async () => {
  vi.mocked(fetch).mockResolvedValue(Response.json({ record_id: "record-1" }, { status: 201 }));
  const url = `http://localhost:3000/api/research/scholarly/reviews/${reviewId}/imports/pdf?title=Report`;
  const response = await uploadPdf(new NextRequest(url, {
    method: "POST", headers: { origin: "http://localhost:3000", "content-type": "application/pdf" },
    body: "%PDF-example",
  }), { params: Promise.resolve({ reviewId }) });
  expect(response.status).toBe(201);
  const [target, sent] = vi.mocked(fetch).mock.calls[0] ?? [];
  expect(String(target)).toBe(`http://backend.example.test/research/reviews/${reviewId}/imports/pdf?title=Report`);
  expect(sent?.method).toBe("POST");
  expect(new Headers(sent?.headers).get("x-verified-account-id")).toBe("account");
  expect(new TextDecoder().decode(sent?.body as Uint8Array)).toBe("%PDF-example");
});

it("shows a useful DOI validation error and preserves the backend's 422 detail", async () => {
  await expect(importDoi(reviewId, "an article title")).rejects.toThrow("Enter a DOI");
  expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValue(Response.json({ detail: "invalid DOI" }, { status: 422 }));
  await expect(importDoi(reviewId, "10.1038/s41586-020-2649-2")).rejects.toThrow("invalid DOI");
  expect(fetch).toHaveBeenCalledWith(
    `/api/research/scholarly/reviews/${reviewId}/imports/doi`,
    expect.objectContaining({ method: "POST" }),
  );
});

it("restores imported PDF metadata when a review is loaded again", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    const path = String(input);
    if (path.endsWith("/artifacts")) return Response.json([{
      recordId: "record-1", artifactId: "artifact-1", pageNumbers: [1, 2],
    }]);
    if (path.endsWith(`/reviews/${reviewId}`)) return Response.json({ id: reviewId, title: "Review", question: "Question" });
    if (path.endsWith("/records")) return Response.json([{ record_id: "record-1", title: "Paper", provider: "user_pdf_upload" }]);
    return Response.json([]);
  });
  const loaded = await getReview(reviewId);
  expect(loaded).toEqual(expect.objectContaining({
    artifacts: [{ recordId: "record-1", artifactId: "artifact-1", pageNumbers: [1, 2] }],
  }));
  expect(fetch).toHaveBeenCalledWith(`/api/research/scholarly/reviews/${reviewId}/artifacts`, expect.anything());
});

it("does not offer evidence until the same PDF is retrieved and included at full text", () => {
  const detail: ReviewDetail = {
    reviewId, title: "Review", question: "Question", records: [], evidence: [],
    artifacts: [{ recordId: "paper-1", artifactId: "pdf-1", pageNumbers: [1] }],
    retrievals: [{ record_id: "paper-1", status: "retrieved", source_id: "pdf-1" }],
    decisions: [],
  };
  expect(evidenceSourceForRecord(detail, "paper-1")).toBeNull();
  detail.decisions.push({ record_id: "paper-1", stage: "full_text", outcome: "include", exclusion_reason: null, source_id: "pdf-1" });
  expect(evidenceSourceForRecord(detail, "paper-1")).toEqual(detail.artifacts[0]);
  expect(evidenceSourceForRecord(detail, "paper-2")).toBeNull();
  detail.retrievals = [{ record_id: "paper-1", status: "retrieved", source_id: "another-records-pdf" }];
  expect(evidenceSourceForRecord(detail, "paper-1")).toBeNull();
});
