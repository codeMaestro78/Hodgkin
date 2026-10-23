import { NextRequest } from "next/server";
import { createAuthClient } from "../../../../../../../../lib/auth/server";
import { authConfigured } from "../../../../../../../../lib/auth/config";
import { authJson, sameOrigin } from "../../../../../../../../lib/auth/http";
import { researchApiUrl } from "../../../../../../../../lib/research-api-url";

export const runtime = "nodejs";
// Keep below Vercel's 4.5 MB Function request-body ceiling.
const MAX_PDF_BYTES = 4 * 1024 * 1024;
const REVIEW_ID = /^[0-9a-f-]{36}$/i;
type Context = { params: Promise<{ reviewId: string }> };

export async function POST(request: NextRequest, { params }: Context) {
  const { reviewId } = await params;
  if (!REVIEW_ID.test(reviewId)) return authJson({ error: "Invalid review id." }, 400);
  if (!sameOrigin(request)) return authJson({ error: "Cross-site requests are not allowed." }, 403);
  if (!authConfigured()) return authJson({ error: "Supabase Auth is not configured." }, 503);
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/pdf"))
    return authJson({ error: "Select a PDF file." }, 415);
  const title = request.nextUrl.searchParams.get("title")?.trim();
  if (!title || title.length > 500) return authJson({ error: "Enter a PDF title (up to 500 characters)." }, 400);
  const length = Number(request.headers.get("content-length"));
  if (Number.isFinite(length) && length > MAX_PDF_BYTES)
    return authJson({ error: "PDF must be 4 MiB or smaller." }, 413);

  try {
    const supabase = await createAuthClient();
    const { data: identity, error } = await supabase.auth.getUser();
    if (error || !identity.user || identity.user.is_anonymous)
      return authJson({ error: "Sign in to access your research." }, 401);
    if (!identity.user.email_confirmed_at)
      return authJson({ error: "Confirm your email before researching." }, 403);
    const { data: { session } } = await supabase.auth.getSession();
    if (!session || session.user.id !== identity.user.id)
      return authJson({ error: "Your session has expired." }, 401);

    const apiUrl = process.env.RESEARCH_API_URL;
    const serviceKey = process.env.INTERNAL_SERVICE_AUTH;
    if (!apiUrl || !serviceKey)
      return authJson({ error: "Research service is not configured." }, 503);

    const reader = request.body?.getReader();
    if (!reader) return authJson({ error: "Choose a PDF file." }, 400);
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_PDF_BYTES) {
          await reader.cancel();
          return authJson({ error: "PDF must be 4 MiB or smaller." }, 413);
        }
        chunks.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    if (size < 5) return authJson({ error: "PDF is empty or invalid." }, 400);
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    if (new TextDecoder().decode(bytes.subarray(0, 5)) !== "%PDF-")
      return authJson({ error: "File does not appear to be a PDF." }, 415);

    const target = researchApiUrl(apiUrl, `/research/reviews/${reviewId}/imports/pdf`);
    target.searchParams.set("title", title);
    const response = await fetch(target, {
      method: "POST",
      headers: {
        authorization: `Bearer ${session.access_token}`,
        "x-internal-service-auth": serviceKey,
        "x-verified-account-id": identity.user.id,
        accept: "application/json",
        "content-type": "application/pdf",
      },
      body: bytes,
      cache: "no-store",
      signal: request.signal,
    });
    // Keep the response bounded too; never reflect an arbitrary upstream document.
    const responseLength = Number(response.headers.get("content-length"));
    if (Number.isFinite(responseLength) && responseLength > 256 * 1024)
      return authJson({ error: "Research service returned an oversized response." }, 502);
    const responseReader = response.body?.getReader();
    if (!responseReader) return authJson({ error: "Research service returned an invalid response." }, 502);
    const responseChunks: Uint8Array[] = [];
    let responseSize = 0;
    try {
      while (true) {
        const { value, done } = await responseReader.read();
        if (done) break;
        responseSize += value.byteLength;
        if (responseSize > 256 * 1024) {
          await responseReader.cancel();
          return authJson({ error: "Research service returned an oversized response." }, 502);
        }
        responseChunks.push(value);
      }
    } finally {
      responseReader.releaseLock();
    }
    const responseBytes = new Uint8Array(responseSize);
    let responseOffset = 0;
    for (const chunk of responseChunks) { responseBytes.set(chunk, responseOffset); responseOffset += chunk.byteLength; }
    const body = new TextDecoder().decode(responseBytes);
    try { JSON.parse(body); } catch { return authJson({ error: "Research service returned an invalid response." }, 502); }
    return new Response(body, {
      status: response.status,
      headers: { "content-type": "application/json", "cache-control": "private, no-store" },
    });
  } catch {
    return authJson({ error: "Research service is unavailable. Please try again." }, 503);
  }
}
