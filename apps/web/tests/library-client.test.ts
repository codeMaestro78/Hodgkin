import { afterEach, expect, it, vi } from "vitest";
import {
  libraryError,
  libraryQuery,
  libraryRequest,
  LibraryItemSchema,
  LibraryListSchema,
  mergeLibraryItems,
  parseLibraryTags,
  ProjectListSchema,
  ProjectSchema,
  type LibraryItem,
} from "../lib/library-client";

const id = "11111111-1111-4111-8111-111111111111";
const item: LibraryItem = {
  id,
  kind: "report",
  title: "Saved report",
  runId: id,
  reportId: id,
  reportVersion: 2,
  sourceId: null,
  url: null,
  projectId: null,
  tags: [],
  notes: "",
  createdAt: "2026-10-16T10:00:00Z",
};
afterEach(() => vi.unstubAllGlobals());

it("validates nullable fields and requires an explicit terminal cursor", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(Response.json({ items: [item], nextCursor: null })),
  );
  expect(await libraryRequest("/library/items", LibraryListSchema)).toEqual({
    items: [item],
    nextCursor: null,
  });
  expect(LibraryListSchema.safeParse({ items: [item] }).success).toBe(false);
  expect(LibraryItemSchema.safeParse({ ...item, id: "bad" }).success).toBe(
    false,
  );
});

it("validates projects and sends JSON to the same-origin endpoint without caching", async () => {
  const project = { id, name: "Evidence", createdAt: item.createdAt };
  const fetcher = vi.fn().mockResolvedValue(Response.json(project));
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  expect(
    await libraryRequest("/projects", ProjectSchema, {
      method: "POST",
      body: '{"name":"Evidence"}',
      signal: controller.signal,
    }),
  ).toEqual(project);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/research/projects",
    expect.objectContaining({
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
      body: '{"name":"Evidence"}',
    }),
  );
  expect(ProjectListSchema.safeParse({ projects: [project] }).success).toBe(
    true,
  );
});

it("encodes filters and cursor and omits blank values", () => {
  const result = libraryQuery(
    { query: " grids & queues ", projectId: id, kind: "source", tag: "a/b" },
    id,
  );
  const url = new URL(result, "http://localhost");
  expect(Object.fromEntries(url.searchParams)).toEqual({
    query: "grids & queues",
    projectId: id,
    kind: "source",
    tag: "a/b",
    after: id,
    limit: "50",
  });
  expect(libraryQuery({ query: " ", projectId: "", kind: "", tag: "" })).toBe(
    "/library/items?limit=50",
  );
});

it("merges pages by stable ID without duplicating rows", () => {
  const second = { ...item, id: "22222222-2222-4222-8222-222222222222" };
  expect(
    mergeLibraryItems([item], [{ ...item, notes: "Updated" }, second]),
  ).toEqual([{ ...item, notes: "Updated" }, second]);
});

it("normalizes comma-separated tags without dropping non-Latin text", () => {
  expect(parseLibraryTags(" queues, , queues, स्रोत , C++ ")).toEqual([
    "queues",
    "स्रोत",
    "C++",
  ]);
});

it.each([401, 403, 404, 422, 500])(
  "shows a clean error for HTTP %s without exposing backend detail",
  async (status) => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json({ detail: "secret internal traceback" }, { status }),
        ),
    );
    const error = await libraryRequest("/projects", ProjectListSchema).catch(
      (cause: unknown) => cause,
    );
    expect(libraryError(error)).not.toContain("secret");
    expect(libraryError(error)).not.toContain("traceback");
    expect(libraryError(error).length).toBeGreaterThan(20);
  },
);

it("rejects malformed successful JSON with an actionable error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(new Response("<html>private</html>")),
  );
  const error = await libraryRequest("/projects", ProjectListSchema).catch(
    (cause: unknown) => cause,
  );
  expect(libraryError(error)).toContain("unexpected response");
});

it("keeps aborts distinguishable from network failures", async () => {
  const controller = new AbortController();
  controller.abort();
  const abort = new DOMException("Aborted", "AbortError");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
  await expect(
    libraryRequest("/projects", ProjectListSchema, {
      signal: controller.signal,
    }),
  ).rejects.toBe(abort);
  const error = await libraryRequest("/projects", ProjectListSchema).catch(
    (cause: unknown) => cause,
  );
  expect(libraryError(error)).toContain("Check your connection");
  expect(libraryError(new Error("private stack"))).not.toContain("private");
});
