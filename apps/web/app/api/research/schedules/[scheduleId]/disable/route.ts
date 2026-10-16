import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";

export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ scheduleId: string }> },
) {
  const { scheduleId } = await context.params;
  return forwardResearch(
    request,
    `/research/schedules/${encodeURIComponent(scheduleId)}/disable`,
    "POST",
  );
}
