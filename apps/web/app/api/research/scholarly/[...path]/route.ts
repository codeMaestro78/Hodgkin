import { NextRequest } from "next/server";
import { forwardResearch } from "../../../../../lib/research-proxy";

export const runtime = "nodejs";

type Context = { params: Promise<{ path: string[] }> };
const id = /^[0-9a-f-]{36}$/i;

function upstreamPath(parts: string[], method: "GET" | "POST") {
  if (parts.length === 1 && parts[0] === "reviews") return "/research/reviews";
  if (parts.length < 2 || parts[0] !== "reviews" || !parts[1] || !id.test(parts[1])) return null;
  const base = `/research/reviews/${parts[1]}`;
  if (parts.length === 2 && method === "GET") return base;
  if (parts.length === 3 && parts[2] && ["prisma", "evidence", "records", "decisions", "retrievals", "artifacts"].includes(parts[2]) && method === "GET")
    return `${base}/${parts[2]}`;
  if (method === "GET" && parts.length === 6 && parts[2] === "artifacts" && id.test(parts[3] ?? "") &&
      parts[4] === "pages" && /^(?:[1-9]|[1-9][0-9]|100)$/.test(parts[5] ?? ""))
    return `${base}/artifacts/${parts[3]}/pages/${parts[5]}`;
  if (parts.length === 3 && parts[2] && ["searches", "records"].includes(parts[2]) && method === "POST")
    return `${base}/${parts[2]}`;
  if (parts.length === 5 && parts[2] === "records" && parts[3] && parts[3].length <= 200 && parts[4] &&
      ["decisions", "retrievals", "duplicate", "artifacts", "evidence"].includes(parts[4]) && method === "POST")
    return `${base}/records/${encodeURIComponent(parts[3])}/${parts[4]}`;
  if (parts.length === 4 && parts[2] === "imports" && parts[3] === "doi" && method === "POST")
    return `${base}/imports/doi`;
  return null;
}

async function handle(request: NextRequest, context: Context, method: "GET" | "POST") {
  const { path } = await context.params;
  const target = upstreamPath(path, method);
  if (!target) return Response.json({ error: "Unknown scholarly route." }, { status: 404 });
  return forwardResearch(request, target, method);
}

export async function GET(request: NextRequest, context: Context) {
  return handle(request, context, "GET");
}

export async function POST(request: NextRequest, context: Context) {
  return handle(request, context, "POST");
}
