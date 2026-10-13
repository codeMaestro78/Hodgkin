import { NextRequest, NextResponse } from "next/server";
import { FollowupRequestSchema } from "@research/contracts";
import { forwardResearch } from "../../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ runId: string }> },
) {
  const parsed = FollowupRequestSchema.safeParse(
    await request
      .clone()
      .json()
      .catch(() => null),
  );
  if (!parsed.success)
    return NextResponse.json(
      { detail: "A question and request key are required." },
      { status: 422 },
    );
  const { runId } = await context.params;
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}/followups`,
    "POST",
  );
}
