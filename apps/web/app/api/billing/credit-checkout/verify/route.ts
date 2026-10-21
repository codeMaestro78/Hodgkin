import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../lib/research-proxy";

export const runtime = "nodejs";

export function POST(request: NextRequest) {
  return forwardResearch(request, "/billing/credit-checkout/verify", "POST");
}
