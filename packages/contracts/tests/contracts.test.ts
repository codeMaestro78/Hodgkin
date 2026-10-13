import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ResearchStateSchema } from "../src/index.js";

function fixture(group: "valid" | "invalid", name: string): unknown {
  return JSON.parse(
    readFileSync(
      join(import.meta.dirname, "..", "fixtures", group, name),
      "utf8",
    ),
  );
}

describe("ResearchStateSchema", () => {
  it("accepts the shared valid fixture", () => {
    expect(
      ResearchStateSchema.safeParse(fixture("valid", "research-state.json"))
        .success,
    ).toBe(true);
  });

  it("rejects raw source content in compact graph state", () => {
    expect(
      ResearchStateSchema.safeParse(
        fixture("invalid", "research-state-raw-content.json"),
      ).success,
    ).toBe(false);
  });
});
