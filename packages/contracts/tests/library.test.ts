import { describe, expect, it } from "vitest";
import {
  CreateProjectRequestSchema,
  SaveLibraryItemRequestSchema,
  OrganizeLibraryItemRequestSchema,
} from "../src/library";

const id = "c09a98ae-a3ef-4f8d-903a-c02452694c28";
describe("private library contracts", () => {
  it("trims folder names and enforces bounds", () => {
    expect(CreateProjectRequestSchema.parse({ name: " Folder " })).toEqual({
      name: "Folder",
    });
    for (const name of ["  ", "x".repeat(101)]) {
      expect(CreateProjectRequestSchema.safeParse({ name }).success).toBe(
        false,
      );
    }
  });
  it("requires exactly one target and defaults annotations", () => {
    expect(SaveLibraryItemRequestSchema.parse({ reportId: id })).toEqual({
      reportId: id,
      tags: [],
      notes: "",
    });
    for (const payload of [
      {},
      { reportId: id, sourceId: id },
      { sourceId: "bad" },
      { reportId: id, tags: Array(11).fill("a") },
      { reportId: id, tags: ["x".repeat(41)] },
      { reportId: id, notes: "x".repeat(2001) },
    ]) {
      expect(SaveLibraryItemRequestSchema.safeParse(payload).success).toBe(
        false,
      );
    }
  });
  it("requires complete organize fields with nullable folder", () => {
    expect(
      OrganizeLibraryItemRequestSchema.parse({
        projectId: null,
        tags: [],
        notes: "",
      }),
    ).toEqual({ projectId: null, tags: [], notes: "" });
    expect(OrganizeLibraryItemRequestSchema.safeParse({}).success).toBe(false);
  });
});
