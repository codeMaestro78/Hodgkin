import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const after = encodeURIComponent(
    request.nextUrl.searchParams.get("after") ?? "0",
  );
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}/events?after=${after}`,
    "GET",
    true,
  );
}
