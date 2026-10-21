import { NextRequest } from "next/server";
import { researchApiUrl } from "../../../lib/research-api-url";

export const runtime = "nodejs";

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization") ?? "";
  const match = /^ResearchShare ([A-Za-z0-9_-]{40,100})$/.exec(authorization);
  if (!match)
    return Response.json(
      { error: "Shared report not found." },
      { status: 404 },
    );
  const apiUrl = process.env.RESEARCH_API_URL;
  const serviceKey = process.env.INTERNAL_SERVICE_AUTH;
  if (!apiUrl || !serviceKey)
    return Response.json(
      { error: "Shared report service is unavailable." },
      { status: 503 },
    );
  try {
    const upstream = await fetch(researchApiUrl(apiUrl, "/s").toString(), {
      headers: {
        authorization: `ResearchShare ${match[1]}`,
        "x-internal-service-auth": serviceKey,
        accept: "application/json",
        "x-request-id": crypto.randomUUID(),
      },
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
        "cache-control": "private, no-store",
        "referrer-policy": "no-referrer",
        "x-robots-tag": "noindex, nofollow, noarchive",
      },
    });
  } catch {
    return Response.json(
      { error: "Shared report service is unavailable." },
      { status: 503 },
    );
  }
}
