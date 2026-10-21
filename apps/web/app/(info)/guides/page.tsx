import type { Metadata } from "next";

import { ActionLink, Icon } from "../../components/ui";
import "./guides.css";

export const metadata: Metadata = {
  title: "Guides · HogsKin",
  description:
    "Four short manuals drawn from how HogsKin actually works: ask the question well, pick the depth, read the trail, and keep what you learn.",
};

const JUMP = [
  { href: "#ask", label: "Ask the question well", icon: "search" as const },
  { href: "#depth", label: "Pick the depth", icon: "layers" as const },
  { href: "#trail", label: "Read the trail", icon: "eye" as const },
  { href: "#keep", label: "Keep what you learn", icon: "folder" as const },
];

/*
 * Ceilings copied from the depth cards (lib/research-draft.ts): Focused
 * 6 sources / 6 provider operations / 4 active minutes; Balanced 12/12/5;
 * Deep 20/20/10. Deep's plan gate is real (lib/run-status.ts).
 */
const DEPTHS = [
  {
    name: "Focused",
    sources: "6 sources",
    operations: "6 operations",
    minutes: "4 active minutes",
    read: "A first read. When you want the shape of an answer more than the argument.",
    units: "1 unit",
  },
  {
    name: "Balanced",
    sources: "12 sources",
    operations: "12 operations",
    minutes: "5 active minutes",
    read: "Most decisions. Enough width to catch disagreement between sources.",
    units: "2 units",
  },
  {
    name: "Deep",
    sources: "20 sources",
    operations: "20 operations",
    minutes: "10 active minutes",
    read: "Contested questions, claims that fight each other, and stakes worth the wait.",
    units: "4 units · Investigator plan",
  },
];

/*
 * The evidence-panel blurb titles are verbatim from the real panel cards
 * (evidence-tour.tsx TABS): what the run shows you, in its own words.
 */
const PANEL = [
  {
    tab: "Sources",
    kicker: "Evidence",
    title: "Every source, with the passage it gave.",
    line: "What was read, where it came from, the extract quoted in the answer, and whether it was cited or only collected.",
  },
  {
    tab: "Methodology",
    kicker: "Process",
    title: "The plan and every step that ran.",
    line: "The approved plan, the searches behind each sub-question, coverage loops, and how long each step took. Recorded actions, not private reasoning.",
  },
  {
    tab: "Checks",
    kicker: "Verdicts",
    title: "Each claim, its span, and its verdict.",
    line: "Whether each quote matched exactly, and whether it supports the claim. Excluded claims stay listed with the reason.",
  },
];

const WEAK_STRONG = [
  {
    weak: "Best standing desks",
    strong: "Do standing desks measurably improve focus at work?",
    why: "A question, not a shopping query — the answer keeps its receipts in the sample dossier.",
  },
  {
    weak: "Is AI overrated?",
    strong:
      "What measured productivity effects are documented for AI coding assistants?",
    why: "Asks for measurements a source can actually record.",
  },
  {
    weak: "Everything about solar",
    strong:
      "What do utilities disclose about residential solar payback periods?",
    why: "Scoped to what public filings can answer.",
  },
];

