import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../lib/research-proxy";

export const runtime = "nodejs";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ sessionId: string }> },
) {
  const { sessionId } = await context.params;
  if (!/^order_[A-Za-z0-9_]+$/.test(sessionId))
    return Response.json({ detail: "Credit purchase not found" }, { status: 404 });
  return forwardResearch(request, `/billing/credit-purchases/${sessionId}`);
}
