import { NextRequest } from "next/server";
import { createAuthClient } from "./auth/server";
import { authConfigured } from "./auth/config";
import { authJson, sameOrigin } from "./auth/http";
import { researchApiUrl } from "./research-api-url";

/** Every BFF route verifies the session; never forwards caller identity headers. */
export async function forwardResearch(
  request: NextRequest,
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
  events = false,
  binary = false,
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
  if (method !== "GET" && !sameOrigin(request))
    return authJson({ error: "Cross-site requests are not allowed." }, 403);
  if (!authConfigured())
    return authJson({ error: "Supabase Auth is not configured." }, 503);
  try {
    let requestBody: string | null = null;
    if (method === "POST" || method === "PATCH") {
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
    // This is only a consistency hint, never an identity/authorization source.
    // Check against the identity already verified for this exact request, avoiding
    // both an extra client preflight round trip and a cross-tab account-change race.
    const expectedAccount = request.headers.get("x-research-account-id");
    if (
      method === "POST" &&
      expectedAccount &&
      expectedAccount !== identity.user.id
    )
      return authJson(
        {
          error:
            "Your account changed. Review the current account's draft before starting research.",
        },
        409,
      );
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session || session.user.id !== identity.user.id)
      return authJson({ error: "Your session has expired." }, 401);
    timing("auth", authStarted);
    const authDuration = performance.now() - authStarted;
    const apiUrl = process.env.RESEARCH_API_URL;
    const serviceKey = process.env.INTERNAL_SERVICE_AUTH;
    if (!apiUrl || !serviceKey)
      return authJson({ error: "Research service is not configured." }, 503);
    const headers = new Headers({
      authorization: `Bearer ${session.access_token}`,
      "x-internal-service-auth": serviceKey,
      "x-verified-account-id": identity.user.id,
      accept: events ? "text/event-stream" : "application/json",
      "x-request-id": requestId,
    });
    if (method === "POST" || method === "PATCH") {
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
    const response = await fetch(researchApiUrl(apiUrl, path).toString(), {
      method,
      headers,
      body: requestBody,
      cache: "no-store",
      signal: request.signal,
    });
    timing("upstream.headers", upstreamStarted, response.status);
    const upstreamDuration = performance.now() - upstreamStarted;
    // Numeric only; SSE measurements end at response headers, not stream closure.
    const serverTiming = () =>
      `auth;dur=${authDuration.toFixed(1)}, upstream_headers;dur=${upstreamDuration.toFixed(1)}, proxy;dur=${(performance.now() - started).toFixed(1)}`;
    if (response.status === 204)
      return new Response(null, {
        status: 204,
        headers: {
          "cache-control": "private, no-store",
          "x-request-id": requestId,
          "server-timing": serverTiming(),
        },
      });
    if (events && response.ok && response.body)
      return new Response(response.body, {
        headers: {
          "cache-control": "private, no-cache, no-transform",
          "content-type": "text/event-stream",
          "x-accel-buffering": "no",
          "x-request-id": requestId,
          "server-timing": serverTiming(),
        },
      });
    if (binary) {
      return new Response(response.body, {
        status: response.status,
        headers: {
          "content-type":
            response.headers.get("content-type") ?? "application/octet-stream",
          "content-disposition":
            response.headers.get("content-disposition") ?? "attachment",
          "cache-control": "private, no-store",
          "x-content-type-options": "nosniff",
          "x-request-id": requestId,
          "server-timing": serverTiming(),
        },
      });
    }
    const body = await response.text();
    let responseBody = body;
    try {
      JSON.parse(body);
    } catch {
      responseBody = JSON.stringify({
        error:
          response.status >= 500
            ? "Research service encountered an internal error. Please try again."
            : "Research service returned an invalid response. Please try again.",
      });
    }
    timing("response", started, response.status);
    const forwardedHeaders = new Headers({
      "content-type": "application/json",
      "cache-control": "private, no-store",
      "x-request-id": requestId,
      "server-timing": serverTiming(),
    });
    for (const name of [
      "retry-after",
      "ratelimit-limit",
      "ratelimit-remaining",
      "ratelimit-reset",
    ]) {
      const value = response.headers.get(name);
      if (value !== null) forwardedHeaders.set(name, value);
    }
    return new Response(responseBody, {
      status: response.status,
      headers: forwardedHeaders,
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
