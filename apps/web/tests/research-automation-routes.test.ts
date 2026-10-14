import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const proxy = vi.hoisted(() => vi.fn());
vi.mock("../lib/research-proxy", () => ({ forwardResearch: proxy }));
import {
  GET as getBatches,
  POST as createBatch,
} from "../app/api/research/batches/route";
import {
  GET as getSchedules,
  POST as createSchedule,
} from "../app/api/research/schedules/route";
import { POST as disableSchedule } from "../app/api/research/schedules/[scheduleId]/disable/route";
import { POST as approve } from "../app/api/research/runs/[runId]/approve/route";
import { POST as retry } from "../app/api/research/runs/[runId]/retry/route";

beforeEach(() => {
  proxy.mockReset();
  proxy.mockImplementation(
    async (request: NextRequest, path: string, method = "GET") =>
      new Response(
        JSON.stringify({
          path,
          method,
          body: method === "POST" ? await request.text() : null,
        }),
        { status: 202 },
      ),
  );
});

it("forwards an explicitly chosen retry deadline and drops unrelated query parameters", async () => {
  const request = new NextRequest(
    "http://localhost/api/research/runs/id/retry?maxWallClockMs=600000&tenantId=forged",
    { method: "POST" },
  );
  await retry(request, { params: Promise.resolve({ runId: "id" }) });
  expect(proxy).toHaveBeenCalledWith(
    request,
    "/research/runs/id/retry?maxWallClockMs=600000",
    "POST",
  );
});

it.each([
  [getBatches, "/research/batches"],
  [getSchedules, "/research/schedules"],
] as const)(
  "forwards a list request without changing the backend response",
  async (handler, path) => {
    const request = new NextRequest(`http://localhost/api${path}`);
    const response = await handler(request);
    expect(proxy).toHaveBeenCalledWith(request, path);
    expect(response.status).toBe(202);
  },
);

it.each([
  [
    createBatch,
    "/research/batches",
    {
      questions: ["Compare queues"],
      idempotencyKey: "11111111-1111-4111-8111-111111111111",
      requireApproval: true,
      budgetOverrides: { maxSearchCalls: 6 },
    },
  ],
  [
    createSchedule,
    "/research/schedules",
    {
      question: "Compare queues",
      intervalMinutes: 60,
      idempotencyKey: "11111111-1111-4111-8111-111111111111",
      requireApproval: false,
    },
  ],
] as const)(
  "forwards creation with POST and the original JSON body",
  async (handler, path, body) => {
    const request = new NextRequest(`http://localhost/api${path}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    const response = await handler(request);
    expect(proxy).toHaveBeenCalledWith(request, path, "POST");
    expect((await response.json()).body).toBe(JSON.stringify(body));
  },
);

it.each(["approve", "reject"] as const)(
  "forwards %s decisions including the plan reference",
  async (decision) => {
    const body = { planId: "11111111-1111-4111-8111-111111111111", decision };
    const request = new NextRequest(
      "http://localhost/api/research/runs/id/approve",
      { method: "POST", body: JSON.stringify(body) },
    );
    const response = await approve(request, {
      params: Promise.resolve({ runId: "run/id" }),
    });
    expect(proxy).toHaveBeenCalledWith(
      request,
      "/research/runs/run%2Fid/approve",
      "POST",
    );
    expect((await response.json()).body).toBe(JSON.stringify(body));
  },
);

it("forwards disable with its empty JSON body and encoded schedule ID", async () => {
  const request = new NextRequest(
    "http://localhost/api/research/schedules/id/disable",
    { method: "POST", body: "{}" },
  );
  const response = await disableSchedule(request, {
    params: Promise.resolve({ scheduleId: "schedule/id" }),
  });
  expect(proxy).toHaveBeenCalledWith(
    request,
    "/research/schedules/schedule%2Fid/disable",
    "POST",
  );
  expect((await response.json()).body).toBe("{}");
});
