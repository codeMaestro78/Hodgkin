import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({ getUser: vi.fn(), getSession: vi.fn() }));
vi.mock("../lib/auth/server", () => ({ createAuthClient: async () => ({ auth }) }));
import { GET, POST } from "../app/api/research/scholarly/[...path]/route";
import { POST as uploadPdf } from "../app/api/research/scholarly/reviews/[reviewId]/imports/pdf/route";

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
