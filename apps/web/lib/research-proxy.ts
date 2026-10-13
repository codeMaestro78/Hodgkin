import { NextRequest } from "next/server";
import { createAuthClient } from "./auth/server";
import { authConfigured } from "./auth/config";
import { authJson, sameOrigin } from "./auth/http";

/** Every BFF route verifies the session; never forwards caller identity headers. */
export async function forwardResearch(
  request: NextRequest,
  path: string,
  method: "GET" | "POST" = "GET",
  events = false,
) {
  if (method === "POST" && !sameOrigin(request))
    return authJson({ error: "Cross-site requests are not allowed." }, 403);
  if (!authConfigured())
    return authJson({ error: "Supabase Auth is not configured." }, 503);
  try {
    const supabase = await createAuthClient();
    const { data: identity, error } = await supabase.auth.getUser();
    if (error || !identity.user || identity.user.is_anonymous)
      return authJson({ error: "Sign in to access your research." }, 401);
    if (!identity.user.email_confirmed_at)
      return authJson({ error: "Confirm your email before researching." }, 403);
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session || session.user.id !== identity.user.id)
      return authJson({ error: "Your session has expired." }, 401);
    const apiUrl = process.env.RESEARCH_API_URL;
    const serviceKey = process.env.INTERNAL_SERVICE_AUTH;
    if (!apiUrl || !serviceKey)
      return authJson({ error: "Research service is not configured." }, 503);
    const headers = new Headers({
      authorization: `Bearer ${session.access_token}`,
      "x-internal-service-auth": serviceKey,
      accept: events ? "text/event-stream" : "application/json",
    });
    if (method === "POST") {
      headers.set("content-type", "application/json");
      const idempotency = request.headers.get("idempotency-key");
      if (idempotency) headers.set("idempotency-key", idempotency);
    }
    const response = await fetch(`${apiUrl}${path}`, {
      method,
      headers,
      body:
        method === "POST" &&
        (path === "/research/runs" ||
          /^\/research\/runs\/[^/]+\/followups$/.test(path))
          ? await request.text()
          : null,
      cache: "no-store",
      signal: request.signal,
    });
    if (events && response.ok && response.body)
      return new Response(response.body, {
        headers: {
          "cache-control": "private, no-cache, no-transform",
          "content-type": "text/event-stream",
          "x-accel-buffering": "no",
        },
      });
    return new Response(await response.text(), {
      status: response.status,
      headers: {
        "content-type": "application/json",
        "cache-control": "private, no-store",
      },
    });
  } catch {
    return authJson(
      { error: "Research service is unavailable. Please try again." },
      503,
    );
  }
}
