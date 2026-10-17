import type { z } from "zod";
import type { LibraryItem } from "@research/contracts";
export {
  ProjectSchema,
  ProjectsResponseSchema as ProjectListSchema,
  LibraryItemSchema,
  LibraryItemsResponseSchema as LibraryListSchema,
  RemoveLibraryItemResponseSchema as RemovedItemSchema,
  CreateProjectRequestSchema,
  OrganizeLibraryItemRequestSchema,
} from "@research/contracts";
export type { Project, LibraryItem } from "@research/contracts";
export type LibraryFilters = {
  query: string;
  projectId: string;
  kind: string;
  tag: string;
};

class LibraryError extends Error {}

/** Never show upstream detail, validation payloads, or exception messages to users. */
export function libraryError(error: unknown): string {
  return error instanceof LibraryError
    ? error.message
    : "The library couldn’t be updated. Please try again.";
}

export async function libraryRequest<T>(
  path: string,
  schema: z.ZodType<T>,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/research${path}`, {
      ...options,
      cache: "no-store",
      headers: { "content-type": "application/json", ...options.headers },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new LibraryError(
      "The library couldn’t be reached. Check your connection and try again.",
    );
  }
  if (!response.ok) {
    const message =
      response.status === 401
        ? "Your session expired. Sign in again to use your library."
        : response.status === 403
          ? "You don’t have permission to change this library."
          : response.status === 404
            ? "This library item is no longer available. Refresh the list."
            : response.status === 422 || response.status === 400
              ? "Check the form values and try again."
              : "The library is unavailable. Please try again.";
    throw new LibraryError(message);
  }
  try {
    return schema.parse(await response.json());
  } catch {
    throw new LibraryError(
      "The library returned an unexpected response. Please try again.",
    );
  }
}

export function libraryQuery(filters: LibraryFilters, after?: string): string {
  const params = new URLSearchParams({ limit: "50" });
  for (const key of ["query", "projectId", "kind", "tag"] as const) {
    const value = filters[key].trim();
    if (value) params.set(key, value);
  }
  if (after) params.set("after", after);
  return `/library/items?${params}`;
}

export function parseLibraryTags(value: string): string[] {
  return [
    ...new Set(
      value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
    ),
  ];
}

export function mergeLibraryItems(
  current: LibraryItem[],
  incoming: LibraryItem[],
): LibraryItem[] {
  const items = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) items.set(item.id, item);
  return [...items.values()];
}