export default function GuidesPage() {
  return (
    <div className="gd">
      <section className="lg-hero">
        <p className="lp-eyebrow lp-enter">Practice, documented</p>
        <h1 className="lg-title lp-enter">
          Guides<span className="gd-period">.</span>
        </h1>
        <p className="lg-lead lp-enter">
          The manuals for running better research here — drawn from how the
          product actually works, not how we wish it did. Four short reads, each
          one about a habit you can practice on the next run.
        </p>
        <div className="gd-jump lp-enter" role="list">
          {JUMP.map((item) => (
            <a href={item.href} key={item.href} role="listitem">
              <Icon name={item.icon} size={13} /> {item.label}
            </a>
          ))}
        </div>
      </section>

      <section className="lg-sheet gd-guide" id="ask">
        <p className="gd-kicker">Guide 1</p>
        <h2>Ask the question well.</h2>
        <p className="gd-lead">
          The composer starts almost empty on purpose. The field only hints at
          what fits: &ldquo;Ask a question, compare alternatives, or investigate
          a decision…&rdquo; — three reportable shapes, and the rules for asking
          them well are the same.
        </p>
        <div className="gd-table-wrap">
          <table className="gd-table">
            <thead>
              <tr>
                <th scope="col">Weak ask</th>
                <th scope="col">Strong ask</th>
                <th scope="col">Why</th>
              </tr>
            </thead>
            <tbody>
              {WEAK_STRONG.map((row) => (
                <tr key={row.weak}>
                  <td className="gd-weak">{row.weak}</td>
                  <td className="gd-strong">{row.strong}</td>
                  <td className="gd-why">{row.why}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="gd-body">
          The pattern: point at something <em>checkable</em>. Questions that ask
          for measurements, disclosures, or documented decisions give a run
          something to quote. The requirements field then steers the
          report&rsquo;s shape — one requirement per line, up to 20 requirements
          and 500 characters each:
        </p>
        <aside className="gd-callout">
          <p>
            <strong>Tell it what to privilege, not what to find.</strong>
          </p>
          <p className="gd-mono">Prefer primary studies over commentary.</p>
          <p className="gd-mono">
            Flag disagreements between sources and name them.
          </p>
        </aside>
        <p className="gd-note">
          While you type, a counter counts the question&rsquo;s characters
          (1,000 is the ceiling) and unsent drafts stay in your browser&rsquo;s
          session storage, per account — nothing merely typed is sent anywhere.
        </p>
      </section>

      <section className="lg-sheet gd-guide" id="depth">
        <p className="gd-kicker">Guide 2</p>
        <h2>Pick the depth.</h2>
        <p className="gd-lead">
          Depth is the search budget: how many sources the run may read, how
          many operations it may spend reading them, and how many active minutes
          it gets. The numbers below are the ceilings a run states before it
          starts — not vague adjectives.
        </p>
        <div className="gd-depths">
          {DEPTHS.map((depth) => (
            <article className="gd-depth" key={depth.name}>
              <header>
                <h3>{depth.name}</h3>
                {depth.units.includes("Investigator") ? (
                  <span className="gd-depth-flag">Investigator plan</span>
                ) : null}
              </header>
              <ul className="gd-depth-ceils">
                <li>
                  <Icon name="book" size={14} /> {depth.sources}
                </li>
                <li>
                  <Icon name="sliders" size={14} /> {depth.operations}
                </li>
                <li>
                  <Icon name="clock" size={14} /> {depth.minutes}
                </li>
              </ul>
              <p>{depth.read}</p>
              <span className="gd-depth-units">{depth.units}</span>
            </article>
          ))}
        </div>
        <p className="gd-body">Two budget notes that trip people up:</p>
        <ul className="gd-list">
          <li>
            <strong>Approval pauses the clock, never spends it.</strong> A run
            waits — with active time stopped — until you approve its plan (that
            checkbox is on by default). Unchecking it lets the run proceed
            without the pause.
          </li>
          <li>
            <strong>Depths cost units on paid plans.</strong> Focused, Balanced,
            and Deep draw from a monthly allowance of units — one, two, and four
            respectively. The Free plan runs Focused and Balanced; Deep unlocks
            with the Investigator plan.
          </li>
        </ul>
      </section>

      <section className="lg-sheet gd-guide" id="trail">
        <p className="gd-kicker">Guide 3</p>
        <h2>Read the trail.</h2>
        <p className="gd-lead">
          A finished report grades itself before you read a word. Start at the
          top, then work outward:
        </p>
        <ol className="gd-steps">
          <li>
            <strong>Check the claim gate.</strong> &ldquo;Answer assessed&rdquo;
            or &ldquo;Partial answer&rdquo; tells you how the run judged its own
            coverage before publishing.
          </li>
          <li>
            <strong>Read the overview strip.</strong> Evidence collected,
            questions explored, and reading time — the shape of the run in one
            row.
          </li>
          <li>
            <strong>Follow an inline citation.</strong> Chips sit beside the
            claims they back; opening one shows the passage from the source
            without leaving the report.
          </li>
          <li>
            <strong>Open the evidence panel.</strong> Widen, narrow, or hide it.
            Three views — built from what the run actually recorded:
          </li>
        </ol>
        <div className="gd-panel">
          {PANEL.map((view) => (
            <article key={view.tab}>
              <p className="gd-panel-kicker">{view.kicker}</p>
              <h3>{view.tab}</h3>
              <p className="gd-panel-title">{view.title}</p>
              <p className="gd-panel-line">{view.line}</p>
            </article>
          ))}
        </div>
        <p className="gd-body">
          The verification trail sits beside the report: how many sources were
          fetched, kept, and dropped, and how many claims got softened or
          dropped before you ever read them. When two runs disagree, compare
          them side by side — same question, different depth makes short work of
          deciding which answer earned its confidence.
        </p>
        <aside className="gd-callout">
          <p>
            <strong>Exports keep the trail too.</strong> A Markdown export
            carries every heading, quote, and citation; the BibTeX export lists
            the sources for your bibliography. The published version is fixed —
            an export or shared link shows exactly what you read.
          </p>
        </aside>
      </section>

      <section className="lg-sheet gd-guide" id="keep">
        <p className="gd-kicker">Guide 4</p>
        <h2>Keep what you learn.</h2>
        <p className="gd-lead">
          Runs stay in your history; what matters graduates.
        </p>
        <ul className="gd-list">
          <li>
            <strong>Library.</strong> Save the runs worth returning to. Revisit
            them, organize them, or remove them — the library is yours to sort.
          </li>
          <li>
            <strong>Share links.</strong> Publish a read-only link to a finished
            run and revoke it whenever you like. Treat it like a key you handed
            someone — the run itself is immutable, so what they see is what you
            saw.
          </li>
          <li>
            <strong>Automation.</strong> Queue a batch of questions, or repeat
            one on a schedule — no closer than every 60 minutes. A run scheduled
            is still a run governed by the same approval step.
          </li>
          <li>
            <strong>Compare.</strong> Park two finished runs side by side and
            read the disagreement — the fastest way to see which answer earned
            its confidence.
          </li>
        </ul>
        <div className="gd-end-links">
          <ActionLink href="/research">Run your first question</ActionLink>
          <ActionLink href="/dossier" secondary>
            See a finished run first
          </ActionLink>
        </div>
      </section>

      <div className="lg-end">
        <p>
          Read these once and the product is yours. Everything else is at the
          questions.
        </p>
      </div>
    </div>
  );
}
