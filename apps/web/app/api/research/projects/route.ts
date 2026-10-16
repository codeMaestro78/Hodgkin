import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../lib/research-proxy";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  return forwardResearch(request, "/research/projects");
}
export async function POST(request: NextRequest) {
  return forwardResearch(request, "/research/projects", "POST");
}
