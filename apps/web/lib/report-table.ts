/** Pure helpers behind report tables: extraction, CSV, chart detection and panel sizing. */

export type HastLike = {
  type: string;
  tagName?: string;
  value?: string;
  properties?: Record<string, unknown>;
  children?: HastLike[];
};

function cellText(node: HastLike, citations: boolean): string {
  if (node.type === "text") return node.value ?? "";
  const href = node.properties?.href;
  if (
    node.tagName === "a" &&
    typeof href === "string" &&
    href.startsWith("#source-")
  )
    return citations ? `[${href.slice(8)}]` : "";
  return (node.children ?? [])
    .map((child) => cellText(child, citations))
    .join("");
}

/** Reads a rendered markdown table into rows of trimmed cell text. */
export function tableRows(table: HastLike | undefined, citations = true) {
  const rows: string[][] = [];
  const walk = (node: HastLike) => {
    if (node.tagName === "tr") {
      rows.push(
        (node.children ?? [])
          .filter((cell) => cell.tagName === "th" || cell.tagName === "td")
          .map((cell) =>
            cellText(cell, citations)
              .replace(/\s+/g, " ")
              .replace(/\s+([,.;:])/g, "$1")
              .trim(),
          ),
      );
      return;
    }
    node.children?.forEach(walk);
  };
  if (table) walk(table);
  return rows;
}

function csvCell(raw: string) {
  const value = /^[=+\-@\t\r]/.test(raw) && !parseNumber(raw) ? `'${raw}` : raw;
  return /[",\r\n]/.test(value) || /^\s|\s$/.test(value)
    ? `"${value.replaceAll('"', '""')}"`
    : value;
}

/** RFC 4180 CSV; formula-leading cells are prefixed so spreadsheets do not execute them. */
export function toCsv(rows: string[][]) {
  return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function toTsv(rows: string[][]) {
  return rows
    .map((row) => row.map((cell) => cell.replace(/[\t\r\n]+/g, " ")).join("\t"))
    .join("\n");
}

export type ParsedNumber = { value: number; unit: string };

const NUMBER =
  /^(?<sign>[-+\u2212]?)(?<currency>[$\u20ac\u00a3]?)(?<digits>\d{1,3}(?:,\d{3})+|\d+)(?<fraction>\.\d+)?\s*(?<unit>%|[A-Za-z\u00b5/]{1,8})?$/;

/** Parses "47.2%", "1,204", "-3.5 ms", "$12" — anything else (ranges, prose) is not a number. */
export function parseNumber(raw: string): ParsedNumber | null {
  const match = NUMBER.exec(raw.replace(/\[\d+\]/g, "").trim());
  if (!match?.groups) return null;
  const { sign, currency, digits, fraction, unit } = match.groups;
  const value = Number(`${digits!.replaceAll(",", "")}${fraction ?? ""}`);
  if (!Number.isFinite(value)) return null;
  return {
    value: sign ? -value : value,
    unit: currency || unit || "",
  };
}

export type ChartSeries = {
  name: string;
  unit: string;
  points: { label: string; value: number }[];
};

export const CHART_MAX_ROWS = 24;

/**
 * A table is chartable when it has a label column and at least one other
 * column whose every body cell is a number in one consistent unit.
 */
export function chartSeries(rows: string[][]): ChartSeries[] {
  const [header, ...body] = rows;
  if (!header || header.length < 2) return [];
  if (body.length < 2 || body.length > CHART_MAX_ROWS) return [];
  const labels = body.map((row) => row[0] ?? "");
  if (labels.some((label) => !label || parseNumber(label))) return [];
  const series: ChartSeries[] = [];
  for (let column = 1; column < header.length; column++) {
    const parsed = body.map((row) => parseNumber(row[column] ?? ""));
    if (parsed.some((item) => !item)) continue;
    const units = new Set(parsed.map((item) => item!.unit));
    if (units.size !== 1) continue;
    series.push({
      name: header[column] || `Column ${column + 1}`,
      unit: parsed[0]!.unit,
      points: parsed.map((item, index) => ({
        label: labels[index]!,
        value: item!.value,
      })),
    });
  }
  return series;
}

/** Axis domain that always includes zero so bar lengths stay honest. */
export function chartDomain(values: number[]) {
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  return max === min ? { min, max: min + 1 } : { min, max };
}

export function formatValue(value: number, unit: string) {
  const text = new Intl.NumberFormat("en", {
    maximumFractionDigits: Math.abs(value) < 10 ? 2 : 1,
  }).format(value);
  if (!unit) return text;
  if (unit === "%") return `${text}%`;
  if (/^[$\u20ac\u00a3]$/.test(unit))
    return value < 0 ? `-${unit}${text.slice(1)}` : `${unit}${text}`;
  return `${text} ${unit}`;
}

export const EVIDENCE_MIN = 300;
export const EVIDENCE_DEFAULT = 340;
export const EVIDENCE_MAX_SHARE = 0.65;
export const REPORT_MIN = 380;

/** Keeps the evidence panel usable without crushing the report column. */
export function clampEvidenceWidth(width: number, container: number) {
  const max = Math.max(
    EVIDENCE_MIN,
    Math.min(container * EVIDENCE_MAX_SHARE, container - REPORT_MIN),
  );
  return Math.round(Math.min(Math.max(width, EVIDENCE_MIN), max));
}

export function evidencePreset(
  preset: "reading" | "split" | "wide",
  container: number,
) {
  const width =
    preset === "reading"
      ? EVIDENCE_DEFAULT
      : preset === "split"
        ? container / 2
        : container * 0.62;
  return clampEvidenceWidth(width, container);
}
