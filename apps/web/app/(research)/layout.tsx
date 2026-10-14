import type { ReactNode } from "react";
import { redirect } from "next/navigation";
import { authConfigured } from "../../lib/auth/config";
import { createAuthClient } from "../../lib/auth/server";
import { needsOnboarding } from "../../lib/onboarding";

export default async function ResearchLayout({
  children,
}: {
  children: ReactNode;
}) {
  if (!authConfigured()) redirect("/login?error=configuration");
  const supabase = await createAuthClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user || data.user.is_anonymous) redirect("/login");
  if (needsOnboarding(data.user.user_metadata)) redirect("/onboarding");
  return children;
}
