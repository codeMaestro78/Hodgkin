import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "./components/landing/og/og-card";

export const alt = "HogsKin — research that shows its work.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "CURIOSITY, WITH A PAPER TRAIL",
      title: "Research that shows its work.",
      subtitle: "Every answer keeps the sources behind it.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
