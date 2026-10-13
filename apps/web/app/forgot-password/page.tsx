import { AuthPage } from "../components/auth-page";
import { authPageProps } from "../../lib/auth/page";
export default async function ForgotPasswordPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  return (
    <AuthPage mode="forgot" {...await authPageProps(searchParams, false)} />
  );
}
