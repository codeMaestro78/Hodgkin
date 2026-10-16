import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  const params = new URLSearchParams();
  for (const key of ["query", "projectId", "kind", "tag", "after", "limit"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value !== null) params.set(key, value);
  }
  const query = params.toString();
  return forwardResearch(
    request,
    `/research/library/items${query ? `?${query}` : ""}`,
  );
}
export async function POST(request: NextRequest) {
  return forwardResearch(request, "/research/library/items", "POST");
}
