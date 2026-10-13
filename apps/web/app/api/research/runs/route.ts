import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  const reportsOnly =
    request.nextUrl.searchParams.get("reportsOnly") === "true";
  return forwardResearch(
    request,
    reportsOnly ? "/research/runs?reportsOnly=true" : "/research/runs",
  );
}
export async function POST(request: NextRequest) {
  return forwardResearch(request, "/research/runs", "POST");
}
