import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";
import { appOrigin, authConfig, authConfigured } from "./lib/auth/config";
import { onboardingDestination } from "./lib/onboarding";

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const copySession = (target: NextResponse) => {
    response.cookies.getAll().forEach((cookie) => target.cookies.set(cookie));
    target.headers.set("cache-control", "private, no-store");
    return target;
  };
  const researchPage = request.nextUrl.pathname.startsWith("/research");
  const protectedPage =
    researchPage || request.nextUrl.pathname === "/onboarding";
  if (!authConfigured()) {
    if (!protectedPage) return response;
    const login = new URL("/login", appOrigin());
    login.searchParams.set("error", "configuration");
    return copySession(NextResponse.redirect(login));
  }
  const { url, key } = authConfig();
  const supabase = createServerClient(url, key, {
    cookieOptions: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
    },
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (values) => {
        values.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        values.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });
  try {
    const { data, error } = await supabase.auth.getClaims();
    if (
      protectedPage &&
      (error || !data?.claims.sub || data.claims.is_anonymous)
    ) {
      const login = new URL("/login", appOrigin());
      login.searchParams.set("next", request.nextUrl.pathname);
      return copySession(NextResponse.redirect(login));
    }
    if (researchPage) {
      const identity = await supabase.auth.getUser();
      if (
        identity.error ||
        !identity.data.user ||
        identity.data.user.is_anonymous
      )
        return copySession(
          NextResponse.redirect(new URL("/login", appOrigin())),
        );
      const destination = onboardingDestination(
        request.nextUrl.pathname,
        identity.data.user.user_metadata,
      );
      if (destination !== request.nextUrl.pathname)
        return copySession(
          NextResponse.redirect(new URL(destination, appOrigin())),
        );
    }
  } catch {
    if (protectedPage)
      return copySession(
        NextResponse.redirect(new URL("/login?error=unavailable", appOrigin())),
      );
  }
  return copySession(response);
}

export const config = {
  matcher: [
    "/research/:path*",
    "/onboarding",
    "/login",
    "/signup",
    "/forgot-password",
    "/reset-password",
  ],
};
