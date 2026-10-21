import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const version = request.nextUrl.searchParams.get("reportVersion");
  const query =
    version && /^[1-9]\d{0,3}$/.test(version)
      ? `?reportVersion=${version}`
      : "";
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}${query}`,
    "GET",
  );
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return forwardResearch(
    request,
    `/research/runs/${encodeURIComponent(runId)}`,
    "DELETE",
  );
}
