import { createAuthClient } from "../../../../lib/auth/server";
import { authConfigured } from "../../../../lib/auth/config";
import { authJson } from "../../../../lib/auth/http";
export async function GET() {
  if (!authConfigured())
    return authJson({ error: "Account service is not configured." }, 503);
  try {
    const supabase = await createAuthClient();
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user || data.user.is_anonymous)
      return authJson({ error: "Sign in to continue." }, 401);
    return authJson({
      user: {
        id: data.user.id,
        email: data.user.email,
        name:
          typeof data.user.user_metadata.full_name === "string"
            ? data.user.user_metadata.full_name.slice(0, 120)
            : "Research account",
      },
    });
  } catch {
    return authJson({ error: "Account service is unavailable." }, 503);
  }
}
