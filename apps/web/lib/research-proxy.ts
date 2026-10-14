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
  const requestId = crypto.randomUUID();
  const started = performance.now();
  let phase = "guard";
  const timing = (operation: string, phaseStarted: number, status?: number) => {
    const failed = operation.endsWith(".failed") || (status ?? 200) >= 400;
    // One completion record, not three phase records, unless diagnostics are requested.
    if (
      !failed &&
      operation !== "response" &&
      process.env.RESEARCH_LOG_LEVEL !== "DEBUG"
    )
      return;
    const log = failed ? console.error : console.info;
    log(
      JSON.stringify({
        event: "research.proxy",
        requestId,
        operation,
        method,
        stream: events,
        status,
        durationMs: Math.round(performance.now() - phaseStarted),
      }),
    );
  };
  if (method === "POST" && !sameOrigin(request))
    return authJson({ error: "Cross-site requests are not allowed." }, 403);
  if (!authConfigured())
    return authJson({ error: "Supabase Auth is not configured." }, 503);
  try {
    let requestBody: string | null = null;
    if (method === "POST") {
      const reader = request.body?.getReader();
      let bytes = 0;
      const chunks: Uint8Array[] = [];
      if (reader) {
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            bytes += value.byteLength;
            if (bytes > 256 * 1024) {
              await reader.cancel();
              return authJson({ error: "Research request is too large." }, 413);
            }
            chunks.push(value);
          }
        } finally {
          reader.releaseLock();
        }
      }
      if (bytes) {
        const joined = new Uint8Array(bytes);
        let offset = 0;
        for (const chunk of chunks) {
          joined.set(chunk, offset);
          offset += chunk.length;
        }
        requestBody = new TextDecoder().decode(joined);
      }
    }
    phase = "auth";
    const authStarted = performance.now();
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
    timing("auth", authStarted);
    const apiUrl = process.env.RESEARCH_API_URL;
    const serviceKey = process.env.INTERNAL_SERVICE_AUTH;
    if (!apiUrl || !serviceKey)
      return authJson({ error: "Research service is not configured." }, 503);
    const headers = new Headers({
      authorization: `Bearer ${session.access_token}`,
      "x-internal-service-auth": serviceKey,
      accept: events ? "text/event-stream" : "application/json",
      "x-request-id": requestId,
    });
    if (method === "POST") {
      headers.set("content-type", "application/json");
      const idempotency = request.headers.get("idempotency-key");
      if (idempotency) headers.set("idempotency-key", idempotency);
    }
    if (events) {
      const cursor = request.headers.get("last-event-id");
      if (cursor) headers.set("last-event-id", cursor);
    }
    phase = "upstream";
    const upstreamStarted = performance.now();
    const response = await fetch(`${apiUrl}${path}`, {
      method,
      headers,
      body: requestBody,
      cache: "no-store",
      signal: request.signal,
    });
    timing("upstream.headers", upstreamStarted, response.status);
    if (events && response.ok && response.body)
      return new Response(response.body, {
        headers: {
          "cache-control": "private, no-cache, no-transform",
          "content-type": "text/event-stream",
          "x-accel-buffering": "no",
          "x-request-id": requestId,
        },
      });
    const body = await response.text();
    timing("response", started, response.status);
    return new Response(body, {
      status: response.status,
      headers: {
        "content-type": "application/json",
        "cache-control": "private, no-store",
        "x-request-id": requestId,
      },
    });
  } catch {
    if (request.signal.aborted) {
      // Navigation/closed tabs are not provider failures. No body or exception is logged.
      return new Response(null, {
        status: 499,
        headers: { "x-request-id": requestId },
      });
    }
    timing(`${phase}.failed`, started, 503);
    return authJson(
      { error: "Research service is unavailable. Please try again." },
      503,
    );
  }
}
