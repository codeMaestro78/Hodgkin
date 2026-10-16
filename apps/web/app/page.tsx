import Link from "next/link";
import { Fragment, type CSSProperties } from "react";
import { Icon } from "./components/ui";
import { LandingMotion } from "./components/landing-motion";
import { EvidenceField } from "./components/landing/evidence-field";
import { HeroConsole } from "./components/landing/hero-console";
import { PlanTile } from "./components/landing/plan-tile";
import { EvidenceTour } from "./components/landing/evidence-tour";
import {
  CitationOpen,
  ClaimGate,
  SpanMatch,
} from "./components/landing/verify-vignettes";
import { FaqThread } from "./components/landing/faq-thread";
import { SiteFooter, SiteNav } from "./components/landing/site-chrome";
import { SourceMarquee } from "./components/landing/source-marquee";
import { Critter } from "./components/crew/critter";
import { CrewEyes } from "./components/crew/crew-eyes";
import "./landing.css";

const TITLE = ["Research that", "shows its work."];

// Characters fade in from the middle of the headline outwards.
function bloomLines() {
  const total = TITLE.join(" ").length;
  let position = 0;
  return TITLE.map((line) =>
    line.split(" ").map((word) => {
      const chars = [...word].map((char) => {
        const distance = Math.abs(position - total / 2) / (total / 2);
        position += 1;
        return { char, delay: Math.round(120 + distance * 420) };
      });
      position += 1;
      return { word, chars };
    }),
  );
}

function BloomTitle() {
  return (
    <h1 className="lp-title" aria-label={TITLE.join(" ")}>
      {bloomLines().map((words, lineIndex) => (
        <span className="lp-title-line" key={lineIndex} aria-hidden="true">
          {words.map(({ word, chars }, wordIndex) => (
            <Fragment key={`${word}-${wordIndex}`}>
              {wordIndex > 0 && " "}
              <span className="lp-title-word">
                {chars.map(({ char, delay }, charIndex) => (
                  <span
                    key={charIndex}
                    className="lp-char"
                    style={{ "--d": `${delay}ms` } as CSSProperties}
                  >
                    {char}
                  </span>
                ))}
              </span>
            </Fragment>
          ))}
        </span>
      ))}
    </h1>
  );
}

const STEPS = [
  {
    title: "Plan, then wait for you",
    body: "Intake fixes the scope and the search budget. The planner splits the question into sub-questions sized to the depth you chose, then the run pauses, clock stopped, until you approve or edit the plan.",
    detail: ["intake", "planner", "approval_gate"],
  },
  {
    title: "Collect in parallel",
    body: "Each sub-question becomes its own research task. Tasks search and read side by side within the budget, and the reflector sends coverage gaps back to the planner while budget remains.",
    detail: ["research_worker", "reflector", "planner_delta"],
  },
  {
    title: "Check every quote",
    body: "Each claim draft carries the exact passage behind it. The verifier confirms the span exists in the source, then reviews whether it supports the claim. Anything less is excluded, and the exclusions are counted.",
    detail: ["verifier", "exact span", "supports only"],
  },
  {
    title: "Publish a fixed version",
    body: "The synthesizer writes sections for the depth you chose, key figures quoted verbatim, and a table of evidence by source. Published versions are immutable, so a shared link or export matches what you read.",
    detail: ["synthesizer", "key figures", "immutable version"],
  },
];

const STATEMENT =
  "An answer you can't trace is only an opinion. HogsKin keeps the whole trail: the plan it followed, the pages it read, and where every claim came from.";

