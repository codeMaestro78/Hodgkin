import type { CSSProperties } from "react";

const GLYPHS = {
  journal: "M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3Z M5 17a3 3 0 0 1 3-3h10",
  stats: "M5 19v-8 M10 19V6 M15 19v-5 M20 19V9",
  standard: "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18Z M8.5 12l2.5 2.5 4.5-5",
  field: "M12 21s-6-6-6-11a6 6 0 0 1 12 0c0 5-6 11-6 11Z M12 10h.01",
  preprint: "M7 3h7l4 4v14H7Z M14 3v4h4 M10 12h5 M10 16h5",
  docs: "M9 7l-5 5 5 5 M15 7l5 5-5 5",
  data: "M5 6c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Z M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6 M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3",
  report: "M12 3v9h9 M12 3a9 9 0 1 0 9 9",
  news: "M4 5h13v14H6a2 2 0 0 1-2-2Z M17 9h3v8a2 2 0 0 1-2 2 M8 9h5 M8 13h5",
  patent: "M9 18h6 M10 21h4 M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3Z",
  globe:
    "M12 3a9 9 0 1 1 0 18a9 9 0 1 1 0-18Z M3 12h18 M12 3c3 3 3 15 0 18 M12 3c-3 3-3 15 0 18",
  quote: "M4 5h16v11H9l-5 4Z M9 10h6",
  law: "M12 4v16 M7 20h10 M5 8h14 M5 8l-3 6a3 3 0 0 0 6 0Z M19 8l-3 6a3 3 0 0 0 6 0Z",
  clinic:
    "M12 6v12 M6 12h12 M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z",
} as const;

const TONES: readonly string[] = [
  "#f2dca8",
  "#cfe2d3",
  "#d3e1ec",
  "#efd3cd",
  "#e8dfd0",
];

type Source = [keyof typeof GLYPHS, string];

const ROWS: Source[][] = [
  [
    ["journal", "Peer-reviewed journals"],
    ["stats", "Government statistics"],
    ["standard", "Standards bodies"],
    ["field", "Field studies"],
    ["preprint", "Preprints"],
    ["docs", "Technical documentation"],
    ["clinic", "Clinical guidance"],
  ],
  [
    ["data", "Public datasets"],
    ["report", "Industry reports"],
    ["news", "Reporting"],
    ["patent", "Patents"],
    ["globe", "Reference works"],
    ["quote", "Interviews and transcripts"],
    ["law", "Regulation"],
  ],
];

function Tile({
  glyph,
  label,
  tone,
}: {
  glyph: keyof typeof GLYPHS;
  label: string;
  tone: string;
}) {
  return (
    <li className="lp-source-tile">
      <span style={{ "--tone": tone } as CSSProperties}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <path d={GLYPHS[glyph]} />
        </svg>
      </span>
      {label}
    </li>
  );
}

export function SourceMarquee() {
  return (
    <div className="lp-marquee">
      {ROWS.map((row, rowIndex) => (
        <div
          className="lp-marquee-row"
          key={rowIndex}
          data-direction={rowIndex ? "right" : "left"}
        >
          {/* The row is drawn twice so the loop has no seam. */}
          {[0, 1].map((copy) => (
            <ul
              className="lp-marquee-track"
              key={copy}
              aria-hidden={copy ? "true" : undefined}
            >
              {row.map(([glyph, label], index) => (
                <Tile
                  key={label}
                  glyph={glyph}
                  label={label}
                  tone={
                    TONES[(index + rowIndex * 2) % TONES.length] ?? "#e8dfd0"
                  }
                />
              ))}
            </ul>
          ))}
        </div>
      ))}
    </div>
  );
}
