import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../../components/landing/og/og-card";

export const alt = "HogsKin privacy policy — no ad trackers, no selling.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "YOUR RESEARCH BELONGS TO YOU",
      title: "Privacy Policy.",
      subtitle: "What we hold, what stays on your device.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
