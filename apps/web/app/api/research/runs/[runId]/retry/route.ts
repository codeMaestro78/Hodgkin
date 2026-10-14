import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const limit = request.nextUrl.searchParams.get("maxWallClockMs");
  const query = limit ? `?maxWallClockMs=${encodeURIComponent(limit)}` : "";
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}/retry${query}`,
    "POST",
  );
}