export default function HomePage() {
  return (
    <div className="lp">
      <a className="skip-link" href="#introduction">
        Skip to introduction
      </a>
      <SiteNav />

      <main id="introduction">
        <section className="lp-hero">
          <div className="lp-field-wrap" aria-hidden="true">
            <EvidenceField />
          </div>
          <div className="lp-hero-copy">
            <BloomTitle />
            <p className="lp-hero-lead lp-enter">
              Ask a hard question. HogsKin plans the search, waits for your
              approval, reads sources in parallel, and publishes only the claims
              their quotes support.
            </p>
            <div className="lp-hero-actions lp-enter">
              <Link
                href="/research"
                className="lp-btn lp-btn-ink"
                data-magnetic
              >
                Start research
              </Link>
              <a href="#how" className="lp-btn lp-btn-paper">
                See how it works
              </a>
            </div>
          </div>
          <div className="lp-hero-stage lp-enter">
            <div className="lp-stage-inner">
              <div className="lp-perch" aria-hidden="true">
                <Critter kind="folio" size={58} className="lp-perch-a" />
                <Critter
                  kind="lens"
                  size={54}
                  className="lp-perch-b"
                  delay={700}
                />
                <Critter
                  kind="seal"
                  size={56}
                  className="lp-perch-c"
                  delay={1300}
                />
                <Critter
                  kind="quill"
                  size={52}
                  className="lp-perch-d"
                  delay={400}
                />
              </div>
              <HeroConsole />
            </div>
          </div>
        </section>

        <section className="lp-statement" aria-label="Why it matters">
          <p className="lp-scrub">
            {STATEMENT.split(" ").map((word, index) => (
              <span key={index}>{word} </span>
            ))}
          </p>
        </section>

        <section className="lp-sources" aria-labelledby="sources-title">
          <header className="lp-section-head">
            <h2 id="sources-title">Reads where the evidence lives.</h2>
            <p>
              Every run searches the open web and keeps what it read, from
              primary research to the reporting around it.
            </p>
          </header>
          <SourceMarquee />
        </section>

        <section className="lp-section" id="workspace">
          <header className="lp-section-head">
            <h2>A workspace for following a thought all the way through.</h2>
            <p>
              The answer is the start. Everything that led to it stays one click
              away.
            </p>
          </header>
          <div className="lp-gallery">
            <article className="lp-tile" data-reveal data-spotlight>
              <div className="lp-tile-visual">
                <div className="lp-depth" aria-hidden="true">
                  {[
                    ["Focused", "6 searches", "about 3 min"],
                    ["Balanced", "12 searches", "about 5 min"],
                    ["Deep", "20 searches", "about 10 min"],
                  ].map(([name, sources, time], index) => (
                    <div key={name} data-selected={index === 1}>
                      <strong>{name}</strong>
                      <span>{sources}</span>
                      <span>{time}</span>
                      <i />
                    </div>
                  ))}
                </div>
              </div>
              <h3>Set the scope before it starts.</h3>
              <p>
                Choose how far a run should reach. Focused for a quick brief,
                Deep for a broad investigation.
              </p>
            </article>
            <article className="lp-tile" data-reveal data-spotlight>
              <div className="lp-tile-visual">
                <PlanTile />
              </div>
              <h3>Watch the plan take shape.</h3>
              <p>
                The research plan, the searches, and the reading are visible
                while they happen, not hidden behind a spinner.
              </p>
            </article>
            <article className="lp-tile" data-reveal data-spotlight>
              <div className="lp-tile-visual">
                <div className="lp-claim" aria-hidden="true">
                  <p>
                    Rated figures tend to be optimistic, so independent field
                    data is the better guide
                    <sup className="lp-cite">3</sup>.
                  </p>
                  <div className="lp-claim-card">
                    <span className="lp-source-index">3</span>
                    <div>
                      <strong>Rated capacity at low temperatures</strong>
                      <small>
                        &ldquo;Measured output at the coldest sites often fell
                        below the rated figure.&rdquo;
                      </small>
                    </div>
                  </div>
                </div>
              </div>
              <h3>Check any claim in place.</h3>
              <p>
                Citations sit inside the answer. Open one to read the passage
                behind it without losing your place.
              </p>
            </article>
            <article className="lp-tile" data-reveal data-spotlight>
              <div className="lp-tile-visual">
                <div className="lp-compare" aria-hidden="true">
                  {[
                    ["Heat pumps in cold climates", "Balanced", "11 sources"],
                    ["Heat pumps vs. gas boilers", "Deep", "18 sources"],
                  ].map(([title, depth, sources]) => (
                    <div key={title}>
                      <strong>{title}</strong>
                      <span>
                        {depth}
                        <i />
                        {sources}
                      </span>
                      <b />
                      <b />
                      <b />
                    </div>
                  ))}
                  <span className="lp-compare-mark">
                    <Icon name="columns" size={16} />
                  </span>
                </div>
              </div>
              <h3>Keep, compare, and revisit.</h3>
              <p>
                Save runs to your library, put two side by side, export a PDF,
                or schedule a question to run again.
              </p>
            </article>
          </div>
        </section>

        <section className="lp-section lp-method" id="how">
          <div className="lp-method-intro">
            <h2>How a run actually works.</h2>
            <p>
              Seven graph nodes and one evidence gate. Every step leaves a
              record you can open afterwards.
            </p>
            <Link href="/research" className="lp-btn lp-btn-paper">
              Try a question
            </Link>
          </div>
          <ol className="lp-steps">
            <li className="lp-steps-trace" aria-hidden="true">
              <i />
              <b />
            </li>
            {STEPS.map((step, index) => (
              <li
                key={step.title}
                className="lp-step"
                data-reveal
                style={{ "--i": index } as CSSProperties}
              >
                <div className="lp-step-card">
                  <span className="lp-step-index" aria-hidden="true">
                    {index + 1}
                  </span>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                  <div className="lp-step-trail" aria-hidden="true">
                    {step.detail.map((item) => (
                      <span key={item}>{item}</span>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <div className="lp-band">
          <div className="lp-band-glow" aria-hidden="true" />
          <section
            className="lp-section lp-verify"
            id="verify"
            aria-labelledby="verify-title"
          >
            <header className="lp-section-head">
              <p className="lp-eyebrow">How we verify</p>
              <h2 id="verify-title">
                Nothing reaches the answer without its passage.
              </h2>
              <p>
                The verifier runs after collection and before a word is written.
                It applies the same three rules to every claim.
              </p>
            </header>
            <div className="lp-verify-grid">
              <article className="lp-tile" data-reveal data-spotlight>
                <div className="lp-tile-visual">
                  <SpanMatch />
                </div>
                <span className="lp-verify-rule">Rule 1</span>
                <h3>Quotes are matched word for word.</h3>
                <p>
                  Each claim draft carries the passage it came from. If that
                  exact span is not in the retrieved text, the claim stops here.
                </p>
              </article>
              <article className="lp-tile" data-reveal data-spotlight>
                <div className="lp-tile-visual">
                  <ClaimGate />
                </div>
                <span className="lp-verify-rule">Rule 2</span>
                <h3>Only support is published.</h3>
                <p>
                  A review rates every matched quote. Partial support,
                  contradiction, and off-topic quotes are excluded, and counted.
                </p>
              </article>
              <article
                className="lp-tile lp-verify-wide"
                data-reveal
                data-spotlight
              >
                <div className="lp-tile-visual">
                  <CitationOpen />
                </div>
                <div className="lp-verify-copy">
                  <span className="lp-verify-rule">Rule 3</span>
                  <h3>Every citation opens its passage.</h3>
                  <p>
                    Citations stay glued to the words they support. Open one to
                    see the source, the matched quote, and the review without
                    losing your place.
                  </p>
                </div>
              </article>
            </div>
          </section>

          <section
            className="lp-section lp-desk"
            id="evidence"
            aria-labelledby="evidence-title"
          >
            <header className="lp-section-head">
              <p className="lp-eyebrow">Beside every answer</p>
              <h2 id="evidence-title">The evidence stays on the record.</h2>
              <p>
                Each report keeps a panel you can widen, narrow, or hide. Three
                views, all built from what the run actually recorded.
              </p>
            </header>
            <EvidenceTour />
          </section>
        </div>

        <section className="lp-section lp-faq" id="questions">
          <header className="lp-section-head">
            <h2>Questions, answered with sources of their own.</h2>
            <p>The short version of how HogsKin works.</p>
          </header>
          <div className="lp-faq-stage">
            <FaqThread />
            <span className="lp-peek-slot" aria-hidden="true">
              <Critter kind="lens" pose="peek" size={76} delay={300} />
            </span>
          </div>
        </section>

        <section className="lp-closing">
          <div className="lp-closing-crew" aria-hidden="true">
            <Critter kind="quill" size={48} delay={200} />
            <Critter kind="seal" size={50} delay={900} />
            <Critter kind="folio" size={52} delay={500} />
          </div>
          <h2>Your next question deserves a better answer.</h2>
          <p>Make space for a more considered perspective.</p>
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
