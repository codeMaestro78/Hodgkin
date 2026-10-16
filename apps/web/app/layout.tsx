import type { Metadata } from "next";
import type { ReactNode } from "react";
import localFont from "next/font/local";
import "./styles.css";
import "./onboarding.css";

const outfit = localFont({
  src: [
    {
      path: "../public/fonts/outfit-regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../public/fonts/outfit-semibold.ttf",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-outfit",
  display: "swap",
});

export const metadata: Metadata = {
  title: "HogsKin · Research with a trail",
  description:
    "Turn a question into a considered answer with sources and a research trail close at hand.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <body className={outfit.variable}>{children}</body>
    </html>
  );
}
