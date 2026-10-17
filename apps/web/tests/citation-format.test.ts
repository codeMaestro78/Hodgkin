import { describe, expect, it } from "vitest";
import {
  formatReference,
  isCitationStyle,
  parseSourceList,
  referenceText,
  type ReferenceInput,
} from "../lib/citation-format";

const dated: ReferenceInput = {
  number: 2,
  title: "Pairs trading with crypto evidence",
  url: "https://www.example.org/papers/pairs",
  publisher: "Ledger Review",
  publishedAt: "2024-09-03T00:00:00Z",
  retrievedAt: "2026-06-17T08:00:00Z",
};
const bare: ReferenceInput = {
  number: 1,
  title: "Does cointegration last?",
  url: "https://example.test/evidence",
};
const text = (
  input: ReferenceInput,
  style: Parameters<typeof formatReference>[1],
) => referenceText(formatReference(input, style));

describe("formatReference", () => {
  it("formats APA with publisher, date and site", () => {
    expect(text(dated, "apa")).toBe(
      "Ledger Review. (2024, September 3). Pairs trading with crypto evidence. example.org. https://www.example.org/papers/pairs",
    );
  });

  it("uses n.d. and the site as author when metadata is missing", () => {
    expect(text(bare, "apa")).toBe(
      "example.test. (n.d.). Does cointegration last? https://example.test/evidence",
    );
    expect(text(bare, "harvard")).toBe(
      "example.test (n.d.) Does cointegration last? Available at: https://example.test/evidence.",
    );
  });

  it("formats MLA with Sept. and an access date", () => {
    expect(text(dated, "mla")).toBe(
      "“Pairs trading with crypto evidence.” Ledger Review, 3 Sept. 2024, www.example.org/papers/pairs. Accessed 17 June 2026.",
    );
    expect(text(bare, "mla")).toBe(
      "“Does cointegration last?” example.test, example.test/evidence.",
    );
  });

  it("formats Chicago, falling back to the access date", () => {
    expect(text(dated, "chicago")).toBe(
      "Ledger Review. “Pairs trading with crypto evidence.” September 3, 2024. https://www.example.org/papers/pairs.",
    );
    expect(text({ ...dated, publishedAt: null }, "chicago")).toContain(
      "Accessed June 17, 2026.",
    );
  });

  it("formats IEEE with the reference number and abbreviated month", () => {
    expect(text(dated, "ieee")).toBe(
      "[2] Ledger Review, “Pairs trading with crypto evidence,” example.org, 2024. Accessed: Jun. 17, 2026. [Online]. Available: https://www.example.org/papers/pairs",
    );
  });

  it("marks only the work title (or container) as italic", () => {
    const em = formatReference(dated, "apa").filter((part) => part.em);
    expect(em).toEqual([{ text: dated.title, em: true }]);
  });

  it("ignores invalid dates instead of printing NaN", () => {
    expect(text({ ...dated, publishedAt: "not a date" }, "apa")).toContain(
      "(n.d.)",
    );
  });
});

describe("parseSourceList", () => {
  it("reads the numbered markdown source list", () => {
    expect(
      parseSourceList(
        "## Findings\nText [1]\n\n## Sources\n1. [A](https://a.test/x)\n2. [B (2024)](https://b.test)\n",
      ),
    ).toEqual([
      { number: 1, title: "A", url: "https://a.test/x" },
      { number: 2, title: "B (2024)", url: "https://b.test" },
    ]);
    expect(parseSourceList("## Findings\nNo list")).toEqual([]);
  });
});

it("validates stored citation styles", () => {
  expect(isCitationStyle("ieee")).toBe(true);
  expect(isCitationStyle("vancouver")).toBe(false);
});
