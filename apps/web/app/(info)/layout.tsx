import type { ReactNode } from "react";
import { LandingMotion } from "../components/landing-motion";
import { CrewEyes } from "../components/crew/crew-eyes";
import { SiteFooter, SiteNav } from "../components/landing/site-chrome";
import "../landing.css";
import "./info.css";

/*
 * Shared chrome for the public info pages: Terms, Privacy, About, Guides.
 * The prose itself lives in each page; this layout only supplies the house
 * navigation, footer, and motion layer.
 */
export default function InfoLayout({ children }: { children: ReactNode }) {
  return (
    <div className="lp lg">
      <a className="skip-link" href="#page">
        Skip to content
      </a>
      <SiteNav />
      <main id="page">{children}</main>
      <SiteFooter />
      <LandingMotion />
      <CrewEyes />
    </div>
  );
}
