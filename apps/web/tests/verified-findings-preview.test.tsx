import { expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { VerifiedFindingsPreview } from "../app/components/verified-findings-preview";

it("shows checked draft claims with a source inspection action and honest status", () => {
  const html = renderToStaticMarkup(
    <VerifiedFindingsPreview
      findings={[{ text: "A supported claim.", sourceIds: ["source-1"] }]}
      total={3}
      sources={[{ id: "source-1", title: "Original paper", url: "https://example.org" }]}
      onOpenSource={() => undefined}
    />,
  );
  expect(html).toContain("Evidence-checked findings");
  expect(html).toContain("A supported claim.");
  expect(html).toContain("Inspect Original paper");
  expect(html).toContain("The report and coverage review are still in progress.");
  expect(html).toContain("3 checked");
});
