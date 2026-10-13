export type ReportSection = { id: string; title: string };

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
