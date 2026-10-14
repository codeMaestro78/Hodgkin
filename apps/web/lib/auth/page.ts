import { redirect } from "next/navigation";
import { authConfigured, authDestination } from "./config";
import { createAuthClient } from "./server";
import { onboardingDestination } from "../onboarding";

const messages: Record<string, string> = {
  configuration:
    "Supabase Auth needs its project URL and publishable key before you can sign in.",
  unavailable:
    "The account service is temporarily unavailable. Please try again.",
  callback:
    "Sign-in could not be completed. The link may have expired, or Google sign-in was cancelled. Please try again.",
  confirmation:
    "This confirmation link is invalid or has expired. Try signing in or request a new password-reset link.",
  "password-updated":
    "Your password has been updated. Sign in with your new password.",
};
export async function authPageProps(
  searchParams: Promise<Record<string, string | string[] | undefined>>,
  redirectSignedIn = true,
) {
  const params = await searchParams;
  const configured = authConfigured();
  const next = authDestination(
    typeof params.next === "string" ? params.next : undefined,
  );
  if (configured && redirectSignedIn) {
    const supabase = await createAuthClient();
    const { data } = await supabase.auth.getUser();
    if (data.user && !data.user.is_anonymous)
      redirect(
        onboardingDestination(
          next === "/reset-password" ? "/research" : next,
          data.user.user_metadata,
        ),
      );
  }
  const code =
    typeof params.error === "string"
      ? params.error
      : typeof params.message === "string"
        ? params.message
        : "";
  return { configured, next, initialNotice: messages[code] ?? "" };
}
