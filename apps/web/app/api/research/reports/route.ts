import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../lib/research-proxy";

export const runtime = "nodejs";
export function GET(request: NextRequest) {
  const params = new URLSearchParams();
  for (const key of ["after", "limit"]) {
    const value = request.nextUrl.searchParams.get(key);
    if (value !== null) params.set(key, value);
  }
  const query = params.toString();
  return forwardResearch(
    request,
    `/research/reports${query ? `?${query}` : ""}`,
  );
}
