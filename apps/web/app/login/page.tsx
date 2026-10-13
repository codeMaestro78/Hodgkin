import type { Metadata } from "next";
import { AuthPage } from "../components/auth-page";
import { authPageProps } from "../../lib/auth/page";
export const metadata: Metadata = { title: "Log in · HogsKin" };
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return <AuthPage mode="login" {...await authPageProps(searchParams)} />;
}
