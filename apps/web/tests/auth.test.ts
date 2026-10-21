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
import { emptyOnboarding } from "../lib/onboarding";

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
    auth.signInWithPassword.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    expect(
      await (
        await run("login", {
          email: "user@example.test",
          password: "fixture-password",
          next: "https://evil.example",
        })
      ).json(),
    ).toEqual({ redirect: "/onboarding?next=%2Fresearch" });
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
    auth.exchangeCodeForSession.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    const response = await callback(
      new NextRequest(
        "http://localhost:3000/auth/callback?code=fixture&next=https://evil.example",
      ),
    );
    expect(auth.exchangeCodeForSession).toHaveBeenCalledWith("fixture");
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/onboarding?next=%2Fresearch",
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
    auth.verifyOtp.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
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
  it.each([
    "/research/11111111-1111-4111-8111-111111111111",
    "/research/automation",
  ])("returns completed accounts directly to %s", async (next) => {
    auth.signInWithPassword.mockResolvedValue({
      data: {
        user: {
          user_metadata: {
            research_onboarding: {
              ...emptyOnboarding,
              version: 1,
              step: 6,
              status: "skipped",
              updatedAt: "2026-10-13T10:00:00.000Z",
            },
          },
        },
      },
      error: null,
    });
    expect(
      await (
        await run("login", {
          email: "user@example.test",
          password: "fixture-password",
          next,
        })
      ).json(),
    ).toEqual({ redirect: next });
  });
  it("preserves Automation through login and the setup redirect", async () => {
    auth.signInWithPassword.mockResolvedValue({
      data: { user: { user_metadata: {} } },
      error: null,
    });
    expect(
      await (
        await run("login", {
          email: "user@example.test",
          password: "fixture-password",
          next: "/research/automation",
        })
      ).json(),
    ).toEqual({ redirect: "/onboarding?next=%2Fresearch%2Fautomation" });
  });
  it("routes immediate-session signup to setup", async () => {
    auth.signUp.mockResolvedValue({
      data: { user: { user_metadata: {} }, session: {} },
      error: null,
    });
    expect(
      await (
        await run("signup", {
          name: "Fixture",
          email: "user@example.test",
          password: "fixture-password",
        })
      ).json(),
    ).toEqual({ redirect: "/onboarding?next=%2Fresearch" });
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
  it("guards cross-origin DELETEs and preserves a valid no-content response", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const crossOrigin = new NextRequest(
      "http://localhost:3000/api/research/runs/run-id",
      { method: "DELETE", headers: { origin: "https://evil.example" } },
    );
    expect(
      (await forwardResearch(crossOrigin, "/research/runs/run-id", "DELETE"))
        .status,
    ).toBe(403);
    expect(upstream).not.toHaveBeenCalled();

    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    upstream.mockResolvedValue(new Response(null, { status: 204 }));
    const sameOrigin = new NextRequest(
      "http://localhost:3000/api/research/runs/run-id",
      { method: "DELETE", headers: { origin: "http://localhost:3000" } },
    );
    const response = await forwardResearch(
      sameOrigin,
      "/research/runs/run-id",
      "DELETE",
    );
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    expect(upstream.mock.calls[0]![1].method).toBe("DELETE");
  });

  it("normalizes a plain-text upstream 500 into safe JSON for the client", async () => {
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
      vi.fn().mockResolvedValue(
        new Response("Internal Server Error", {
          status: 500,
          headers: { "content-type": "text/plain" },
        }),
      ),
    );

    const response = await forwardResearch(
      new NextRequest("http://localhost:3000/api/research/runs", {
        method: "POST",
        headers: { origin: "http://localhost:3000" },
        body: JSON.stringify({ question: "A test question" }),
      }),
      "/research/runs",
      "POST",
    );

    expect(response.status).toBe(500);
    expect(response.headers.get("content-type")).toContain("application/json");
    await expect(response.json()).resolves.toEqual({
      error: "Research service encountered an internal error. Please try again.",
    });
  });

  it("rejects an account-switched submission before upstream dispatch", async () => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const request = new NextRequest("http://localhost:3000/api/research/runs", {
      method: "POST",
      headers: {
        origin: "http://localhost:3000",
        "x-research-account-id": "previous-account",
      },
      body: JSON.stringify({ question: "Private draft" }),
    });
    expect(
      (await forwardResearch(request, "/research/runs", "POST")).status,
    ).toBe(409);
    expect(auth.getSession).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it("accepts the matching account hint without forwarding it as identity", async () => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    const body = JSON.stringify({ question: "Current account draft" });
    const request = new NextRequest("http://localhost:3000/api/research/runs", {
      method: "POST",
      headers: {
        origin: "http://localhost:3000",
        "x-research-account-id": "verified",
      },
      body,
    });
    const response = await forwardResearch(request, "/research/runs", "POST");
    expect(response.status).toBe(200);
    expect(response.headers.get("server-timing")).toMatch(
      /^auth;dur=\d+\.\d, upstream_headers;dur=\d+\.\d, proxy;dur=\d+\.\d$/,
    );
    expect(auth.getUser).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0]![1].body).toBe(body);
    expect(
      (fetch.mock.calls[0]![1].headers as Headers).has("x-research-account-id"),
    ).toBe(false);
  });
  it("treats an aborted browser request as disconnect rather than upstream failure", async () => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockRejectedValue(
          new DOMException("Client disconnected", "AbortError"),
        ),
    );
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const response = await forwardResearch(
        new NextRequest("http://localhost:3000/api/research/runs", {
          signal: controller.signal,
        }),
        "/research/runs",
      );
      expect(response.status).toBe(499);
      expect(log).not.toHaveBeenCalled();
    } finally {
      log.mockRestore();
    }
  });
  it.each([
    "/research/runs/run/approve",
    "/research/batches",
    "/research/schedules",
    "/research/schedules/id/disable",
  ])("forwards POST bodies intact to %s", async (path) => {
    auth.getUser.mockResolvedValue({
      data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
      error: null,
    });
    auth.getSession.mockResolvedValue({
      data: {
        session: { user: { id: "verified" }, access_token: "fixture-access" },
      },
    });
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    const body = JSON.stringify({ decision: "approve", planId: "fixture" });
    const req = new NextRequest(`http://localhost:3000/api${path}`, {
      method: "POST",
      headers: { origin: "http://localhost:3000" },
      body,
    });
    expect((await forwardResearch(req, path, "POST")).status).toBe(200);
    expect(fetch.mock.calls[0]![1].body).toBe(body);
  });
  it.each(["focused", "balanced", "deep", null, undefined])(
    "forwards mode %s and independent budgets opaquely with verified auth",
    async (mode) => {
      auth.getUser.mockResolvedValue({
        data: { user: { id: "verified", email_confirmed_at: "2026-01-01" } },
        error: null,
      });
      auth.getSession.mockResolvedValue({
        data: {
          session: { user: { id: "verified" }, access_token: "fixture-access" },
        },
      });
      const upstream = JSON.stringify({
        runId: "fixture",
        mode,
        modePolicyVersion: "research-mode-policy-v1",
        modeResolution: mode == null ? "legacy-inferred" : "explicit",
      });
      const fetch = vi
        .fn()
        .mockResolvedValue(new Response(upstream, { status: 202 }));
      vi.stubGlobal("fetch", fetch);
      const body = JSON.stringify({
        question: "What is a database?",
        mode,
        budgetOverrides: {
          maxProviderOperations: 4,
          maxSources: 2,
          maxWallClockMs: 60_000,
        },
      });
      const req = new NextRequest("http://localhost:3000/api/research/runs", {
        method: "POST",
        body,
        headers: {
          origin: "http://localhost:3000",
          "x-research-account-id": "verified",
          "idempotency-key": "fixture-mode-request",
          authorization: "Bearer forged",
        },
      });
      const response = await forwardResearch(req, "/research/runs", "POST");
      expect(response.status).toBe(202);
      expect(await response.text()).toBe(upstream);
      const forwarded = fetch.mock.calls[0]![1];
      expect(forwarded.body).toBe(body);
      expect(forwarded.headers.get("authorization")).toBe(
        "Bearer fixture-access",
      );
      expect(forwarded.headers.get("idempotency-key")).toBe(
        "fixture-mode-request",
      );
      expect(forwarded.headers.get("x-internal-service-auth")).toBe(
        "fixture-service",
      );
      expect(forwarded.headers.has("x-research-account-id")).toBe(false);
    },
  );
  it("rejects oversized research bodies before authentication or upstream dispatch", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const req = new NextRequest("http://localhost:3000/api/research/batches", {
      method: "POST",
      headers: { origin: "http://localhost:3000" },
      body: "x".repeat(256 * 1024 + 1),
    });
    expect(
      (await forwardResearch(req, "/research/batches", "POST")).status,
    ).toBe(413);
    expect(auth.getUser).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
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
    const fetch = vi.fn().mockResolvedValue(new Response("data: {}\n\n"));
    vi.stubGlobal("fetch", fetch);
    const response = await forwardResearch(
      new NextRequest("http://localhost:3000/api/research/runs/run/events", {
        headers: { "last-event-id": "42" },
      }),
      "/research/runs/run/events",
      "GET",
      true,
    );
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toContain("private");
    expect(
      (fetch.mock.calls[0]![1].headers as Headers).get("last-event-id"),
    ).toBe("42");
    expect(await response.text()).toBe("data: {}\n\n");
  });
});
