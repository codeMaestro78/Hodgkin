import { NextRequest, NextResponse } from "next/server";
import { createAuthClient } from "../../../lib/auth/server";
import { appOrigin, authDestination } from "../../../lib/auth/config";
import { onboardingDestination } from "../../../lib/onboarding";

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get("code");
  try {
    if (code && !request.nextUrl.searchParams.has("error")) {
      const supabase = await createAuthClient();
      const { data, error } = await supabase.auth.exchangeCodeForSession(code);
      if (!error)
        return NextResponse.redirect(
          new URL(
            onboardingDestination(
              authDestination(request.nextUrl.searchParams.get("next")),
              data.user?.user_metadata,
            ),
            appOrigin(),
          ),
          { headers: { "cache-control": "private, no-store" } },
        );
    }
  } catch {
    /* Failed, expired or cross-browser PKCE exchanges return to login. */
  }
  return NextResponse.redirect(new URL("/login?error=callback", appOrigin()), {
    headers: { "cache-control": "private, no-store" },
  });
}
