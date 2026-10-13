import { NextRequest, NextResponse } from "next/server";
import { appOrigin } from "./config";

export function sameOrigin(request: NextRequest) {
  return (
    request.headers.get("origin") === appOrigin() &&
    request.headers.get("sec-fetch-site") !== "cross-site"
  );
}
export function authJson(body: unknown, status = 200) {
  return NextResponse.json(body, {
    status,
    headers: { "cache-control": "private, no-store" },
  });
}
