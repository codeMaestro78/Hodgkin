import { describe, expect, it } from "vitest";
import {
  chartDomain,
  chartSeries,
  clampEvidenceWidth,
  evidencePreset,
  formatValue,
  parseNumber,
  tableRows,
  toCsv,
  toTsv,
  type HastLike,
} from "../lib/report-table";

const text = (value: string): HastLike => ({ type: "text", value });
const cell = (tag: "th" | "td", ...children: HastLike[]): HastLike => ({
  type: "element",
  tagName: tag,
  children,
});
const cite = (n: number): HastLike => ({
  type: "element",
  tagName: "a",
  properties: { href: `#source-${n}` },
  children: [text(String(n))],
});

describe("tableRows", () => {
  const table: HastLike = {
    type: "element",
    tagName: "table",
    children: [
      {
        type: "element",
        tagName: "thead",
        children: [
          {
            type: "element",
            tagName: "tr",
            children: [cell("th", text("Model")), cell("th", text("Recall"))],
          },
        ],
      },
      {
        type: "element",
        tagName: "tbody",
        children: [
          {
            type: "element",
            tagName: "tr",
            children: [
              cell("td", text("Baseline")),
              cell("td", text("47.2% "), cite(1)),
            ],
          },
        ],
      },
    ],
  };
  it("keeps citations as bracketed numbers by default", () => {
    expect(tableRows(table)).toEqual([
      ["Model", "Recall"],
      ["Baseline", "47.2% [1]"],
    ]);
  });
  it("can drop citations for numeric parsing", () => {
    expect(tableRows(table, false)[1]).toEqual(["Baseline", "47.2%"]);
  });
  it("returns nothing without a node", () => {
    expect(tableRows(undefined)).toEqual([]);
  });
});

describe("CSV and TSV", () => {
  it("quotes separators, quotes and newlines", () => {
    expect(toCsv([["a,b", 'say "hi"', "x\ny"]])).toBe(
      '"a,b","say ""hi""","x\ny"',
    );
  });
  it("neutralises spreadsheet formulas but keeps negative numbers", () => {
    expect(toCsv([["=SUM(A1)", "-3.5", "@cmd", "+1"]])).toBe(
      "'=SUM(A1),-3.5,'@cmd,+1",
    );
  });
  it("neutralises formulas that also need quoting", () => {
    expect(toCsv([["=1,2"]])).toBe(`"'=1,2"`);
  });
  it("flattens tabs and newlines for TSV", () => {
    expect(
      toTsv([
        ["a\tb", "c\nd"],
        ["e", "f"],
      ]),
    ).toBe("a b\tc d\ne\tf");
  });
});

describe("parseNumber", () => {
  it.each([
    ["47.2%", 47.2, "%"],
    ["1,204", 1204, ""],
    ["-3.5 ms", -3.5, "ms"],
    ["\u22122", -2, ""],
    ["$12", 12, "$"],
    ["0.81 [2]", 0.81, ""],
  ])("parses %s", (raw, value, unit) => {
    expect(parseNumber(raw)).toEqual({ value, unit });
  });
  it.each(["", "n/a", "10-20", "about 5", "2024-01-02", "1,2,3"])(
    "rejects %s",
    (raw) => {
      expect(parseNumber(raw)).toBeNull();
    },
  );
});

describe("chartSeries", () => {
  it("returns numeric columns with a consistent unit", () => {
    const series = chartSeries([
      ["Method", "Recall", "Notes", "Latency"],
      ["A", "47.2%", "fast", "12 ms"],
      ["B", "61.8%", "slow", "40 ms"],
    ]);
    expect(series.map((item) => item.name)).toEqual(["Recall", "Latency"]);
    expect(series[0]?.points).toEqual([
      { label: "A", value: 47.2 },
      { label: "B", value: 61.8 },
    ]);
    expect(series[1]?.unit).toBe("ms");
  });
  it("skips columns that mix units", () => {
    expect(
      chartSeries([
        ["Item", "Value"],
        ["A", "4%"],
        ["B", "4 ms"],
      ]),
    ).toEqual([]);
  });
  it("needs text labels and at least two rows", () => {
    expect(
      chartSeries([
        ["Year", "Value"],
        ["2020", "1"],
        ["2021", "2"],
      ]),
    ).toEqual([]);
    expect(
      chartSeries([
        ["Item", "Value"],
        ["A", "1"],
      ]),
    ).toEqual([]);
  });
});

describe("chart helpers", () => {
  it("anchors the domain at zero", () => {
    expect(chartDomain([3, 9])).toEqual({ min: 0, max: 9 });
    expect(chartDomain([-4, 2])).toEqual({ min: -4, max: 2 });
    expect(chartDomain([0, 0])).toEqual({ min: 0, max: 1 });
  });
  it("formats with the reported unit", () => {
    expect(formatValue(47.2, "%")).toBe("47.2%");
    expect(formatValue(1204, "")).toBe("1,204");
    expect(formatValue(-12, "$")).toBe("-$12");
    expect(formatValue(3.25, "ms")).toBe("3.25 ms");
  });
});

describe("evidence panel width", () => {
  it("never goes below the minimum", () => {
    expect(clampEvidenceWidth(100, 1600)).toBe(300);
  });
  it("caps at 65% and leaves room for the report", () => {
    expect(clampEvidenceWidth(5000, 1600)).toBe(1040);
    expect(clampEvidenceWidth(5000, 800)).toBe(420);
  });
  it("resolves presets against the container", () => {
    expect(evidencePreset("reading", 1600)).toBe(340);
    expect(evidencePreset("split", 1600)).toBe(800);
    expect(evidencePreset("wide", 1600)).toBe(992);
  });
});
