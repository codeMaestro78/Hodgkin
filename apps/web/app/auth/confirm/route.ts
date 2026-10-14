import { NextRequest, NextResponse } from "next/server";
import { createAuthClient } from "../../../lib/auth/server";
import { appOrigin, authDestination } from "../../../lib/auth/config";
import { onboardingDestination } from "../../../lib/onboarding";

export async function GET(request: NextRequest) {
  const hash = request.nextUrl.searchParams.get("token_hash");
  const type = request.nextUrl.searchParams.get("type");
  try {
    if (
      hash &&
      (type === "signup" || type === "email" || type === "recovery")
    ) {
      const supabase = await createAuthClient();
      const { data, error } = await supabase.auth.verifyOtp({
        token_hash: hash,
        type,
      });
      const next =
        type === "recovery"
          ? "/reset-password"
          : authDestination(request.nextUrl.searchParams.get("next"));
      if (!error)
        return NextResponse.redirect(
          new URL(
            onboardingDestination(next, data.user?.user_metadata),
            appOrigin(),
          ),
          {
            headers: { "cache-control": "private, no-store" },
          },
        );
    }
  } catch {
    /* Tokens and upstream errors must not be echoed into the page. */
  }
  return NextResponse.redirect(
    new URL("/login?error=confirmation", appOrigin()),
    { headers: { "cache-control": "private, no-store" } },
  );
}
