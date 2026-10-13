import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const auth = vi.hoisted(() => ({
  signInWithPassword: vi.fn(),
  signUp: vi.fn(),
  signInWithOAuth: vi.fn(),
  signOut: vi.fn(),
  getUser: vi.fn(),
  getSession: vi.fn(),
  resetPasswordForEmail: vi.fn(),
  updateUser: vi.fn(),
  exchangeCodeForSession: vi.fn(),
  verifyOtp: vi.fn(),
}));
vi.mock("../lib/auth/server", () => ({
  createAuthClient: async () => ({ auth }),
}));
import { POST } from "../app/api/auth/[action]/route";
import { GET as callback } from "../app/auth/callback/route";
import { GET as confirm } from "../app/auth/confirm/route";
import { forwardResearch } from "../lib/research-proxy";
import { authDestination } from "../lib/auth/config";

function request(
  action: string,
  body: unknown = {},
  origin = "http://localhost:3000",
) {
  return new NextRequest(`http://localhost:3000/api/auth/${action}`, {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
async function run(action: string, body: unknown = {}, origin?: string) {
  return POST(request(action, body, origin), {
    params: Promise.resolve({ action }),
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_APP_URL", "http://localhost:3000");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://identity.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "fixture-public");
  vi.stubEnv("INTERNAL_SERVICE_AUTH", "fixture-service");
  vi.stubEnv("RESEARCH_API_URL", "http://backend.example.test");
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("account flows", () => {
  it("rejects cross-origin requests before credentials reach Supabase", async () => {
    expect(
      (
        await run(
          "login",
          { email: "user@example.test", password: "fixture-password" },
          "https://evil.example",
        )
      ).status,
    ).toBe(403);
    expect(auth.signInWithPassword).not.toHaveBeenCalled();
  });
  it("fails closed when Auth configuration is absent", async () => {
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "");
    expect((await run("signup")).status).toBe(503);
  });
  it("validates signup fields before invoking auth", async () => {
    expect(
      (await run("signup", { email: "bad", password: "short" })).status,
    ).toBe(400);
    expect(auth.signUp).not.toHaveBeenCalled();
  });
  it("creates the Auth user with display metadata and confirmation callback", async () => {
    auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
    const response = await run("signup", {
      name: "Researcher",
      email: "user@example.test",
      password: "fixture-password",
    });
    expect(response.status).toBe(200);
    expect((await response.json()).message).toContain("confirm your email");
    expect(auth.signUp).toHaveBeenCalledWith(
      expect.objectContaining({
        options: {
          data: { full_name: "Researcher" },
          emailRedirectTo:
            "http://localhost:3000/auth/callback?next=%2Fresearch",
        },
      }),
    );
  });
  it("logs in and restricts redirect destinations", async () => {
    auth.signInWithPassword.mockResolvedValue({ error: null });
    expect(
      await (
        await run("login", {
          email: "user@example.test",
          password: "fixture-password",
          next: "https://evil.example",
        })
      ).json(),
    ).toEqual({ redirect: "/research" });
  });
  it("returns useful confirmation errors without leaking upstream details", async () => {
    auth.signInWithPassword.mockResolvedValue({
      error: { code: "email_not_confirmed" },
    });
    expect(
      (
        await (
          await run("login", {
            email: "user@example.test",
            password: "fixture-password",
          })
        ).json()
      ).error,
    ).toContain("Confirm your email");
  });
  it("starts Google through Supabase PKCE with an allowlisted callback", async () => {
    auth.signInWithOAuth.mockResolvedValue({
      data: { url: "https://identity.example.test/auth/v1/authorize" },
      error: null,
    });
    expect((await run("google", { next: "//evil.example" })).status).toBe(200);
    expect(auth.signInWithOAuth).toHaveBeenCalledWith({
      provider: "google",
      options: {
        redirectTo: "http://localhost:3000/auth/callback?next=%2Fresearch",
        skipBrowserRedirect: true,
        queryParams: { prompt: "select_account" },
      },
    });
  });
  it("exchanges OAuth code before redirecting and handles denied consent", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: null });
    const response = await callback(
      new NextRequest(
        "http://localhost:3000/auth/callback?code=fixture&next=https://evil.example",
      ),
    );
    expect(auth.exchangeCodeForSession).toHaveBeenCalledWith("fixture");
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/research",
    );
    expect(
      (
        await callback(
          new NextRequest(
            "http://localhost:3000/auth/callback?error=access_denied",
          ),
        )
      ).headers.get("location"),
    ).toContain("error=callback");
  });
  it("verifies confirmation and recovery tokens without trusting arbitrary types", async () => {
    auth.verifyOtp.mockResolvedValue({ error: null });
    const response = await confirm(
      new NextRequest(
        "http://localhost:3000/auth/confirm?token_hash=fixture&type=recovery&next=https://evil.example",
      ),
    );
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/reset-password",
    );
    expect(
      (
        await confirm(
          new NextRequest(
            "http://localhost:3000/auth/confirm?token_hash=fixture&type=admin",
          ),
        )
      ).headers.get("location"),
    ).toContain("error=confirmation");
  });
  it("requests password recovery with a reset-specific destination", async () => {
    auth.resetPasswordForEmail.mockResolvedValue({ error: null });
    expect((await run("forgot", { email: "user@example.test" })).status).toBe(
      200,
    );
    expect(auth.resetPasswordForEmail).toHaveBeenCalledWith(
      "user@example.test",
      {
        redirectTo:
          "http://localhost:3000/auth/callback?next=%2Freset-password",
      },
    );
  });
  it("rejects unauthenticated password changes", async () => {
    auth.getUser.mockResolvedValue({ data: { user: null }, error: null });
    expect((await run("reset", { password: "fixture-password" })).status).toBe(
      401,
    );
    expect(auth.updateUser).not.toHaveBeenCalled();
  });
  it("signs out through the cookie-backed Supabase client", async () => {
    auth.signOut.mockResolvedValue({ error: null });
    expect(await (await run("logout")).json()).toEqual({ redirect: "/login" });
    expect(auth.signOut).toHaveBeenCalledWith({ scope: "local" });
  });
  it.each([
    "//evil.example",
    "https://evil.example",
    "/research/../login",
    "/\\evil.example",
  ])("rejects unsafe next path %s", (value) => {
    expect(authDestination(value)).toBe("/research");
  });
});

