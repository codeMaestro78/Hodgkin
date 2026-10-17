import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({ getUser: vi.fn(), getSession: vi.fn() }));
vi.mock("../lib/auth/server", () => ({
  createAuthClient: async () => ({ auth }),
}));
import {
  GET as projects,
  POST as createProject,
} from "../app/api/research/projects/route";
import {
  GET as items,
  POST as save,
} from "../app/api/research/library/items/route";
import { POST as remove } from "../app/api/research/library/items/[itemId]/remove/route";
import { POST as organize } from "../app/api/research/library/items/[itemId]/organize/route";

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_APP_URL", "http://localhost:3000");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://identity.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "fixture-public");
  vi.stubEnv("INTERNAL_SERVICE_AUTH", "fixture-service");
  vi.stubEnv("RESEARCH_API_URL", "http://backend.example.test");
  const user = {
    id: "account",
    email_confirmed_at: "2026-10-16T10:00:00Z",
    is_anonymous: false,
  };
  auth.getUser.mockResolvedValue({ data: { user }, error: null });
  auth.getSession.mockResolvedValue({
    data: { session: { user, access_token: "fixture-token" } },
  });
  vi.spyOn(console, "info").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(Response.json({ items: [], nextCursor: null })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

it("forwards only supported list filters, preserving a null terminal cursor", async () => {
  const request = new NextRequest(
    "http://localhost:3000/api/research/library/items?query=a%26b&projectId=p&kind=source&tag=t&after=c&limit=50&tenantId=forged",
  );
  const response = await items(request);
  expect(fetch).toHaveBeenCalledWith(
    "http://backend.example.test/research/library/items?query=a%26b&projectId=p&kind=source&tag=t&after=c&limit=50",
    expect.objectContaining({ method: "GET", cache: "no-store" }),
  );
  expect(await response.json()).toEqual({ items: [], nextCursor: null });
  expect(response.headers.get("cache-control")).toBe("private, no-store");
});

it("lists projects through the authenticated backend proxy", async () => {
  await projects(
    new NextRequest(
      "http://localhost:3000/api/research/projects?tenantId=forged",
    ),
  );
  expect(fetch).toHaveBeenCalledWith(
    "http://backend.example.test/research/projects",
    expect.objectContaining({ method: "GET" }),
  );
});

it.each([
  [createProject, "/projects", { name: "Evidence" }],
  [save, "/library/items", { reportId: "report", tags: [], notes: "" }],
] as const)(
  "forwards mutation bodies through the existing POST guard",
  async (handler, path, body) => {
    const request = new NextRequest(
      `http://localhost:3000/api/research${path}`,
      {
        method: "POST",
        headers: { origin: "http://localhost:3000" },
        body: JSON.stringify(body),
      },
    );
    await handler(request);
    expect(fetch).toHaveBeenCalledWith(
      `http://backend.example.test/research${path}`,
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  },
);

it.each([
  [remove, "remove", {}],
  [
    organize,
    "organize",
    { projectId: null, tags: ["queues"], notes: "Read again" },
  ],
] as const)(
  "encodes item IDs and forwards item mutations",
  async (handler, action, body) => {
    const request = new NextRequest(
      `http://localhost:3000/api/research/library/items/id/${action}`,
      {
        method: "POST",
        headers: { origin: "http://localhost:3000" },
        body: JSON.stringify(body),
      },
    );
    await handler(request, { params: Promise.resolve({ itemId: "item/id" }) });
    expect(fetch).toHaveBeenCalledWith(
      `http://backend.example.test/research/library/items/item%2Fid/${action}`,
      expect.objectContaining({ method: "POST", body: JSON.stringify(body) }),
    );
  },
);

it("rejects cross-origin library writes before fetching the backend", async () => {
  const response = await createProject(
    new NextRequest("http://localhost:3000/api/research/projects", {
      method: "POST",
      headers: { origin: "https://evil.example" },
      body: '{"name":"Evidence"}',
    }),
  );
  expect(response.status).toBe(403);
  expect(fetch).not.toHaveBeenCalled();
});

it("requires a verified session for library reads", async () => {
  auth.getUser.mockResolvedValue({ data: { user: null }, error: null });
  expect(
    (
      await items(
        new NextRequest("http://localhost:3000/api/research/library/items"),
      )
    ).status,
  ).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});
