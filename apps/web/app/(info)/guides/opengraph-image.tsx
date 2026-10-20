import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../../components/landing/og/og-card";

export const alt = "HogsKin guides — four manuals drawn from how the product works.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "PRACTICE, DOCUMENTED",
      title: "Guides.",
      subtitle: "Ask well. Pick depth. Read the trail. Keep what you learn.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
