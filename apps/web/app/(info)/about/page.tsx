import type { Metadata } from "next";

import { ActionLink, Icon } from "../../components/ui";
import { Critter } from "../../components/crew/critter";
import "./about.css";

export const metadata: Metadata = {
  title: "About · HogsKin",
  description:
    "Why HogsKin is built around the trail instead of the answer: the principles, the pipeline, and the things we won't pretend.",
};

/*
 * The pipeline copy is condensed from the landing page's STEPS — the real
 * intake → planner → workers → verifier → synthesizer chain, described the
 * same way everywhere it is named.
 */
const PIPELINE = [
  {
    step: "01",
    name: "Plan, then wait for you",
    body: "Intake fixes the scope and the search budget. The planner splits the question into sub-questions sized to the depth you chose, then the run pauses, clock stopped, until you approve or edit the plan.",
  },
  {
    step: "02",
    name: "Collect in parallel",
    body: "Each sub-question becomes its own research task. Tasks search and read side by side within the budget, and the reflector sends coverage gaps back to the planner while budget remains.",
  },
  {
    step: "03",
    name: "Check every quote",
    body: "Each claim draft carries the exact passage behind it. The verifier confirms the span exists in the source, then reviews whether it supports the claim. Anything less is excluded, and the exclusions are counted.",
  },
  {
    step: "04",
    name: "Publish a fixed version",
    body: "The synthesizer writes sections for the depth you chose, key figures quoted verbatim, and a table of evidence by source. Published versions are immutable, so a shared link or export matches what you read.",
  },
];

/*
 * The crewCopy matches the personalities declared on the critter components
 * themselves — folio keeps the notes, lens looks closer, seal leans on
 * verdicts, quill wants to write. Nothing invented here.
 */
const CREW = [
  {
    kind: "folio" as const,
    name: "Folio",
    line: "A folded research page. Calm; it keeps the notes.",
    delay: 200,
  },
  {
    kind: "lens" as const,
    name: "Lens",
    line: "A magnifying lens. Curious; always looking closer.",
    delay: 500,
  },
  {
    kind: "seal" as const,
    name: "Seal",
    line: "A diamond seal. Particular about whether a claim checks out.",
    delay: 800,
  },
  {
    kind: "quill" as const,
    name: "Quill",
    line: "A tall quill. Restless; it wants to write the answer.",
    delay: 1100,
  },
];

const PRINCIPLES = [
  {
    icon: "quote" as const,
    title: "Sources first.",
    body: "Every claim in a report carries a number, every number leads to the passage behind it, and the methodology view records the searches the run actually made. The trail is the product, not the footnote.",
  },
  {
    icon: "clock" as const,
    title: "Limits are features.",
    body: "A run states how far it can go before it starts: Focused reads up to 6 sources in 3 active minutes, Balanced 12 in 5, Deep 20 in 10. Waiting for your approval pauses the clock — it never spends it.",
  },
  {
    icon: "eye" as const,
    title: "Verification is a step.",
    body: "Claims are checked against the passages that support them before you ever read the report. Weak ones get softened; some get dropped. The counts end up in the verification trail — a report that hides its gaps is an ad, not an answer.",
  },
  {
    icon: "link" as const,
    title: "You keep the keys.",
    body: "Questions, library items, shared links: yours to keep, to organize, to revoke, to delete. Questions you type stay in your browser until you start a run; nothing is sold and nothing is advertised.",
  },
];

export default function AboutPage() {
  return (
    <div className="ab">
      <section className="lg-hero">
        <p className="lp-eyebrow lp-enter">Why we show our work</p>
        <h1 className="lg-title lp-enter" data-critter="perch">
          Answers are cheap.
          <br />
          <span className="ab-accent">Receipts aren&rsquo;t.</span>
        </h1>
        <p className="lg-lead lp-enter">
          HogsKin exists for a habit most people already have and few tools
          honored: asking where an answer came from. We built the product
          around the trail instead of the answer — the plan a run followed, the
          pages it read, and the claim-by-claim record of what held up.
        </p>
        <div className="ab-jump lp-enter" role="list">
          <a href="#principles" role="listitem">
            <Icon name="quote" size={13} /> Principles
          </a>
          <a href="#pipeline" role="listitem">
            <Icon name="layers" size={13} /> The pipeline
          </a>
          <a href="#honesty" role="listitem">
            <Icon name="eye" size={13} /> What we won&rsquo;t pretend
          </a>
          <a href="#crew" role="listitem">
            <Icon name="spark" size={13} /> The crew
          </a>
        </div>
      </section>

      <section className="lg-section" id="principles">
        <h2 className="ab-h2">Four principles, each enforceable.</h2>
        <p className="lg-muted">
          Nothing on this page is a value statement we can&rsquo;t point at in
          the product. Each principle names the thing you can check.
        </p>
        <div className="ab-principles">
          {PRINCIPLES.map((item) => (
            <article
              className="ab-principle"
              data-critter="spotlight"
              key={item.title}
            >
              <span className="ab-principle-icon" aria-hidden="true">
                <Icon name={item.icon} size={18} />
              </span>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lg-section" id="pipeline">
        <h2 className="ab-h2">How a run keeps its trail.</h2>
        <p className="lg-muted">
          The same four steps every time, whether the question took three
          minutes or ten. This is the literal pipeline — the same names the
          workspace shows while a run is in flight.
        </p>
        <div className="ab-pipeline">
          {PIPELINE.map((stage) => (
            <article className="ab-stage" data-critter="spotlight" key={stage.step}>
              <span className="ab-stage-n" aria-hidden="true">
                {stage.step}
              </span>
              <h3>{stage.name}</h3>
              <p>{stage.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lg-sheet" id="honesty">
        <h2 className="ab-h2">What we won&rsquo;t pretend.</h2>
        <div className="ab-prose">
          <p>
            A report can still be wrong. The machine here drafts, checks, and
            quotes — and it fails the way careless researchers do:
            confidently, occasionally, and in ways a citation exposes. The
            point of the trail is not perfection. It is the ability to tell.
          </p>
          <p>
            Nothing in a report is professional advice. The verification trail
            shows what was checked; the research-gaps section states plainly
            what wasn&rsquo;t. Read the sources. For the stakes that need
            credentials, talk to people who hold them.
          </p>
          <p>
            Sources stay theirs. Citations point at third-party pages, and the
            material you open there obeys their terms, not ours.
          </p>
        </div>
      </section>

      <section className="lg-section" id="crew">
        <h2 className="ab-h2">The crew.</h2>
        <p className="lg-muted">
          The site is staffed. Four small characters keep watch while you read
          — their personalities are the review process in miniature.
        </p>
        <div className="ab-crew">
          {CREW.map((member) => (
            <article
              className="ab-member"
              data-critter="spotlight"
              key={member.name}
            >
              <span className="ab-member-figure" aria-hidden="true">
                <Critter
                  kind={member.kind}
                  size={56}
                  delay={member.delay}
                />
              </span>
              <h3>{member.name}</h3>
              <p>{member.line}</p>
            </article>
          ))}
        </div>
        <p className="lg-muted ab-crew-note">
          They hop while you read, and hold still entirely when your system
          asks for reduced motion.
        </p>
      </section>

      <div className="lg-end">
        <p>Curiosity, with a paper trail.</p>
        <div className="ab-end-links">
          <ActionLink href="/research">Open the workspace</ActionLink>
          <ActionLink href="/dossier" secondary>
            See a sample dossier first
          </ActionLink>
        </div>
      </div>
    </div>
  );
}
