import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { authConfig } from "./config";

export async function createAuthClient() {
  const { url, key } = authConfig();
  const store = await cookies();
  return createServerClient(url, key, {
    // Auth is server-only; no browser SDK needs to read the session cookies.
    cookieOptions: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
    },
    cookies: {
      getAll: () => store.getAll(),
      setAll: (values) => {
        try {
          values.forEach(({ name, value, options }) =>
            store.set(name, value, options),
          );
        } catch {
          /* Server Components are read-only; proxy refreshes their cookies. */
        }
      },
    },
  });
}
