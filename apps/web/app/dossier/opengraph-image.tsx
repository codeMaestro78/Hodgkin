import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../components/landing/og/og-card";

export const alt = "HogsKin sample dossier — one question, start to finish.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "A SAMPLE DOSSIER",
      title: "What a finished run looks like.",
      subtitle: "Sections, citations, and the verification trail.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
