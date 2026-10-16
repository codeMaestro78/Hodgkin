import { NextRequest } from "next/server";
import { createAuthClient } from "../../../lib/auth/server";
import { authConfigured, authDestination } from "../../../lib/auth/config";
import { authJson, sameOrigin } from "../../../lib/auth/http";
import {
  canComplete,
  onboardingRequestSchema,
  readOnboarding,
} from "../../../lib/onboarding";

export const runtime = "nodejs";
export async function GET() {
  if (!authConfigured())
    return authJson({ error: "Account service is not configured." }, 503);
  try {
    const supabase = await createAuthClient();
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user || data.user.is_anonymous)
      return authJson({ error: "Sign in to continue." }, 401);
    return authJson({ profile: readOnboarding(data.user.user_metadata) });
  } catch {
    return authJson(
      { error: "Could not load your setup. Please try again." },
      503,
    );
  }
}
export async function POST(request: NextRequest) {
  if (!sameOrigin(request))
    return authJson({ error: "Cross-site requests are not allowed." }, 403);
  if (!authConfigured())
    return authJson({ error: "Account service is not configured." }, 503);
  // Limit both declared and actual input; never accept caller-controlled identities.
  if (Number(request.headers.get("content-length")) > 10000)
    return authJson({ error: "Setup is too large." }, 413);
  try {
    const supabase = await createAuthClient();
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user || data.user.is_anonymous)
      return authJson({ error: "Sign in to save your setup." }, 401);
    if (!data.user.email_confirmed_at)
      return authJson({ error: "Confirm your email before continuing." }, 403);
    const raw = await request.text();
    if (raw.length > 10000)
      return authJson({ error: "Setup is too large." }, 413);
    let json: unknown;
    try {
      json = JSON.parse(raw);
    } catch {
      return authJson({ error: "Invalid setup request." }, 400);
    }
    const parsed = onboardingRequestSchema.safeParse(json);
    if (!parsed.success)
      return authJson(
        { error: "Check your setup details and try again." },
        400,
      );
    const { action, draft, step, next } = parsed.data;
    if (action === "complete" && !canComplete(draft))
      return authJson(
        { error: "Choose your role, field and workplace, or skip setup." },
        400,
      );
    const previous = readOnboarding(data.user.user_metadata);
    const profile = {
      ...draft,
      version: 1 as const,
      step,
      status:
        action === "complete"
          ? ("completed" as const)
          : action === "skip"
            ? ("skipped" as const)
            : previous?.status === "completed" || previous?.status === "skipped"
              ? previous.status
              : ("in_progress" as const),
      updatedAt: new Date().toISOString(),
    };
    const saved = await supabase.auth.updateUser({
      data: { research_onboarding: profile },
    });
    if (saved.error)
      return authJson(
        {
          error: "Your setup was not saved. Retry without losing your answers.",
        },
        saved.error.status === 429 ? 429 : 502,
      );
    return authJson({ profile, redirect: authDestination(next) });
  } catch {
    return authJson(
      {
        error:
          "Account service is unavailable. Your answers are still on this page.",
      },
      503,
    );
  }
}
