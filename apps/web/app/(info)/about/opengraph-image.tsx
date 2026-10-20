import { ImageResponse } from "next/og";

import { loadOgFonts, ogCard } from "../../components/landing/og/og-card";

export const alt = "HogsKin — answers are cheap. Receipts aren't.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function image() {
  return new ImageResponse(
    ogCard({
      eyebrow: "WHY WE SHOW OUR WORK",
      title: "Answers are cheap. Receipts aren\u2019t.",
      subtitle: "The trail, the checks, and the crew that keeps them.",
    }),
    {
      ...size,
      fonts: await loadOgFonts(),
    },
  );
}
