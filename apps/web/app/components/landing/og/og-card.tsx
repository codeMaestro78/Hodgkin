import { readFile } from "node:fs/promises";
import { join } from "node:path";

import type { ReactElement } from "react";

const FONT_FILES = [
  { file: "outfit-regular.ttf", weight: 400 },
  { file: "outfit-semibold.ttf", weight: 600 },
] as const;

type OgFont = {
  name: string;
  data: ArrayBuffer;
  weight: 400 | 600;
  style: "normal";
};

/**
 * readFile Buffers may live inside a pooled ArrayBuffer together with other
 * data; slice out exactly the bytes this Buffer owns, since Satori needs a
 * standalone ArrayBuffer for each font.
 */
function copyFontData(buffer: Buffer): ArrayBuffer {
  return buffer.buffer.slice(
    buffer.byteOffset,
    buffer.byteOffset + buffer.byteLength,
  ) as ArrayBuffer;
}

/**
 * cwd differs between dev (apps/web) and standalone deploys, so try the
 * deployed public dir first and fall back to the repo-relative layout.
 */
async function readFontFile(file: string): Promise<Buffer> {
  try {
    return await readFile(join(process.cwd(), "public", "fonts", file));
  } catch {
    return await readFile(
      join(process.cwd(), "apps/web", "public", "fonts", file),
    );
  }
}

export async function loadOgFonts(): Promise<OgFont[]> {
  const fonts: OgFont[] = [];
  for (const { file, weight } of FONT_FILES) {
    const buffer = await readFontFile(file);
    fonts.push({
      name: "outfit",
      data: copyFontData(buffer),
      weight,
      style: "normal",
    });
  }
  return fonts;
}

/**
 * A 1200x630 social card, kept compatible with Satori: flexbox only, every
 * styled div carries an explicit style object, and every text node sits
 * inside a styled div.
 */
export function ogCard(props: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}): ReactElement {
  return (
    <div
      style={{
        width: "1200px",
        height: "630px",
        display: "flex",
        background: "#fffcfa",
        padding: "64px 72px",
        position: "relative",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", width: "100%" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <svg width="34" height="34" viewBox="0 0 24 24">
            <path
              d="M5 4.5v15M15 9.5v10"
              stroke="#252522"
              strokeWidth="3.75"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M5 13h10"
              stroke="#252522"
              strokeWidth="3.75"
              strokeLinecap="round"
              fill="none"
              strokeDasharray="1"
            />
            <circle cx="19.75" cy="4.75" r="2.75" fill="#a96142" />
          </svg>
          <div style={{ display: "flex", alignItems: "center" }}>
            <div
              style={{
                fontFamily: "outfit",
                fontWeight: 600,
                fontSize: 30,
                color: "#252522",
              }}
            >
              HogsKin
            </div>
            <div
              style={{
                fontFamily: "outfit",
                fontWeight: 600,
                fontSize: 30,
                color: "#a96142",
              }}
            >
              .
            </div>
          </div>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            margin: "auto 0",
          }}
        >
          <div
            style={{
              fontFamily: "outfit",
              fontWeight: 600,
              fontSize: 22,
              letterSpacing: "3px",
              color: "#b4552f",
            }}
          >
            {props.eyebrow}
          </div>
          <div
            style={{
              fontFamily: "outfit",
              fontWeight: 400,
              fontSize: 76,
              lineHeight: 1.05,
              letterSpacing: "-4px",
              color: "#252522",
              maxWidth: "1000px",
            }}
          >
            {props.title}
          </div>
          {props.subtitle && (
            <div
              style={{
                fontFamily: "outfit",
                fontWeight: 400,
                fontSize: 26,
                color: "#69675f",
                marginTop: 14,
              }}
            >
              {props.subtitle}
            </div>
          )}
        </div>
      </div>
      <div
        style={{
          width: "120px",
          height: "6px",
          background: "#b4552f",
          borderRadius: "3px",
          position: "absolute",
          left: 72,
          bottom: 64,
        }}
      />
    </div>
  );
}
