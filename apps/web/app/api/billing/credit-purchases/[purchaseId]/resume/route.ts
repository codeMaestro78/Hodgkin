import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";

export const runtime = "nodejs";

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ purchaseId: string }> },
) {
  const { purchaseId } = await context.params;
  if (!/^[0-9a-f-]{36}$/i.test(purchaseId)) {
    return Response.json({ detail: "Credit purchase not found" }, { status: 404 });
  }
  return forwardResearch(
    request,
    `/billing/credit-purchases/${purchaseId}/resume`,
    "POST",
  );
}
