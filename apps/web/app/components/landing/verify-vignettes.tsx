"use client";
import { Icon } from "../ui";
import { useLoopStep } from "./use-loop-step";

/*
 * Three small loops for "How we verify", using the same run as the hero
 * console. Each one shows a single rule of the verifier as it really
 * applies: the quote must exist in the source, only "supports" publishes,
 * and every citation opens the passage behind it.
 */

const MINUS = "\u2212";
const DEG = "\u00a0\u00b0C";

/* 1. The quote has to exist, word for word, in the retrieved text. */

// 0 claim, 1 scan, 2 highlight, 3 span matched, 4 review, then hold.
const SPAN_MS = [900, 1500, 1100, 900, 2800] as const;

export function SpanMatch() {
  const [ref, step] = useLoopStep<HTMLDivElement>({
    steps: SPAN_MS.length,
    ms: 1000,
    still: 4,
    durations: SPAN_MS,
  });
  return (
    <div
      ref={ref}
      className="lp-vg lp-span"
      data-step={step}
      aria-hidden="true"
    >
      <p className="lp-span-claim">
        <span>Claim draft</span>
        Monitored units delivered a COP of 1.9 at {MINUS}20{DEG}.
      </p>
      <div className="lp-span-doc">
        <p className="lp-span-doc-head">
          <span className="lp-source-index">1</span>
          <strong>Cold-climate field monitoring study</strong>
          <small>Retrieved text</small>
        </p>
        <div className="lp-span-text">
          <i />
          <i />
          <p>
            Across the monitored sites,{" "}
            <mark>
              units delivered a seasonal COP of 1.9 at {MINUS}20{DEG}
            </mark>{" "}
            outdoor temperature.
          </p>
          <i />
          <i />
          <span className="lp-span-scan" />
        </div>
      </div>
      <p className="lp-vg-checks">
        <span data-state={step >= 3 ? "ok" : step >= 1 ? "run" : "wait"}>
          <Icon name="check" size={11} />
          {step >= 3 ? "Exact span matched" : "Matching span"}
        </span>
        <span data-state={step >= 4 ? "ok" : "wait"}>
          <Icon name="check" size={11} />
          Review: supports
        </span>
      </p>
    </div>
  );
}

/* 2. Only "supports" is published. Everything else is excluded and counted. */

const CANDIDATES = [
  [`COP of 1.9 at ${MINUS}20${DEG}`, "supports"],
  [`71% of rated capacity at ${MINUS}25${DEG}`, "supports"],
  ["Most homes can remove backup heat", "partially_supports"],
  ["Backup heat ran 6.4% of winter hours", "supports"],
  ["Running costs fall in every climate", "unrelated"],
] as const;
const GATE_MS = [800, 650, 650, 650, 650, 900, 3000] as const;

export function ClaimGate() {
  const [ref, step] = useLoopStep<HTMLDivElement>({
    steps: GATE_MS.length,
    ms: 800,
    still: 6,
    durations: GATE_MS,
  });
  // Step 1..5 reviews one claim each; step 6 settles the result.
  const reviewed = Math.max(0, Math.min(step, CANDIDATES.length));
  const settled = step >= CANDIDATES.length + 1;
  const published = CANDIDATES.slice(0, reviewed).filter(
    ([, verdict]) => verdict === "supports",
  ).length;
  const excluded = reviewed - published;
  return (
    <div
      ref={ref}
      className="lp-vg lp-gate"
      data-settled={settled || undefined}
      aria-hidden="true"
    >
      <p className="lp-gate-head">
        <span>Candidate claims</span>
        <span>Review</span>
      </p>
      <ul>
        {CANDIDATES.map(([claim, verdict], index) => {
          const state =
            index >= reviewed ? "wait" : verdict === "supports" ? "ok" : "out";
          return (
            <li key={claim} data-state={state}>
              <span className="lp-gate-mark">
                <Icon name={state === "out" ? "close" : "check"} size={11} />
              </span>
              <span className="lp-gate-claim">{claim}</span>
              <code>{index < reviewed ? verdict : "queued"}</code>
            </li>
          );
        })}
      </ul>
      <p className="lp-gate-foot">
        <span>
          <b>{published}</b> published
        </span>
        <span data-out>
          <b>{excluded}</b> excluded
        </span>
        <small>{settled ? "Exclusions kept in Checks" : "Verifier"}</small>
      </p>
    </div>
  );
}

/* 3. A citation opens the exact passage it rests on. */

// 0 read, 1 press citation, 2 card opens, 3 passage marks, then hold.
const OPEN_MS = [1200, 600, 900, 3200] as const;

export function CitationOpen() {
  const [ref, step] = useLoopStep<HTMLDivElement>({
    steps: OPEN_MS.length,
    ms: 1000,
    still: 3,
    durations: OPEN_MS,
  });
  return (
    <div
      ref={ref}
      className="lp-vg lp-open"
      data-step={step}
      aria-hidden="true"
    >
      <div className="lp-open-answer">
        <small>Answer</small>
        <p>
          Monitored cold-climate units delivered a COP of 1.9 at{" "}
          <span className="lp-glue">
            {MINUS}20{DEG}
            <sup className="lp-cite">1</sup>,
          </span>{" "}
          but output at {MINUS}25{DEG} averaged 71% of rated{" "}
          <span className="lp-glue">
            <span className="lp-open-target">
              capacity
              <sup className="lp-cite" data-pressed={step >= 1 || undefined}>
                2
              </sup>
            </span>
            .
          </span>
        </p>
        <i />
        <i />
      </div>
      <div className="lp-open-card" data-shown={step >= 2 || undefined}>
        <p className="lp-open-card-head">
          <span className="lp-source-index">2</span>
          <span>
            <strong>Low-temperature capacity test</strong>
            <small>Lab report</small>
          </span>
        </p>
        <span className="lp-open-badge">Exact quote matched</span>
        <blockquote>
          <mark data-on={step >= 3 || undefined}>
            Output at {MINUS}25{DEG} averaged 71% of the rated capacity
          </mark>{" "}
          across the tested units.
        </blockquote>
        <p className="lp-open-foot">
          <span>Model review: supports</span>
          <span>
            Open original source
            <Icon name="external" size={12} />
          </span>
        </p>
      </div>
    </div>
  );
}
