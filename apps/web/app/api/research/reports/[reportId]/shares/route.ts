import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../../lib/research-proxy";

export const runtime = "nodejs";

type Context = { params: Promise<{ reportId: string }> };

export async function GET(request: NextRequest, { params }: Context) {
  const { reportId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(reportId))
    return Response.json({ error: "Invalid report id." }, { status: 400 });
  return forwardResearch(request, `/research/reports/${reportId}/shares`);
}

export async function POST(request: NextRequest, { params }: Context) {
  const { reportId } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(reportId))
    return Response.json({ error: "Invalid report id." }, { status: 400 });
  return forwardResearch(
    request,
    `/research/reports/${reportId}/shares`,
    "POST",
  );
}
