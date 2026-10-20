import type { Metadata } from "next";
import Link from "next/link";
import type { CSSProperties } from "react";
import { Icon } from "../components/ui";
import { LandingMotion } from "../components/landing-motion";
import { EvidenceField } from "../components/landing/evidence-field";
import { FaqThread } from "../components/landing/faq-thread";
import { SiteFooter, SiteNav } from "../components/landing/site-chrome";
import { Critter } from "../components/crew/critter";
import { CrewEyes } from "../components/crew/crew-eyes";
import { PricingPlans } from "./pricing-plans";
import "../landing.css";
import "./pricing.css";

export const metadata: Metadata = { title: "Pricing · HogsKin" };

const YES = true;
const NO = false;

const COMPARISON: [
  string,
  string | boolean,
  string | boolean,
  string | boolean,
][] = [
  ["Proposed monthly research units", "5", "20", "40"],
  [
    "Research modes",
    "Focused",
    "Focused + Balanced",
    "Focused + Balanced + Deep",
  ],
  ["Inline citations and source passages", YES, YES, YES],
  ["Research history and personal library", YES, YES, YES],
  ["Markdown and BibTeX export", YES, YES, YES],
  ["Compare reports side by side", NO, YES, YES],
  ["Read-only share links", NO, YES, YES],
  ["Batches and scheduled runs", NO, NO, YES],
];

const QUESTIONS: [string, string][] = [
  [
    "Is the Free plan really free?",
    "Yes. No card is needed to start, and Free produces the same cited, source-linked reports as the paid plans. It simply runs fewer of them.",
  ],
  [
    "Do deeper runs cost more?",
    "The current proposal allocates 1 unit for Focused, 2 for Balanced, and 4 for Deep. Monthly allowances remain provisional pending cost validation.",
  ],
  [
    "Are paid plans available now?",
    "The paid-plan buttons show whether checkout is currently available. When enabled, checkout requires signing in and completes securely through Stripe. Prices and unit allowances remain proposals until cost validation is complete. Existing reports and sources remain available regardless of future plan changes.",
  ],
  [
    "Can I switch between monthly and yearly?",
    "The proposed yearly prices are billed once per year and are about 17% lower than paying monthly for twelve months. Annual billing is not available yet.",
  ],
];

function Cell({ value }: { value: string | boolean }) {
  if (typeof value === "string") return <strong>{value}</strong>;
  return value ? (
    <span className="pr-yes">
      <Icon name="check" size={13} />
      <span className="sr-only">Included</span>
    </span>
  ) : (
    <span className="pr-no">
      <i aria-hidden="true" />
      <span className="sr-only">Not included</span>
    </span>
  );
}

export default function PricingPage() {
  return (
    <div className="lp lp-pricing">
      <a className="skip-link" href="#plans">
        Skip to plans
      </a>
      <SiteNav active="pricing" />
      <main>
        <section className="pr-hero" id="plans">
          <div className="lp-field-wrap pr-field" aria-hidden="true">
            <EvidenceField />
          </div>
          <div className="pr-hero-copy">
            <p className="pr-eyebrow lp-enter">Individual plans</p>
            <h1 className="pr-title" aria-label="Pricing">
              {[..."Pricing"].map((char, index) => (
                <span
                  key={index}
                  className="lp-char"
                  aria-hidden="true"
                  style={{ "--d": `${120 + index * 55}ms` } as CSSProperties}
                >
                  {char}
                </span>
              ))}
            </h1>
            <p className="pr-lead lp-enter">
              Start free. Move up when research becomes a habit. Every plan
              cites its sources.
            </p>
            <p className="pr-lead lp-enter" role="status">
              Pricing preview: paid-plan checkout availability is checked live
              below. Unit allowances are provisional pending cost validation.
            </p>
          </div>
          <div className="pr-stage lp-enter">
            <PricingPlans />
          </div>
        </section>

        <section
          className="lp-section pr-compare"
          aria-labelledby="compare-title"
        >
          <header className="lp-section-head">
            <h2 id="compare-title">Proposed plan differences.</h2>
            <p>
              The same evidence-first reports on every plan. Paid plans read
              deeper and do more with them.
            </p>
          </header>
          <div className="pr-table-wrap" data-reveal>
            <table className="pr-table">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">Feature</span>
                  </th>
                  <th scope="col">Free</th>
                  <th scope="col">Scholar</th>
                  <th scope="col">Investigator</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISON.map(([label, ...values]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    {values.map((value, index) => (
                      <td key={index}>
                        <Cell value={value} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pr-notes">
            <div data-reveal>
              <span className="pr-note-icon">
                <Icon name="sliders" size={18} />
              </span>
              <h3>Depth is a ceiling, not a quota.</h3>
              <p>
                Focused, Balanced and Deep have different provider and source
                ceilings. A run reads what the question needs, within that
                limit.
              </p>
            </div>
            <div data-reveal>
              <span className="pr-note-icon">
                <Icon name="folder" size={18} />
              </span>
              <h3>Your research stays yours.</h3>
              <p>
                Reports, sources and history remain available. Markdown and
                BibTeX export are supported; PDF export is not currently
                offered.
              </p>
            </div>
          </div>
        </section>

        <section className="lp-section pr-faq" aria-labelledby="pricing-faq">
          <div className="pr-faq-intro">
            <h2 id="pricing-faq">Questions about plans.</h2>
            <p>Still deciding? Start on Free and see a full report first.</p>
            <Link
              href="/signup?plan=free"
              className="lp-btn lp-btn-ink"
              data-magnetic
            >
              Start free
              <Icon name="arrow" size={16} />
            </Link>
          </div>
          <div className="lp-faq-stage">
            <FaqThread items={QUESTIONS} />
            <span className="lp-peek-slot" aria-hidden="true">
              <Critter kind="quill" pose="peek" size={70} delay={200} />
            </span>
          </div>
        </section>
      </main>
      <SiteFooter />
      <LandingMotion />
      <CrewEyes />
    </div>
  );
}
