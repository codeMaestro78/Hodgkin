import { redirect } from "next/navigation";
import { createAuthClient } from "../../lib/auth/server";
import { authConfigured, authDestination } from "../../lib/auth/config";
import { readOnboarding } from "../../lib/onboarding";
import { OnboardingFlow } from "../components/onboarding-flow";

export default async function OnboardingPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!authConfigured()) redirect("/login?error=configuration");
  const supabase = await createAuthClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user || data.user.is_anonymous) redirect("/login");
  if (!data.user.email_confirmed_at) redirect("/login?error=confirmation");
  const params = await searchParams;
  const next = authDestination(
    typeof params.next === "string" ? params.next : undefined,
  );
  return (
    <OnboardingFlow
      initialProfile={readOnboarding(data.user.user_metadata)}
      next={next}
    />
  );
}
