import type { Metadata } from "next";
import { AuthPage } from "../components/auth-page";
import { authPageProps } from "../../lib/auth/page";
export const metadata: Metadata = { title: "Create account · HogsKin" };
export default async function SignupPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <AuthPage mode="signup" {...await authPageProps(searchParams)} />;
}
