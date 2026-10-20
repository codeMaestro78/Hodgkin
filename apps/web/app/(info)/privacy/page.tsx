import type { Metadata } from "next";
import { ActionLink } from "../../components/ui";

export const metadata: Metadata = {
  title: "Privacy Policy · HogsKin",
  description:
    "What HogsKin collects, what stays on your device, and the services we rely on to run research.",
};

type Block = { kind: "p" | "ul"; text?: string; items?: string[] };
type Section = { id: string; heading: string; blocks: Block[] };

const UPDATED = "October 19, 2026";

const SECTIONS: Section[] = [
  {
    id: "summary",
    heading: "The short version.",
    blocks: [
      {
        kind: "ul",
        items: [
          "We collect what the product needs to work: an account, your research, and the reports you keep.",
          "Your in-progress drafts never leave your device.",
          "No ad trackers, no data selling — ever.",
          "Research runs send your question to web search and language-model services, and every report cites what it used.",
          "You can delete runs, library items, and your account at any time.",
        ],
      },
    ],
  },
  {
    id: "collect",
    heading: "What we collect.",
    blocks: [
      {
        kind: "ul",
        items: [
          "Account basics: your email address and authentication identifiers, plus the preferences you set during onboarding.",
          "Research content: your questions, report requirements, runs, plans, reports, library items, projects, schedules, and batches.",
          "Billing: checkout session identifiers through Stripe when billing is live. Card numbers go to Stripe, not to us.",
          "Technical records: request logs and error diagnostics needed to run and debug the service.",
        ],
      },
    ],
  },
  {
    id: "on-device",
    heading: "What stays on your device.",
    blocks: [
      {
        kind: "p",
        text: "The composer draft — the question and requirements you are still typing — is kept in your browser's sessionStorage under a per-account key. It never leaves the device in that form, and it disappears when the tab session ends. Nothing you merely type is transmitted until you start a run.",
      },
    ],
  },
  {
    id: "use",
    heading: "How your information is used.",
    blocks: [
      {
        kind: "ul",
        items: [
          "To run research and produce the reports you asked for.",
          "To keep your history, library, comparisons, and automation working.",
          "To honor the approvals and schedules you set up.",
          "To keep the service reliable and debug it when it isn't.",
          "To handle billing, once billing is live.",
        ],
      },
    ],
  },
  {
    id: "research-processing",
    heading: "How a research run works.",
    blocks: [
      {
        kind: "p",
        text: "When you start a run, your question and requirements go to our research service. It plans the work, searches the public web — currently using Tavily — reads what it finds, and drafts a cited report with the help of language models. Ceilings on sources, provider operations, and active time cap how far a run can go.",
      },
      {
        kind: "p",
        text: "If you ask to review the plan first, the run pauses at the plan until you approve it. Approval waits on you, not on a timer.",
      },
    ],
  },
  {
    id: "third-parties",
    heading: "Services we rely on.",
    blocks: [
      {
        kind: "ul",
        items: [
          "Supabase — accounts, authentication, and the database behind your workspace.",
          "Stripe — payments when checkout is live.",
          "Tavily — public web search during runs.",
          "Language-model services — the drafting and verification steps of a run.",
        ],
      },
      {
        kind: "p",
        text: "Each of these processes data under its own terms. We send them what the feature needs and no more.",
      },
    ],
  },
  {
    id: "cookies",
    heading: "Cookies and local storage.",
    blocks: [
      {
        kind: "p",
        text: "Signing in sets authentication cookies so the app knows it is you — they are functional, not advertising. The composer draft lives in your browser's sessionStorage, on your device only. We don't run ad trackers and we don't buy or sell behavioral analytics.",
      },
    ],
  },
  {
    id: "sharing",
    heading: "Sharing and disclosure.",
    blocks: [
      {
        kind: "p",
        text: "Your research is not sold and is not used to advertise. Reports leave the platform only when you create a read-only share link or export one — and share links can be revoked the moment you change your mind. We disclose data only when the law requires it or to the providers above, to run the service you asked for.",
      },
    ],
  },
  {
    id: "retention",
    heading: "How long we keep things.",
    blocks: [
      {
        kind: "p",
        text: "Reports, library items, schedules, and share links stay until you delete them. Deleting removes them from your workspace. Closing your account removes your research content; we may keep the minimal records the law requires. Technical logs age out on a short rotation.",
      },
    ],
  },
  {
    id: "choices",
    heading: "Your choices.",
    blocks: [
      {
        kind: "ul",
        items: [
          "Delete individual runs and library items from the workspace.",
          "Revoke share links at any time.",
          "Close your account and take your research content with it.",
          "Ask questions about any of this — the contact below reaches a person.",
        ],
      },
    ],
  },
  {
    id: "children",
    heading: "Children.",
    blocks: [
      {
        kind: "p",
        text: "HogsKin is not directed at children under 13, and we don't knowingly collect their data. If you believe a child's account exists, tell us and we will remove it.",
      },
    ],
  },
  {
    id: "changes",
    heading: "Changes to this policy.",
    blocks: [
      {
        kind: "p",
        text: "We update the date above whenever this policy changes, and we describe material changes in the product before they take effect.",
      },
    ],
  },
  {
    id: "contact",
    heading: "Contact.",
    blocks: [
      {
        kind: "p",
        text: "Privacy questions, deletions, or anything else: support@hogskin.com.",
      },
    ],
  },
];

export default function PrivacyPage() {
  return (
    <>
      <header className="lg-hero">
        <p className="lp-eyebrow lp-enter">Your research belongs to you</p>
        <h1 className="lg-title lp-enter">Privacy Policy.</h1>
        <p className="lg-lead lp-enter">
          We collect what the product needs to work and nothing we can sell.
          This page says what that means in practice — what we hold, what stays
          on your device, and who helps us run a run.
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
        <p>This policy describes the product as it works today, not as we wish it did.</p>
        <ActionLink href="/">Back to the front page</ActionLink>
      </div>
    </>
  );
}
