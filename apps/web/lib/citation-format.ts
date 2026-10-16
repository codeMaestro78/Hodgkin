export const CITATION_STYLES = [
  { id: "apa", label: "APA 7" },
  { id: "mla", label: "MLA 9" },
  { id: "chicago", label: "Chicago" },
  { id: "harvard", label: "Harvard" },
  { id: "ieee", label: "IEEE" },
] as const;
export type CitationStyle = (typeof CITATION_STYLES)[number]["id"];

export type ReferenceInput = {
  number: number;
  title: string;
  url: string;
  publisher?: string | null | undefined;
  publishedAt?: string | null | undefined;
  retrievedAt?: string | null | undefined;
};
/** Formatted reference as ordered runs; `em` marks the italic work title. */
export type ReferencePart = { text: string; em?: boolean };

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
/** MLA keeps May, June and July whole and writes "Sept."; IEEE abbreviates all but May. */
const mlaMonth = (month: string) =>
  month.length <= 4
    ? month
    : month === "September"
      ? "Sept."
      : month.slice(0, 3) + ".";
const ieeeMonth = (month: string) =>
  month === "May" ? month : month.slice(0, 3) + ".";

export function isCitationStyle(value: unknown): value is CitationStyle {
  return CITATION_STYLES.some((style) => style.id === value);
}

export function siteName(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function date(value?: string | null) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return {
    year: parsed.getUTCFullYear(),
    month: MONTHS[parsed.getUTCMonth()]!,
    day: parsed.getUTCDate(),
  };
}

/** No author metadata is collected, so the publisher (or site) stands in as the organisational author. */
export function formatReference(
  reference: ReferenceInput,
  style: CitationStyle,
): ReferencePart[] {
  const site = siteName(reference.url);
  const title = reference.title.trim() || site || reference.url;
  const author = reference.publisher?.trim() || site || "Unknown publisher";
  const published = date(reference.publishedAt);
  const accessed = date(reference.retrievedAt);
  const sameAsAuthor = author.toLowerCase() === site.toLowerCase();
  const end = (text: string) => (/[.?!]$/.test(text) ? "" : ".");

  switch (style) {
    case "apa":
      return [
        { text: `${author}. (` },
        {
          text: published
            ? `${published.year}, ${published.month} ${published.day}`
            : "n.d.",
        },
        { text: "). " },
        { text: title, em: true },
        { text: end(title) + " " },
        ...(sameAsAuthor || !site ? [] : [{ text: `${site}. ` }]),
        { text: reference.url },
      ];
    case "mla":
      return [
        { text: `“${title}${end(title) ? "." : ""}” ` },
        { text: reference.publisher?.trim() || site, em: true },
        {
          text: published
            ? `, ${published.day} ${mlaMonth(published.month)} ${published.year}`
            : "",
        },
        { text: `, ${reference.url.replace(/^https?:\/\//, "")}.` },
        {
          text: accessed
            ? ` Accessed ${accessed.day} ${mlaMonth(accessed.month)} ${accessed.year}.`
            : "",
        },
      ];
    case "chicago":
      return [
        { text: `${author}. “${title}${end(title) ? "." : ""}” ` },
        {
          text: published
            ? `${published.month} ${published.day}, ${published.year}. `
            : accessed
              ? `Accessed ${accessed.month} ${accessed.day}, ${accessed.year}. `
              : "",
        },
        { text: `${reference.url}.` },
      ];
    case "harvard":
      return [
        { text: `${author} (${published ? published.year : "n.d."}) ` },
        { text: title, em: true },
        { text: `${end(title)} Available at: ${reference.url}` },
        {
          text: accessed
            ? ` (Accessed: ${accessed.day} ${accessed.month} ${accessed.year}).`
            : ".",
        },
      ];
    case "ieee":
      return [
        { text: `[${reference.number}] ${author}, “${title},” ` },
        ...(site && !sameAsAuthor ? [{ text: site, em: true }] : []),
        ...(site && !sameAsAuthor ? [{ text: ", " }] : []),
        { text: published ? `${published.year}. ` : "" },
        {
          text: accessed
            ? `Accessed: ${ieeeMonth(accessed.month)} ${accessed.day}, ${accessed.year}. `
            : "",
        },
        { text: `[Online]. Available: ${reference.url}` },
      ];
  }
}

export function referenceText(parts: ReferencePart[]) {
  return parts
    .map((part) => part.text)
    .join("")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Parse the report's trailing "## Sources" list: `1. [Title](https://…)`. */
export function parseSourceList(markdown: string) {
  const section = markdown.split(/^## Sources\s*$/im)[1] ?? "";
  return Array.from(
    section.matchAll(/^\s*(\d+)\.\s+\[([^\n]*?)\]\((https?:\/\/[^\s)]+)\)/gm),
    (match) => ({
      number: Number(match[1]),
      title: match[2] ?? "",
      url: match[3] ?? "",
    }),
  );
}
