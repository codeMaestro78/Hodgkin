export type ReportSection = { id: string; title: string };

/** Structured findings are authoritative; historical reports need explicit check records. */
export function hasNoVerifiedFindings(
  document: { findings: readonly unknown[] } | null,
  checks: readonly { publishedInReport?: boolean }[] | undefined,
): boolean {
  if (document) return document.findings.length === 0;
  return (
    checks !== undefined && !checks.some((claim) => claim.publishedInReport)
  );
}

/** Hide the old generated publication ratio, preserving other report mathematics. */
export function reportDisplayMarkdown(markdown: string): string {
  return markdown.replace(
    /^\$\$\r?\n\\text\{published share\} = \\frac\{\d+\}\{\d+\} \\approx [\d.]+\\%\r?\n\$\$[\t ]*(?:\r?\n)?/gm,
    "",
  );
}

/** Match rendered Markdown headings, excluding fenced examples and source lists. */
export function reportSections(markdown: string): ReportSection[] {
  const sections: ReportSection[] = [];
  let fence: string | null = null;
  for (const line of markdown.split("\n")) {
    const marker = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (marker?.[1]) {
      const character = marker[1].charAt(0);
      if (!fence) fence = character;
      else if (character === fence) fence = null;
      continue;
    }
    if (fence) continue;
    const heading = line.match(/^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if (!heading?.[1]) continue;
    const title = heading[1]
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/[*_`]/g, "");
    if (/^sources$/i.test(title)) break;
    sections.push({ id: `report-section-${sections.length}`, title });
  }
  return sections;
}

export function readingMinutes(markdown: string): number {
  return Math.max(
    1,
    Math.ceil(markdown.trim().split(/\s+/).filter(Boolean).length / 220),
  );
}

export type AnswerSectionKind = "lead" | "limitations" | "method" | "body";

/** Classify a level-2 report heading so the lead, limitations and method read differently. */
export function answerSectionKind(title: string): AnswerSectionKind {
  const text = title.trim().toLowerCase();
  if (
    /^(executive summary|direct answer|bottom line|summary|answer)$/.test(text)
  )
    return "lead";
  if (/^(limitations?|evidence limitations?|caveats)$/.test(text))
    return "limitations";
  if (/^(methodology|method|methods)$/.test(text)) return "method";
  return "body";
}

type SuggestionInput = {
  gaps?: { suggestedQuery: string | null; status: string }[] | undefined;
  questionCoverage?: { text: string; status: string }[] | undefined;
};

/** Next questions grounded in recorded gaps and uncovered plan questions, never invented. */
export function followupSuggestions(input: SuggestionInput, limit = 3) {
  const seen = new Set<string>();
  const out: string[] = [];
  const push = (value: string | null | undefined) => {
    const text = value?.trim().replace(/\s+/g, " ");
    if (!text || text.length < 5 || text.length > 1000) return;
    const key = text.toLowerCase();
    if (seen.has(key) || out.length >= limit) return;
    seen.add(key);
    out.push(text);
  };
  for (const gap of input.gaps ?? [])
    if (gap.status === "open") push(gap.suggestedQuery);
  for (const item of input.questionCoverage ?? [])
    if (item.status !== "addressed") push(item.text);
  return out;
}
