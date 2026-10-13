import { NextRequest } from "next/server";
import { z } from "zod";
import { createAuthClient } from "../../../../lib/auth/server";
import {
  appOrigin,
  authConfigured,
  authDestination,
} from "../../../../lib/auth/config";
import { authJson, sameOrigin } from "../../../../lib/auth/http";

export const runtime = "nodejs";
const credentials = z.object({
  email: z.email().max(254),
  password: z.string().min(1).max(128),
  name: z.string().trim().max(120).optional(),
  next: z.string().optional(),
});

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ action: string }> },
) {
  if (!sameOrigin(request))
    return authJson(
      { error: "This request must come from this application." },
      403,
    );
  if (!authConfigured())
    return authJson({ error: "Supabase Auth is not configured yet." }, 503);
  const { action } = await params;
  if (
    !["login", "signup", "google", "logout", "forgot", "reset"].includes(action)
  )
    return authJson({ error: "Unknown account action." }, 404);
  try {
    const supabase = await createAuthClient();
    if (action === "logout") {
      const { error } = await supabase.auth.signOut({ scope: "local" });
      if (error)
        return authJson(
          { error: "We couldn’t sign you out. Please try again." },
          502,
        );
      return authJson({ redirect: "/login" });
    }
    const body: unknown = await request.json();
    const next = authDestination(
      z.object({ next: z.string().optional() }).passthrough().safeParse(body)
        .data?.next,
    );
    if (action === "google") {
      const callback = new URL("/auth/callback", appOrigin());
      callback.searchParams.set(
        "next",
        next === "/reset-password" ? "/research" : next,
      );
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: callback.toString(),
          skipBrowserRedirect: true,
          queryParams: { prompt: "select_account" },
        },
      });
      if (error || !data.url)
        return authJson(
          {
            error:
              "Google sign-in is unavailable. Check the Supabase Google provider configuration.",
          },
          400,
        );
      return authJson({ redirect: data.url });
    }
    if (action === "forgot") {
      const parsed = z.object({ email: z.email().max(254) }).safeParse(body);
      if (!parsed.success)
        return authJson({ error: "Enter a valid email address." }, 400);
      const callback = new URL("/auth/callback", appOrigin());
      callback.searchParams.set("next", "/reset-password");
      const { error } = await supabase.auth.resetPasswordForEmail(
        parsed.data.email,
        { redirectTo: callback.toString() },
      );
      if (error)
        return authJson(
          { error: "We couldn’t request the reset email. Try again shortly." },
          error.status === 429 ? 429 : 400,
        );
      return authJson({
        message:
          "If an account exists for this email, you’ll receive a password-reset link.",
      });
    }
    if (action === "reset") {
      const parsed = z
        .object({ password: z.string().min(8).max(128) })
        .safeParse(body);
      if (!parsed.success)
        return authJson(
          { error: "Use a password with 8–128 characters." },
          400,
        );
      const { data, error } = await supabase.auth.getUser();
      if (error || !data.user)
        return authJson(
          { error: "Your reset link has expired. Request a new one." },
          401,
        );
      const result = await supabase.auth.updateUser({
        password: parsed.data.password,
      });
      if (result.error)
        return authJson(
          {
            error:
              "Password could not be updated. Use a different password or request a new link.",
          },
          400,
        );
      await supabase.auth.signOut({ scope: "local" });
      return authJson({ redirect: "/login?message=password-updated" });
    }
    const parsed = credentials.safeParse(body);
    if (
      !parsed.success ||
      (action === "signup" &&
        (parsed.data.password.length < 8 || !parsed.data.name))
    )
      return authJson(
        {
          error:
            "Enter a valid email, name, and password (8–128 characters for signup).",
        },
        400,
      );
    const { email, password, name } = parsed.data;
    if (action === "login") {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error)
        return authJson(
          {
            error:
              error.code === "email_not_confirmed"
                ? "Confirm your email before signing in. Check your inbox."
                : "Email or password is incorrect, or sign-in is temporarily unavailable.",
          },
          error.status === 429 ? 429 : 400,
        );
      return authJson({
        redirect: next === "/reset-password" ? "/research" : next,
      });
    }
    const callback = new URL("/auth/callback", appOrigin());
    callback.searchParams.set(
      "next",
      next === "/reset-password" ? "/research" : next,
    );
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: name },
        emailRedirectTo: callback.toString(),
      },
    });
    if (error)
      return authJson(
        {
          error:
            "Account creation couldn’t be completed. Check your details or try signing in instead.",
        },
        error.status === 429 ? 429 : 400,
      );
    if (data.session)
      return authJson({
        redirect: next === "/reset-password" ? "/research" : next,
      });
    return authJson({
      message:
        "Check your inbox to confirm your email, then sign in. If you already have an account, use the login page.",
    });
  } catch {
    return authJson(
      { error: "The account service is unavailable. Please try again." },
      503,
    );
  }
}
