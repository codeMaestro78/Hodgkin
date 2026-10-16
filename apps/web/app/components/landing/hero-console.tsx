"use client";
import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { BrandMark, Icon } from "../ui";

/*
 * A scripted replay of one Balanced run through the real research graph:
 * intake -> planner -> approval_gate -> research_worker (one lane per
 * sub-question) -> reflector -> verifier -> synthesizer. Every frame is
 * derived from elapsed time, so the loop is deterministic and seekable.
 */

const QUESTION =
  "Do cold-climate heat pumps keep homes warm below \u221220\u00a0\u00b0C?";
const TITLE = "Cold-climate heat pumps";
const BUDGET = 12;

const PLAN = [
  "Measured efficiency and capacity from \u221215 to \u221225\u00a0\u00b0C",
  "Where rated figures differ from field data",
  "Backup heat and sizing on the coldest days",
];

const LANES = [
  {
    query: "cold climate heat pump field monitoring COP",
    searches: 4,
    sources: 4,
    length: 3.1,
  },
  {
    query: "rated vs measured capacity low temperature",
    searches: 3,
    sources: 3,
    length: 3.6,
  },
  {
    query: "backup resistance heat design temperature",
    searches: 2,
    sources: 3,
    length: 2.7,
  },
];

const CLAIMS = [
  {
    text: "Monitored units delivered a COP of 1.9 at \u221220\u00a0\u00b0C.",
    ok: true,
    cite: 1,
  },
  {
    text: "Output at \u221225\u00a0\u00b0C averaged 71% of rated capacity.",
    ok: true,
    cite: 2,
  },
  { text: "Most homes can remove backup heat entirely.", ok: false, cite: 3 },
  { text: "Backup heat ran for 6.4% of winter hours.", ok: true, cite: 3 },
];
const PUBLISHED = CLAIMS.filter((claim) => claim.ok).length;

type Segment = string | number;
const ANSWER: Segment[] = [
  "Yes, with planning. Monitored cold-climate units delivered a COP of 1.9 at \u221220\u00a0\u00b0C",
  1,
  ", but output at \u221225\u00a0\u00b0C averaged 71% of rated capacity",
  2,
  ". Backup heat ran for 6.4% of winter hours",
  3,
  ", so sizing to the local design temperature matters most.",
];

type Token = { text: string; cite?: number; tail?: string };

/** Citations and trailing punctuation stay glued to the word they follow. */
function tokenize(parts: Segment[]) {
  const tokens: Token[] = [];
  for (const part of parts) {
    const last = tokens[tokens.length - 1];
    if (typeof part === "number") {
      if (last) last.cite = part;
      continue;
    }
    const words = part.trim().split(/ +/);
    const lead = !part.startsWith(" ") ? words.shift() : undefined;
    if (last && lead) last.tail = lead;
    else if (lead) words.unshift(lead);
    for (const text of words) tokens.push({ text });
  }
  return tokens;
}
const TOKENS = tokenize(ANSWER);

const FIGURES = [
  ["COP at \u221220\u00a0\u00b0C", "1.9", 1],
  ["Capacity at \u221225\u00a0\u00b0C", "71%", 2],
  ["Backup heat, winter hours", "6.4%", 3],
] as const;

// Seconds on one looping timeline.
const T = {
  typeStart: 0.4,
  typeEnd: 2.3,
  submit: 2.6,
  planner: 3.2,
  approval: 4.8,
  approve: 6.3,
  research: 6.8,
  reflector: 10.8,
  verifier: 11.7,
  synthesizer: 14.8,
  writeStart: 15.0,
  writeEnd: 17.3,
  figures: 17.5,
  share: 18.2,
  card: 18.7,
  done: 19.2,
  loop: 25,
};
const FINAL = T.loop - 1;
// One replay second stands for nine seconds of a real run.
const SCALE = 9;

const NODES = [
  { id: "intake", label: "Intake", start: T.submit, end: T.planner },
  { id: "planner", label: "Planner", start: T.planner, end: T.approval },
  {
    id: "approval_gate",
    label: "Approval",
    start: T.approval,
    end: T.research,
  },
  {
    id: "research_worker",
    label: "Research",
    start: T.research,
    end: T.reflector,
  },
  { id: "reflector", label: "Reflector", start: T.reflector, end: T.verifier },
  { id: "verifier", label: "Verifier", start: T.verifier, end: T.synthesizer },
  {
    id: "synthesizer",
    label: "Synthesizer",
    start: T.synthesizer,
    end: T.done,
  },
];

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));
const span = (t: number, from: number, to: number) =>
  clamp01((t - from) / (to - from));