describe("research BFF identity", () => {
  it("rejects missing session despite forged identity headers", async () => {
    auth.getUser.mockResolvedValue({ data: { user: null }, error: null });
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const req = new NextRequest("http://localhost:3000/api/research/runs", {
      headers: { "x-development-user-id": "forged" },
    });
    expect((await forwardResearch(req, "/research/runs")).status).toBe(401);
    expect(fetch).not.toHaveBeenCalled();
  });
  it("forwards only the verified user's bearer token and internal secret", async () => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    const fetch = vi.fn().mockResolvedValue(new Response('{"runs":[]}'));
    vi.stubGlobal("fetch", fetch);
    const req = new NextRequest("http://localhost:3000/api/research/runs", {
      headers: {
        authorization: "Bearer forged",
        "x-development-tenant-id": "forged",
      },
    });
    expect((await forwardResearch(req, "/research/runs")).status).toBe(200);
    const headers = fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer fixture-access");
    expect(headers.get("x-internal-service-auth")).toBe("fixture-service");
    expect(headers.has("x-development-tenant-id")).toBe(false);
  });
  it("keeps streaming response bodies uncached and private", async () => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("data: {}\n\n")),
    );
    const response = await forwardResearch(
      new NextRequest("http://localhost:3000/api/research/runs/run/events"),
      "/research/runs/run/events",
      "GET",
      true,
    );
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toContain("private");
    expect(await response.text()).toBe("data: {}\n\n");
  });
});
