import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";
import { appOrigin, authConfig, authConfigured } from "./lib/auth/config";

export async function proxy(request: NextRequest) {
  let response = NextResponse.next({ request });
  const copySession = (target: NextResponse) => {
    response.cookies.getAll().forEach((cookie) => target.cookies.set(cookie));
    target.headers.set("cache-control", "private, no-store");
    return target;
  };
  const protectedPage = request.nextUrl.pathname.startsWith("/research");
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
    "/login",
    "/signup",
    "/forgot-password",
    "/reset-password",
  ],
};
