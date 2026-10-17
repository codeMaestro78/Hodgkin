import { ReportDocumentSchema } from "@research/contracts";

/** Invalid/unknown versions retain the historical Markdown and checks fallback. */
export function parseReportDocument(value: unknown) {
  const result = ReportDocumentSchema.safeParse(value);
  return result.success ? result.data : null;
}

/** A supported quotation does not independently validate a reported statistic. */
export function hasNumericalFinding(
  document: {
    findings: { text: string; sourceIds: string[] }[];
  } | null,
): boolean {
  return (
    document?.findings.some(({ text }) =>
      /\b\d[\d,]*(?:\.\d+)?\s*(?:%|percent\b|percentage points\b|ms\b|milliseconds\b)/i.test(
        text,
      ),
    ) ?? false
  );
}
