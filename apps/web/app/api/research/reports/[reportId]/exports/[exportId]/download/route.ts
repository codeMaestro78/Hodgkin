import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../../../lib/research-proxy";

export const runtime = "nodejs";

type Context = { params: Promise<{ reportId: string; exportId: string }> };

export async function GET(request: NextRequest, { params }: Context) {
  const { reportId, exportId } = await params;
  if (![reportId, exportId].every((id) => /^[0-9a-f-]{36}$/i.test(id)))
    return Response.json(
      { error: "Invalid export reference." },
      { status: 400 },
    );
  return forwardResearch(
    request,
    `/research/reports/${reportId}/exports/${exportId}/download`,
    "GET",
    false,
    true,
  );
}
