export function authConfig() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  if (!url || !key)
    throw new Error(
      "Supabase Auth is not configured. Set the project URL and publishable key.",
    );
  return { url, key };
}

export function authConfigured() {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );
}

export function appOrigin() {
  const url = new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000",
  );
  if (!["http:", "https:"].includes(url.protocol))
    throw new Error("Invalid application URL.");
  return url.origin;
}

/** Auth destinations are an allowlist, not a client-controlled open redirect. */
export function authDestination(value: string | null | undefined) {
  if (value === "/reset-password") return value;
  if (value === "/research" || /^\/research\/[a-f0-9-]{36}$/i.test(value ?? ""))
    return value!;
  return "/research";
}
