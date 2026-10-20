import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../components/landing/og/og-card";

export const alt = "HogsKin pricing — start free, every plan cites its sources.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "INDIVIDUAL PLANS",
      title: "Pricing.",
      subtitle: "Start free. Move up when research becomes a habit.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
