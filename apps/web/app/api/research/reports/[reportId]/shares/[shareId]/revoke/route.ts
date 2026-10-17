import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../../../lib/research-proxy";

export const runtime = "nodejs";

type Context = { params: Promise<{ reportId: string; shareId: string }> };

export async function POST(request: NextRequest, { params }: Context) {
  const { reportId, shareId } = await params;
  if (![reportId, shareId].every((id) => /^[0-9a-f-]{36}$/i.test(id)))
    return Response.json(
      { error: "Invalid share reference." },
      { status: 400 },
    );
  return forwardResearch(
    request,
    `/research/reports/${reportId}/shares/${shareId}/revoke`,
    "POST",
  );
}
