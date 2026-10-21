import { describe, expect, it } from "vitest";
import { researchApiUrl } from "../lib/research-api-url";

describe("researchApiUrl", () => {
  it("resolves API paths against the service binding base", () => {
    expect(
      researchApiUrl("https://api.example.test", "/research/runs").href,
    ).toBe("https://api.example.test/research/runs");
  });

  it("preserves a path prefix supplied by the bound base URL", () => {
    expect(
      researchApiUrl("https://api.example.test/internal/", "/s").href,
    ).toBe("https://api.example.test/internal/s");
  });
});
