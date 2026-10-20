import type { Metadata } from "next";
import Link from "next/link";
import type { CSSProperties } from "react";
import { Icon, Status, safeUrl } from "../components/ui";
import { LandingMotion } from "../components/landing-motion";
import { SiteFooter, SiteNav } from "../components/landing/site-chrome";
import { Critter } from "../components/crew/critter";
import { CrewEyes } from "../components/crew/crew-eyes";
import "../landing.css";
import "./dossier.css";

export const metadata: Metadata = {
  title: "Sample dossier · HogsKin",
  description:
    "An illustrative research dossier layout. Its claims and metrics are examples, not a live verified run.",
};

const QUESTION = "Do standing desks measurably improve focus at work?";

type Cite = { n: number };

function Cite({ n }: Cite) {
  return (
    <a className="ds-cite" href={`#ds-source-${n}`} aria-label={`Source ${n}`}>
      {n}
    </a>
  );
}

const SECTIONS: { id: string; heading: string; paras: React.ReactNode[] }[] = [
  {
    id: "ds-answer",
    heading: "Short answer.",
    paras: [
      <>
        Evidence supports a modest, real reduction in sitting time when
        knowledge workers are given sit-stand desks — trial settings report
        roughly 30 to 60 fewer minutes of sitting per day
        <Cite n={1} />. Whether that buys sharper focus is less certain:
        measured effects on attention and self-reported productivity are small
        and inconsistent
        <Cite n={2} />
        <Cite n={3} />. The honest summary is that standing desks change
        posture more reliably than they change output.
      </>,
    ],
  },
  {
    id: "ds-holds",
    heading: "What holds up.",
    paras: [
      <>
        Sit-stand arrangements reliably reduce occupational sitting across
        randomized trials, with the largest effects where organizations make
        posture change easy and normal rather than a stunt
        <Cite n={1} />
        <Cite n={4} />. Benefits compound when desks are paired with regular
        movement breaks — standing still all day trades one sedentary posture
        for another
        <Cite n={2} />. Musculoskeletal discomfort tends to drop when workers
        can alternate positions freely
        <Cite n={3} />.
      </>,
    ],
  },
  {
    id: "ds-overstated",
    heading: "What is overstated.",
    paras: [
      <>
        Headlines promising large gains in concentration or weight loss outrun
        the trials. Measured cognition effects are near zero in the
        best-controlled studies
        <Cite n={6} />, and prolonged static standing carries its own
        complaints — leg discomfort and, in susceptible people, vascular
        strain
        <Cite n={3} />
        <Cite n={5} />. A desk is a posture option, not an exercise program
        <Cite n={4} />.
      </>,
    ],
  },
  {
    id: "ds-next",
    heading: "What we would test next.",
    paras: [
      <>
        The open question is output, not posture: trials that measure actual
        knowledge-work deliverables over months rather than lab attention
        tasks over days
        <Cite n={6} />, and which work settings benefit most — deep-focus
        roles appear to prefer frequent posture changes, while collaborative
        roles may not
        <Cite n={5} />.
      </>,
    ],
  },
];

const SOURCES: {
  n: number;
  title: string;
  publisher: string;
  url: string;
  year: string;
}[] = [
  {
    n: 1,
    title: "Sit-stand workstations for reducing sedentary time at work",
    publisher: "Cochrane Library",
    url: "https://www.cochrane.org",
    year: "2018",
  },
  {
    n: 2,
    title: "Sedentary behaviour and workplace health guidance",
    publisher: "British Journal of Sports Medicine",
    url: "https://bjsm.bmj.com",
    year: "2020",
  },
  {
    n: 3,
    title: "The truth about standing desks",
    publisher: "Harvard Health Publishing",
    url: "https://www.health.harvard.edu",
    year: "2023",
  },
  {
    n: 4,
    title: "Workplace ergonomics and seated work",
    publisher: "CDC · NIOSH",
    url: "https://www.cdc.gov/niosh",
    year: "2022",
  },
  {
    n: 5,
    title: "Work design, discomfort, and daylong attention",
    publisher: "American Psychological Association",
    url: "https://www.apa.org",
    year: "2021",
  },
  {
    n: 6,
    title: "Randomized trial: sit-stand desks and cognitive performance",
    publisher: "PubMed · NLM",
    url: "https://pubmed.ncbi.nlm.nih.gov",
    year: "2019",
  },
];

const TRAIL: { step: string; detail: string }[] = [
  { step: "Planned", detail: "3 steps · 12-source ceiling · Balanced depth" },
  { step: "Collected", detail: "12 sources fetched · 9 kept · 3 dropped" },
  { step: "Verified", detail: "2 claims softened · 1 claim dropped" },
];

const FEATURES: {
  icon: "quote" | "eye" | "download";
  title: string;
  text: string;
  href?: string;
  hrefLabel?: string;
}[] = [
  {
    icon: "quote",
    title: "Inline citations.",
    text: "Every claim carries its number, and every number leads to the passage it came from.",
  },
  {
    icon: "eye",
    title: "A trail you can widen.",
    text: "The evidence panel opens beside the answer — what was planned, fetched, kept, and dropped.",
  },
  {
    icon: "download",
    title: "Exports that keep the trail.",
    text: "Markdown and BibTeX exports carry the citations with them, so the record survives the copy-paste.",
    href: "/hogskin-sample-dossier.md",
    hrefLabel: "Download the sample (.md)",
  },
];

