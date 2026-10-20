import type { Metadata } from "next";
import { ActionLink } from "../../components/ui";

export const metadata: Metadata = {
  title: "Terms of Service · HogsKin",
  description:
    "The agreement for using HogsKin — accounts, plans, reports, and what the service does and doesn't promise.",
};

type Block = { kind: "p" | "ul"; text?: string; items?: string[] };
type Section = { id: string; heading: string; blocks: Block[] };

const UPDATED = "October 19, 2026";

const SECTIONS: Section[] = [
  {
    id: "the-service",
    heading: "What HogsKin does.",
    blocks: [
      {
        kind: "p",
        text: "HogsKin runs research for a question you ask. It plans the work, reads public web sources, and writes a cited report you can keep in your library, compare across runs, share, and export. Every report keeps its trail: the sources behind each claim stay one click away.",
      },
      {
        kind: "p",
        text: "Runs use one of three depths — Focused, Balanced, and Deep — each with its own ceilings on sources, provider operations, and active time. Waiting for your approval on a plan pauses the clock rather than burning it.",
      },
    ],
  },
  {
    id: "accounts",
    heading: "Your account.",
    blocks: [
      {
        kind: "p",
        text: "Accounts are handled by Supabase: you sign up with an email address and a password, or with Google. You are responsible for the activity that happens on your account and for keeping your credentials safe. Use an email address you actually check — security and billing notices go there.",
      },
      {
        kind: "p",
        text: "You must be at least 13 years old to use HogsKin, old enough to form a binding contract where you live, or using it under the supervision of someone who is.",
      },
    ],
  },
  {
    id: "promises",
    heading: "What the service does and doesn't promise.",
    blocks: [
      {
        kind: "p",
        text: "Reports are produced with the help of language models and public web sources. They can be incomplete, out of date, or simply wrong — a citation is a pointer, not a proof. HogsKin shows the trail so you can verify what matters before you rely on it.",
      },
      {
        kind: "p",
        text: "Nothing on the platform is legal, medical, financial, or other professional advice, and you should not treat it as such. The service tries hard and still fails sometimes: runs can miss sources, misread a passage, or time out. Deep mode is gated to the Investigator plan because it costs the most to run, not because it is never wrong.",
      },
    ],
  },
  {
    id: "acceptable-use",
    heading: "How you may use HogsKin.",
    blocks: [
      {
        kind: "ul",
        items: [
          "Use it for real questions, on your own account, within the limits of your plan.",
          "Don't scrape, resell, or automate access outside the features we provide. Scheduled runs and batches are part of the product; abusive request floods are not.",
          "Don't use the service to break the law or anyone else's rights.",
          "Respect the sources: third-party material stays under its own rights and terms.",
        ],
      },
    ],
  },
  {
    id: "plans-billing",
    heading: "Plans, units, and billing.",
    blocks: [
      {
        kind: "p",
        text: "HogsKin has three plans — Free, Scholar, and Investigator. Free requires no card. Paid plans are billed through Stripe, and checkout opens only when billing is live; the buttons on the pricing page show whether it is.",
      },
      {
        kind: "p",
        text: "Proposed unit allowances — 5, 20, and 40 units a month, with Focused costing 1 unit, Balanced 2, and Deep 4 — remain provisional until cost validation is complete. Existing reports and sources stay available regardless of future plan changes.",
      },
    ],
  },
  {
    id: "your-content",
    heading: "Your questions and your library.",
    blocks: [
      {
        kind: "p",
        text: "You keep the rights to the questions, requirements, and notes you bring. You give us a limited license to process them — to run research, store your reports and library items, and make the features you use work. You can delete runs and library items from the workspace, and deleting them removes them from it.",
      },
    ],
  },
  {
    id: "reports-sources",
    heading: "Reports, citations, and third-party sources.",
    blocks: [
      {
        kind: "p",
        text: "A report is yours to use, including the exports we produce for you. The sources it cites are not: material from publishers, journals, and websites remains under their own rights. Citations point at sources so you can read them in context — they do not grant you the content itself.",
      },
    ],
  },
  {
    id: "sharing",
    heading: "Share links.",
    blocks: [
      {
        kind: "p",
        text: "Share links are read-only and revocable. Anyone with the link can read that report until you revoke it, so treat a share link like a key you handed someone. Revoking takes effect immediately.",
      },
    ],
  },
  {
    id: "availability",
    heading: "Availability and changes.",
    blocks: [
      {
        kind: "p",
        text: "The service runs on limits — per-run ceilings on sources, provider operations, and active time — and it may change, pause, or discontinue features as the product evolves. We aim to tell you before breaking changes, but research features in development may shift without much ceremony.",
      },
    ],
  },
  {
    id: "suspension",
    heading: "Suspension and termination.",
    blocks: [
      {
        kind: "p",
        text: "We can suspend or close an account for abuse, unlawful use, or non-payment where billing applies. You can stop using HogsKin at any time. When an account closes, we keep the minimum records the law requires and drop the rest.",
      },
    ],
  },
  {
    id: "disclaimers",
    heading: "Disclaimers and liability.",
    blocks: [
      {
        kind: "p",
        text: "The service is provided as is, without warranties of any kind, to the extent the law allows. To the maximum extent permitted by law, HogsKin is not liable for indirect or consequential damages, and our total liability for any claim is capped at what you paid us in the twelve months before it. Some places don't allow these limits; there, they apply only as far as the law permits.",
      },
    ],
  },
  {
    id: "changes",
    heading: "Changes to these terms.",
    blocks: [
      {
        kind: "p",
        text: "We may update these terms as the product changes. When we do, we change the date above and, for significant changes, we try to tell you in the product first. Continuing to use HogsKin after a change means you accept the updated terms.",
      },
    ],
  },
  {
    id: "contact",
    heading: "Contact.",
    blocks: [
      {
        kind: "p",
        text: "Questions about these terms? Write to support@hogskin.com and a person will read it.",
      },
    ],
  },
];

export default function TermsPage() {
  return (
    <>
      <header className="lg-hero">
        <p className="lp-eyebrow lp-enter">The fine print, in plain sight</p>
        <h1 className="lg-title lp-enter">Terms of Service.</h1>
        <p className="lg-lead lp-enter">
          HogsKin is a research tool that shows its work. These terms explain
          the deal between you and us — in plain English, because a terms page
          nobody can read protects nobody.
        </p>
        <p className="lg-updated lp-enter">
          <i aria-hidden="true" />
          Last updated {UPDATED}
        </p>
      </header>

      <div className="lg-sheet lp-enter">
        <ol className="lg-toc">
          {SECTIONS.map((section) => (
            <li key={section.id}>
              <a href={`#${section.id}`}>{section.heading}</a>
            </li>
          ))}
        </ol>
        {SECTIONS.map((section) => (
          <section key={section.id} className="lg-section" id={section.id}>
            <h2>{section.heading}</h2>
            {section.blocks.map((block, index) =>
              block.kind === "p" ? (
                <p key={index}>{block.text}</p>
              ) : (
                <ul key={index}>
                  {block.items?.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ),
            )}
          </section>
        ))}
      </div>

      <div className="lg-end">
        <p>Read something that doesn't match the product? Tell us — it helps.</p>
        <ActionLink href="/">Back to the front page</ActionLink>
      </div>
    </>
  );
}
