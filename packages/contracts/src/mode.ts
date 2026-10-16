import { z } from "zod";

export const ResearchModeSchema = z.enum(["focused", "balanced", "deep"]);
export const ResearchModeResolutionSchema = z.enum([
  "explicit",
  "legacy-inferred",
]);
