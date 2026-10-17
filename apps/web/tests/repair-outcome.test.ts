import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RepairOutcome } from "../app/components/repair-outcome";

describe("bounded-repair outcome", () => {
  it("announces the verified addition and its counts accessibly", () => {
    const html = renderToStaticMarkup(
      createElement(RepairOutcome, {
        outcome: {
          status: "repaired",
          newSourceCount: 2,
          verifiedFindingCount: 1,
        },
      }),
    );

    expect(html).toContain('aria-live="polite"');
    expect(html).toContain("Coverage gap repaired");
    expect(html).toContain("2 new sources and 1 verified finding");
  });

  it("explains a stopped repair while preserving the base report", () => {
    const html = renderToStaticMarkup(
      createElement(RepairOutcome, {
        outcome: { status: "stopped", reason: "no_new_evidence" },
      }),
    );

    expect(html).toContain("Coverage repair stopped");
    expect(html).toContain("No distinct evidence was found");
    expect(html).toContain("original report was kept");
  });
});
