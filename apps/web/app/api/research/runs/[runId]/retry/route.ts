import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}/retry`,
    "POST",
  );
}
