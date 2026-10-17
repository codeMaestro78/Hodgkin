import { z } from "zod";
import { DateTimeSchema, UuidSchema } from "./common";

const tags = z.array(z.string().max(40)).max(10);
const notes = z.string().max(2000);
export const CreateProjectRequestSchema = z
  .object({
    name: z.string().trim().min(1).max(100),
  })
  .strict();
export const ProjectSchema = z
  .object({
    id: UuidSchema,
    name: z.string().min(1).max(100),
    createdAt: DateTimeSchema,
  })
  .strict();
export const ProjectsResponseSchema = z
  .object({ projects: z.array(ProjectSchema) })
  .strict();
// A union preserves the XOR in emitted JSON Schema and generated Pydantic.
const save = {
  projectId: UuidSchema.optional(),
  tags: tags.default([]),
  notes: notes.default(""),
};
export const SaveLibraryItemRequestSchema = z.union([
  z.object({ ...save, reportId: UuidSchema }).strict(),
  z.object({ ...save, sourceId: UuidSchema }).strict(),
]);
export const OrganizeLibraryItemRequestSchema = z
  .object({
    projectId: UuidSchema.nullable(),
    tags,
    notes,
  })
  .strict();
export const LibraryItemSchema = z
  .object({
    id: UuidSchema,
    kind: z.enum(["report", "source"]),
    title: z.string(),
    runId: UuidSchema,
    reportId: UuidSchema.nullable(),
    reportVersion: z.number().int().min(1).nullable(),
    sourceId: UuidSchema.nullable(),
    url: z.string().nullable(),
    projectId: UuidSchema.nullable(),
    tags,
    notes,
    createdAt: DateTimeSchema,
  })
  .strict();
export const LibraryItemsResponseSchema = z
  .object({
    items: z.array(LibraryItemSchema),
    nextCursor: UuidSchema.nullable(),
  })
  .strict();
export const RemoveLibraryItemResponseSchema = z
  .object({ id: UuidSchema })
  .strict();
export type Project = z.infer<typeof ProjectSchema>;
export type CreateProjectRequest = z.infer<typeof CreateProjectRequestSchema>;
export type ProjectsResponse = z.infer<typeof ProjectsResponseSchema>;
export type LibraryItem = z.infer<typeof LibraryItemSchema>;
export type LibraryItemsResponse = z.infer<typeof LibraryItemsResponseSchema>;
export type RemoveLibraryItemResponse = z.infer<
  typeof RemoveLibraryItemResponseSchema
>;
export type SaveLibraryItemRequest = z.infer<
  typeof SaveLibraryItemRequestSchema
>;
export type OrganizeLibraryItemRequest = z.infer<
  typeof OrganizeLibraryItemRequestSchema
>;
