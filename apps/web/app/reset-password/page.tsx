import { redirect } from "next/navigation";
import { AuthPage } from "../components/auth-page";
import { createAuthClient } from "../../lib/auth/server";
import { authConfigured } from "../../lib/auth/config";
export default async function ResetPasswordPage() {
  if (!authConfigured()) redirect("/login?error=configuration");
  const supabase = await createAuthClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) redirect("/forgot-password");
  return <AuthPage mode="reset" configured />;
}
