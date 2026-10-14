import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";

export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ runId: string }> },
) {
  const { runId } = await context.params;
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}/approve`,
    "POST",
  );
}