/** Run clock in real seconds; it holds still while the plan awaits approval. */
function clockAt(t: number) {
  if (t < T.submit) return 0;
  const beforeGate = Math.min(t, T.approval) - T.submit;
  const afterGate = Math.max(0, Math.min(t, T.done) - T.research);
  return Math.round((beforeGate + afterGate) * SCALE);
}

function formatClock(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function laneProgress(t: number, index: number) {
  const lane = LANES[index]!;
  return span(
    t,
    T.research + index * 0.2,
    T.research + index * 0.2 + lane.length,
  );
}

function Answer({ words, focus }: { words: number; focus: boolean }) {
  return TOKENS.slice(0, words).map((token, index) => (
    <Fragment key={index}>
      {index > 0 && " "}
      {token.cite || token.tail ? (
        <span className="lp-glue">
          {token.text}
          {token.cite && (
            <sup
              className="lp-cite"
              data-focus={(focus && token.cite === 2) || undefined}
            >
              {token.cite}
            </sup>
          )}
          {token.tail}
        </span>
      ) : (
        token.text
      )}
    </Fragment>
  ));
}

function Mark({ state }: { state: "waiting" | "active" | "done" }) {
  return (
    <span className="lp-run-mark" data-state={state}>
      <Icon name="check" size={10} />
    </span>
  );
}

function ComposeScene() {
  return (
    <div className="lp-scene-compose">
      <p className="lp-scene-label">Depth</p>
      <div className="lp-run-depth">
        {[
          ["Focused", "6 searches"],
          ["Balanced", "12 searches"],
          ["Deep", "20 searches"],
        ].map(([name, budget]) => (
          <span key={name} data-selected={name === "Balanced"}>
            <b>{name}</b>
            <small>{budget}</small>
          </span>
        ))}
      </div>
      <p className="lp-run-toggle">
        <span>Review the plan before research starts</span>
        <i data-on="true" />
      </p>
    </div>
  );
}

function PlanScene({ t }: { t: number }) {
  const items = PLAN.filter(
    (_, index) => t >= T.planner + 0.3 + index * 0.4,
  ).length;
  const gate = t >= T.approval;
  const pressed = t >= T.approve;
  const approved = t >= T.approve + 0.3;
  return (
    <div className="lp-scene-plan">
      <p className="lp-run-note" data-shown={t >= T.submit + 0.25}>
        <code>intake</code>
        Scope: home heating, Balanced, {BUDGET} search budget
      </p>
      <p className="lp-scene-label">
        Research plan <span className="lp-count">{items}</span>
      </p>
      <ol className="lp-run-plan">
        {PLAN.map((item, index) => (
          <li key={item} data-shown={index < items}>
            <span className="lp-run-task">T{index + 1}</span>
            {item}
          </li>
        ))}
      </ol>
      <div className="lp-run-gate" data-shown={gate} data-approved={approved}>
        <span className="lp-run-gate-text">
          {approved ? (
            <>
              <Icon name="check" size={13} /> Approved. 3 tasks queued.
            </>
          ) : (
            <>
              <i /> Waiting for your approval. Run clock paused.
            </>
          )}
        </span>
        <span className="lp-run-gate-actions">
          <span>Edit</span>
          <span data-primary data-pressed={pressed && !approved}>
            Approve plan
          </span>
        </span>
      </div>
    </div>
  );
}

function CollectScene({ t }: { t: number }) {
  const searches = LANES.reduce(
    (total, lane, index) =>
      total + Math.round(laneProgress(t, index) * lane.searches),
    0,
  );
  const covered = [0.15, 0.35, 0.55].filter(
    (at) => t >= T.reflector + at,
  ).length;
  return (
    <div className="lp-scene-collect">
      <p className="lp-scene-label">
        Collecting in parallel
        <span className="lp-run-budget">
          Searches <b>{searches}</b> / {BUDGET}
        </span>
      </p>
      <ul className="lp-run-lanes">
        {LANES.map((lane, index) => {
          const progress = laneProgress(t, index);
          return (
            <li key={lane.query} data-done={progress >= 1}>
              <span className="lp-run-task">T{index + 1}</span>
              <span className="lp-run-lane-body">
                <code>{lane.query}</code>
                <span
                  className="lp-run-bar"
                  style={{ "--p": progress } as CSSProperties}
                />
              </span>
              <span className="lp-run-lane-meta">
                {Math.round(progress * lane.sources)} sources
              </span>
            </li>
          );
        })}
      </ul>
      <p className="lp-run-note" data-shown={t >= T.reflector}>
        <code>reflector</code>
        Coverage {covered} / 3 sub-questions
        {covered === 3 ? ". No repair loop needed." : ""}
      </p>
    </div>
  );
}

function VerifyScene({ t }: { t: number }) {
  let published = 0;
  let excluded = 0;
  const rows = CLAIMS.map((claim, index) => {
    const at = T.verifier + 0.15 + index * 0.7;
    const shown = t >= at;
    const exact = t >= at + 0.25;
    const verdict = t >= at + 0.5;
    if (verdict) {
      if (claim.ok) published += 1;
      else excluded += 1;
    }
    return { claim, shown, exact, verdict };
  });
  return (
    <div className="lp-scene-verify">
      <p className="lp-scene-label">
        Checking claim drafts against their quotes
        <span className="lp-run-tally">
          <b>{published}</b> published
          <i />
          <b>{excluded}</b> excluded
        </span>
      </p>
      <ul className="lp-run-claims">
        {rows.map(({ claim, shown, exact, verdict }) => (
          <li
            key={claim.text}
            data-shown={shown}
            data-outcome={
              verdict ? (claim.ok ? "published" : "excluded") : undefined
            }
          >
            <p>{claim.text}</p>
            <span className="lp-run-checks">
              <span data-state={exact ? "ok" : "pending"}>Exact span</span>
              <span
                data-state={verdict ? (claim.ok ? "ok" : "warn") : "pending"}
              >
                {verdict ? (claim.ok ? "Supports" : "Partial") : "Review"}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReportScene({ t }: { t: number }) {
  const words = Math.round(span(t, T.writeStart, T.writeEnd) * TOKENS.length);
  const writing = words < TOKENS.length;
  const figures = FIGURES.filter(
    (_, index) => t >= T.figures + index * 0.15,
  ).length;
  return (
    <div className="lp-scene-report">
      <p className="lp-scene-label">Answer</p>
      <p className="lp-run-answer">
        <Answer words={words} focus={t >= T.card} />
        {writing && <span className="lp-caret" />}
      </p>
      <div className="lp-run-figures" data-shown={figures > 0}>
        <p className="lp-scene-label">Key figures</p>
        <table>
          <tbody>
            {FIGURES.map(([metric, value, cite], index) => (
              <tr key={metric} data-shown={index < figures}>
                <th scope="row">{metric}</th>
                <td>{value}</td>
                <td>
                  <sup className="lp-cite">{cite}</sup>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="lp-run-share" data-shown={t >= T.share}>
        <code>
          published share = {PUBLISHED} / {CLAIMS.length} ={" "}
          {Math.round((PUBLISHED / CLAIMS.length) * 100)}%
        </code>
      </p>
      <div className="lp-run-card" data-shown={t >= T.card}>
        <span className="lp-source-index">2</span>
        <div>
          <strong>Low-temperature capacity test</strong>
          <small>Lab report</small>
          <q>
            Output at {"\u2212"}25{"\u00a0\u00b0"}C averaged 71% of the rated
            capacity across the tested units.
          </q>
          <span className="lp-run-checks">
            <span data-state="ok">Exact span</span>
            <span data-state="ok">Supports</span>
          </span>
        </div>
      </div>
    </div>
  );
}

const SCENES = ["compose", "plan", "collect", "verify", "report"] as const;

function sceneAt(t: number): (typeof SCENES)[number] {
  if (t < T.submit) return "compose";
  if (t < T.research) return "plan";
  if (t < T.verifier) return "collect";
  if (t < T.synthesizer) return "verify";
  return "report";
}

export function HeroConsole() {
  const root = useRef<HTMLDivElement>(null);
  const [time, setTime] = useState(0);
  const [still, setStill] = useState(false);

  useEffect(() => {
    const node = root.current;
    if (!node) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0;
    let last = 0;
    let elapsed = 0;
    let visible = false;
    // Hold until the hero entrance has settled before typing starts.
    let delay = 1.5;

    const tick = (now: number) => {
      const step = Math.min((now - last) / 1000, 0.1);
      last = now;
      if (delay > 0) delay -= step;
      else {
        elapsed = (elapsed + step) % T.loop;
        setTime(Math.round(elapsed * 30) / 30);
      }
      frame = requestAnimationFrame(tick);
    };
    const start = () => {
      if (frame || !visible || document.hidden || reduce.matches) return;
      last = performance.now();
      frame = requestAnimationFrame(tick);
    };
    const stop = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    };
    const applyPreference = () => {
      setStill(reduce.matches);
      if (reduce.matches) stop();
      else start();
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry?.isIntersecting ?? false;
      if (visible) start();
      else stop();
    });
    observer.observe(node);
    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);
    reduce.addEventListener("change", applyPreference);
    applyPreference();
    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduce.removeEventListener("change", applyPreference);
    };
  }, []);

  const t = still ? FINAL : time;
  const typed = Math.round(span(t, T.typeStart, T.typeEnd) * QUESTION.length);
  const scene = sceneAt(t);
  const complete = t >= T.done;
  const active = NODES.find((node) => t >= node.start && t < node.end);
  const awaiting = active?.id === "approval_gate";
  const clock = clockAt(t);

  return (
    <div
      ref={root}
      className="lp-console"
      data-leaving={t > T.loop - 0.45 || undefined}
      role="img"
      aria-label={`A Balanced research run on "${QUESTION}": the plan is approved, three research tasks collect sources in parallel, four claim drafts are checked against their quotes, three are published with citations and one is excluded.`}
    >
      <div className="lp-console-bar" aria-hidden="true">
        <span className="lp-console-crumb">
          <BrandMark size={16} />
          <span className="lp-console-crumb-extra">
            Research
            <Icon name="chevron" size={13} />
          </span>
          <b>{t >= T.submit ? TITLE : "New run"}</b>
        </span>
        <span className="lp-console-meta">
          <span className="lp-run-clock" data-paused={awaiting || undefined}>
            <Icon name="clock" size={13} />
            {formatClock(clock)}
          </span>
          <span
            className="lp-console-status"
            data-state={
              complete ? "done" : awaiting ? "paused" : active ? "live" : "idle"
            }
          >
            <i />
            {complete
              ? "Published"
              : awaiting
                ? "Awaiting approval"
                : (active?.label ?? "Ready")}
          </span>
        </span>
      </div>
      <div className="lp-console-body" aria-hidden="true">
        <ol className="lp-run-rail">
          {NODES.map((node) => {
            const state =
              t >= node.end ? "done" : t >= node.start ? "active" : "waiting";
            const seconds = clockAt(node.end) - clockAt(node.start);
            return (
              <li key={node.id} data-state={state}>
                <Mark state={state} />
                <span className="lp-run-node">
                  <b>{node.label}</b>
                  <code>{node.id}</code>
                </span>
                {node.id === "research_worker" ? (
                  <span className="lp-run-lanes-mini">
                    {LANES.map((lane, index) => (
                      <i
                        key={lane.query}
                        data-done={laneProgress(t, index) >= 1}
                      />
                    ))}
                  </span>
                ) : (
                  <span className="lp-run-time">
                    {state !== "done"
                      ? ""
                      : node.id === "approval_gate"
                        ? "held"
                        : `${seconds}s`}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
        <div className="lp-console-main">
          <div className="lp-console-question" data-sent={t >= T.submit}>
            <Icon name="search" size={16} />
            <p>
              {QUESTION.slice(0, typed)}
              {t < T.submit && <span className="lp-caret" />}
            </p>
            <span className="lp-console-send">
              <Icon name="arrow" size={15} />
            </span>
          </div>
          <div className="lp-scenes">
            {SCENES.map((name) => (
              <section
                key={name}
                className="lp-scene"
                data-active={scene === name}
              >
                {name === "compose" && <ComposeScene />}
                {name === "plan" && <PlanScene t={t} />}
                {name === "collect" && <CollectScene t={t} />}
                {name === "verify" && <VerifyScene t={t} />}
                {name === "report" && <ReportScene t={t} />}
              </section>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
