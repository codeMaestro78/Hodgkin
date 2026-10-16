import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function POST(
  request: NextRequest,
  context: { params: Promise<{ itemId: string }> },
) {
  const { itemId } = await context.params;
  return forwardResearch(
    request,
    `/research/library/items/${encodeURIComponent(itemId)}/remove`,
    "POST",
  );
}
