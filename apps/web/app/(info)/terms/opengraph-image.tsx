import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../../components/landing/og/og-card";

export const alt = "HogsKin terms of service — in plain English.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "THE FINE PRINT, IN PLAIN SIGHT",
      title: "Terms of Service.",
      subtitle: "The deal between you and us, readable.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