export default function DossierPage() {
  return (
    <div className="lp ds">
      <a className="skip-link" href="#ds-sample">
        Skip to the sample
      </a>
      <SiteNav />
      <main>
        <section className="ds-hero">
          <p className="lp-eyebrow lp-enter">A sample dossier</p>
          <h1 className="ds-title lp-enter" aria-label="What a finished run looks like.">
            {["What a finished run", "looks like."].map((line, lineIndex) => (
              <span key={lineIndex} className="ds-line">
                {[...line].map((char, charIndex) => {
                  const position = lineIndex * 19 + charIndex;
                  return (
                    <span
                      key={position}
                      className="lp-char"
                      aria-hidden="true"
                      style={{ "--d": `${120 + position * 32}ms` } as CSSProperties}
                    >
                      {char === " " ? "\u00A0" : char}
                    </span>
                  );
                })}
              </span>
            ))}
          </h1>
          <p className="ds-lead lp-enter">
            An illustrative example of the report layout. Its claims, sources,
            counts, and trail are sample content—not a live research run or
            independently verified findings.
          </p>
          <div className="ds-hero-actions lp-enter">
            <Link href="/research" className="lp-btn lp-btn-ink" data-magnetic>
              Run your own research
              <Icon name="arrow" size={16} />
            </Link>
            <Link href="/pricing" className="lp-btn lp-btn-paper">
              See the plans
            </Link>
          </div>
        </section>

        <section className="ds-stage" id="ds-sample" aria-label="Sample dossier">
          <span className="ds-peek" aria-hidden="true">
            <Critter kind="seal" pose="peek" size={72} delay={400} />
          </span>
          <article className="ds-report lp-enter">
            <header className="ds-report-head">
              <p className="ds-gate" role="note">
                Illustrative sample only. The example claims, source list,
                activity counts, and verification trail below are not from a
                live run and should not be treated as research evidence.
              </p>
              <div className="ds-meta">
                <Status status="complete" />
                <span>12 sources</span>
                <span aria-hidden="true">·</span>
                <span>9 follow-ups</span>
                <span aria-hidden="true">·</span>
                <span>7 min read</span>
              </div>
              <h2 className="ds-question">{QUESTION}</h2>
            </header>

            <div className="ds-body-grid">
              <div className="ds-article">
                {SECTIONS.map((section) => (
                  <section key={section.id} className="ds-section">
                    <h3>{section.heading}</h3>
                    {section.paras.map((para, index) => (
                      <p key={index}>{para}</p>
                    ))}
                  </section>
                ))}
              </div>

              <aside className="ds-trail" aria-label="What the run recorded">
                <h3>What the run recorded</h3>
                <ol>
                  {TRAIL.map((entry) => (
                    <li key={entry.step}>
                      <span className="ds-trail-step">{entry.step}</span>
                      <span className="ds-trail-detail">{entry.detail}</span>
                    </li>
                  ))}
                </ol>
                <p className="ds-trail-note">
                  Waiting for a plan approval pauses the clock — it never
                  spends active time.
                </p>
              </aside>
            </div>

            <section className="ds-sources" aria-label="Sources">
              <h3>Sources</h3>
              <ol>
                {SOURCES.map((source) => {
                  const href = safeUrl(source.url);
                  return (
                    <li key={source.n} id={`ds-source-${source.n}`}>
                      <span className="ds-source-n" aria-hidden="true">
                        {source.n}
                      </span>
                      <div>
                        {href ? (
                          <a href={href} target="_blank" rel="noreferrer">
                            {source.title}
                          </a>
                        ) : (
                          <span>{source.title}</span>
                        )}
                        <p>
                          {source.publisher} · {source.year}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
              <p className="ds-sources-note">
                This dossier is an illustrative sample. Sources link to the
                organizations' public pages, not to the exact passages a real
                run would quote.
              </p>
            </section>
          </article>
        </section>

        <section className="lp-section ds-features" aria-labelledby="ds-features-title">
          <header className="lp-section-head">
            <p className="lp-eyebrow">Standard on every run</p>
            <h2 id="ds-features-title">Every dossier ships with the trail.</h2>
          </header>
          <div className="ds-feature-grid">
            {FEATURES.map((feature) => (
              <div key={feature.title} className="ds-feature" data-spotlight>
                <span className="ds-feature-icon" aria-hidden="true">
                  <Icon name={feature.icon} size={18} />
                </span>
                <h3>{feature.title}</h3>
                <p>{feature.text}</p>
                {feature.href ? (
                  <a className="ds-download" href={feature.href} download>
                    <Icon name="download" size={14} />
                    <span>{feature.hrefLabel}</span>
                  </a>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="lp-closing">
          <div className="lp-closing-crew" aria-hidden="true">
            <Critter kind="folio" size={48} delay={200} />
            <Critter kind="seal" size={50} delay={900} />
          </div>
          <h2>Your question deserves this much paper trail.</h2>
          <p>Start with a free run and read the evidence yourself.</p>
          <div className="lp-hero-actions">
            <Link href="/research" className="lp-btn lp-btn-ink" data-magnetic>
              Open the workspace
            </Link>
            <Link href="/signup" className="lp-btn lp-btn-paper">
              Create an account
            </Link>
          </div>
        </section>
      </main>
      <SiteFooter />
      <LandingMotion />
      <CrewEyes />
    </div>
  );
}
