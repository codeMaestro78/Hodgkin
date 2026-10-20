import type { Metadata } from "next";
import type { CSSProperties } from "react";
import { ActionLink } from "./components/ui";
import { SiteFooter, SiteNav } from "./components/landing/site-chrome";
import { Critter } from "./components/crew/critter";
import { CrewEyes } from "./components/crew/crew-eyes";
import "./landing.css";
import "./not-found.css";

export const metadata: Metadata = {
  title: "Page not found · HogsKin",
};

/*
 * The 404 as a scene: a dashed trail draws itself across the page and
 * dead-ends, the magnifying-lens critter stands in for the zero — still
 * looking for the page — and the copy offers the way back. Motion is CSS
 * only; with reduced motion everything lands in its final, readable state.
 */
export default function NotFound() {
  return (
    <div className="lp nf">
      <a className="skip-link" href="#nf-copy">
        Skip to content
      </a>
      <SiteNav />
      <main className="nf-main">
        <span className="sr-only">404 — page not found</span>
        <div className="nf-stage" aria-hidden="true">
          <svg
            className="nf-trail"
            viewBox="0 0 1200 320"
            fill="none"
            preserveAspectRatio="xMidYMid meet"
          >
            <path
              className="nf-trail-path"
              d="M-24 258 C 150 210, 260 288, 420 244 S 660 150, 810 196 C 900 224, 940 190, 962 160"
              strokeDasharray="7 11"
            />
            <path
              className="nf-trail-end"
              d="M946 132 c 14 10 22 26 22 44 m 4 -46 c -8 14 -10 30 -6 46"
            />
          </svg>
          <span className="nf-digit" style={{ "--d": "80ms" } as CSSProperties}>
            4
          </span>
          <span className="nf-zero">
            <Critter kind="lens" size={176} delay={260} className="nf-critter" />
          </span>
          <span className="nf-digit" style={{ "--d": "240ms" } as CSSProperties}>
            4
          </span>
        </div>
        <div className="nf-copy" id="nf-copy">
          <h1 className="nf-title">This trail ends here.</h1>
          <p>
            The page you followed doesn’t exist — it never did, or it moved on.
            The research workspace is one question away.
          </p>
          <div className="nf-actions">
            <ActionLink href="/research">Open the workspace</ActionLink>
            <ActionLink href="/" secondary>
              Back to the front page
            </ActionLink>
          </div>
        </div>
      </main>
      <SiteFooter />
      <CrewEyes />
    </div>
  );
}
