"use client";
import { useId, useState } from "react";
import { Icon } from "../ui";

const QUESTIONS: [string, string][] = [
  [
    "Where does the evidence come from?",
    "From the live web. Each run plans its searches, reads the pages it finds, and keeps the source material with the report, so you can open what was actually read.",
  ],
  [
    "How do I check a claim?",
    "Citations sit inline with the answer. Open one to see the source it points to without leaving the report or losing your place.",
  ],
  [
    "Can I control how deep it goes?",
    "Yes. Choose Focused, Balanced, or Deep before a run starts. Deeper runs read more widely and take longer; the plan is visible either way.",
  ],
  [
    "What happens to my past research?",
    "Runs stay in your history. Save the ones that matter to the library, compare two runs side by side, or export a report as a PDF.",
  ],
  [
    "Can research run on a schedule?",
    "Automation can queue a batch of questions or repeat one on a schedule, with an approval step before anything runs.",
  ],
];

export function FaqThread({
  items = QUESTIONS,
}: {
  items?: [string, string][];
}) {
  const [open, setOpen] = useState(0);
  const base = useId();
  return (
    <div className="lp-thread">
      {items.map(([question, answer], index) => {
        const expanded = open === index;
        const panel = `${base}-answer-${index}`;
        return (
          <div className="lp-thread-item" key={question} data-open={expanded}>
            <h3>
              <button
                type="button"
                className="lp-bubble-ask"
                aria-expanded={expanded}
                aria-controls={panel}
                onClick={() => setOpen(expanded ? -1 : index)}
              >
                {question}
                <span className="lp-bubble-toggle" aria-hidden="true">
                  <Icon name="plus" size={14} />
                </span>
              </button>
            </h3>
            <div className="lp-bubble-wrap" id={panel} role="region">
              <div className="lp-bubble-clip">
                <p className="lp-bubble-answer" inert={!expanded}>
                  {answer}
                </p>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
