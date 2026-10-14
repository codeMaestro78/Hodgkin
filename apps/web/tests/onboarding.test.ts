import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import {
  canComplete,
  emptyOnboarding,
  needsOnboarding,
  onboardingDestination,
  onboardingDraftSchema,
  readOnboarding,
  stepValid,
} from "../lib/onboarding";
const auth = vi.hoisted(() => ({ getUser: vi.fn(), updateUser: vi.fn() }));
vi.mock("../lib/auth/server", () => ({
  createAuthClient: async () => ({ auth }),
}));
import { GET, POST } from "../app/api/onboarding/route";
const draft = {
  ...emptyOnboarding,
  role: "Researcher",
  field: "Computer science",
  workplace: "Independent" as const,
};
const profile = {
  ...draft,
  version: 1,
  step: 6,
  status: "completed",
  updatedAt: "2026-10-13T10:00:00.000Z",
};
function request(body: unknown, origin = "http://localhost:3000") {
  return new NextRequest("http://localhost:3000/api/onboarding", {
    method: "POST",
    headers: { origin, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}
beforeEach(() => {
  vi.resetAllMocks();
  vi.stubEnv("NEXT_PUBLIC_APP_URL", "http://localhost:3000");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://identity.example.test");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "fixture-public");
  auth.getUser.mockResolvedValue({
    data: {
      user: {
        id: "verified",
        email_confirmed_at: "2026-10-13",
        user_metadata: { full_name: "Fixture" },
      },
    },
    error: null,
  });
  auth.updateUser.mockResolvedValue({ error: null });
});
afterEach(() => vi.unstubAllEnvs());
describe("onboarding boundaries", () => {
  it("routes unfinished accounts but preserves completed/skipped accounts", () => {
    expect(needsOnboarding({})).toBe(true);
    expect(needsOnboarding({ research_onboarding: profile })).toBe(false);
    expect(
      needsOnboarding({
        research_onboarding: { ...profile, status: "skipped" },
      }),
    ).toBe(false);
    expect(
      needsOnboarding({
        research_onboarding: { ...profile, status: "in_progress" },
      }),
    ).toBe(true);
    expect(onboardingDestination("/reset-password", {})).toBe(
      "/reset-password",
    );
    expect(onboardingDestination("/research/reports", {})).toBe(
      "/onboarding?next=%2Fresearch%2Freports",
    );
  });
  it("rejects corrupt metadata and privileged preference fields", () => {
    expect(
      readOnboarding({ research_onboarding: { ...profile, version: 2 } }),
    ).toBeNull();
    expect(
      onboardingDraftSchema.safeParse({ ...draft, tenantId: "forged" }).success,
    ).toBe(false);
    expect(
      onboardingDraftSchema.safeParse({ ...draft, depth: "Unlimited" }).success,
    ).toBe(false);
    expect(
      onboardingDraftSchema.safeParse({ ...draft, topic: "x".repeat(1001) })
        .success,
    ).toBe(false);
  });
  it("requires meaningful selections but allows an omitted question", () => {
    expect(canComplete(draft)).toBe(true);
    expect(stepValid(1, { ...draft, role: "  " })).toBe(false);
    expect(canComplete({ ...draft, topic: "x" })).toBe(false);
  });
  it("rejects cross-origin writes before contacting identity", async () => {
    expect(
      (
        await POST(
          request({ action: "skip", step: 1, draft }, "https://evil.example"),
        )
      ).status,
    ).toBe(403);
    expect(auth.getUser).not.toHaveBeenCalled();
  });
  it("requires authenticated and confirmed identity for writes", async () => {
    auth.getUser.mockResolvedValue({ data: { user: null }, error: null });
    expect((await GET()).status).toBe(401);
    expect(
      (await POST(request({ action: "skip", step: 1, draft }))).status,
    ).toBe(401);
    auth.getUser.mockResolvedValue({
      data: { user: { id: "fixture", user_metadata: {} } },
      error: null,
    });
    expect(
      (await POST(request({ action: "skip", step: 1, draft }))).status,
    ).toBe(403);
    expect(auth.updateUser).not.toHaveBeenCalled();
  });
  it("saves only preferences on the verified account and sanitizes redirects", async () => {
    const response = await POST(
      request({
        action: "complete",
        step: 6,
        draft,
        next: "https://evil.example",
      }),
    );
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.redirect).toBe("/research");
    expect(body.profile.status).toBe("completed");
    expect(auth.updateUser).toHaveBeenCalledWith({
      data: { research_onboarding: body.profile },
    });
    expect(response.headers.get("cache-control")).toBe("private, no-store");
  });
  it("rejects forged identity and incomplete completion", async () => {
    expect(
      (
        await POST(
          request({ action: "save", step: 1, draft, userId: "forged" }),
        )
      ).status,
    ).toBe(400);
    expect(
      (
        await POST(
          request({ action: "complete", step: 6, draft: emptyOnboarding }),
        )
      ).status,
    ).toBe(400);
    expect(auth.updateUser).not.toHaveBeenCalled();
  });
  it("persists skip without requiring answers", async () => {
    const response = await POST(
      request({ action: "skip", step: 1, draft: emptyOnboarding }),
    );
    expect((await response.json()).profile.status).toBe("skipped");
  });
  it.each(["complete", "skip"])(
    "returns to Automation after %s",
    async (action) => {
      const response = await POST(
        request({ action, step: 6, draft, next: "/research/automation" }),
      );
      expect(response.status).toBe(200);
      expect((await response.json()).redirect).toBe("/research/automation");
    },
  );
  it("does not re-gate returning users editing preferences", async () => {
    auth.getUser.mockResolvedValue({
      data: {
        user: {
          id: "verified",
          email_confirmed_at: "2026-10-13",
          user_metadata: { research_onboarding: profile },
        },
      },
      error: null,
    });
    expect(
      (await (await POST(request({ action: "save", step: 2, draft }))).json())
        .profile.status,
    ).toBe("completed");
  });
  it("reports failed persistence rather than claiming completion", async () => {
    auth.updateUser.mockResolvedValue({ error: { status: 429 } });
    const response = await POST(
      request({ action: "complete", step: 6, draft }),
    );
    expect(response.status).toBe(429);
    expect((await response.json()).profile).toBeUndefined();
  });
});
