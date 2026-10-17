"use client";
import {
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { Icon } from "../ui";

/*
 * A guided look at the evidence panel beside every answer. The tabs advance
 * on their own while the section is on screen; hovering, focusing, or
 * choosing a tab hands control to the reader. With reduced motion nothing
 * advances by itself.
 */

const MINUS = "\u2212";
const DEG = "\u00a0\u00b0C";

const TABS = [
  {
    id: "sources",
    label: "Sources",
    kicker: "Evidence",
    count: 10,
    title: "Every source, with the passage it gave.",
    body: "What the run read, where it came from, the extract quoted in the answer, and whether it was cited or only collected.",
  },
  {
    id: "method",
    label: "Methodology",
    kicker: "Process",
    title: "The plan and every step that ran.",
    body: "The approved plan, the searches behind each sub-question, coverage loops, and how long each step took. Recorded actions, not private reasoning.",
  },
  {
    id: "checks",
    label: "Checks",
    kicker: "Verdicts",
    count: 5,
    title: "Each claim, its span, and its verdict.",
    body: "Every claim the verifier reviewed, whether its quote matched exactly, and the verdict. Excluded claims stay listed with the reason.",
  },
] as const;
type TabId = (typeof TABS)[number]["id"];

const SOURCES = [
  {
    title: "Cold-climate field monitoring study",
    kind: "Field study",
    quote: `units delivered a seasonal COP of 1.9 at ${MINUS}20${DEG}`,
    cite: 1,
  },
  {
    title: "Low-temperature capacity test",
    kind: "Lab report",
    quote: `Output at ${MINUS}25${DEG} averaged 71% of the rated capacity`,
    cite: 2,
  },
  {
    title: "Winter backup heat runtime",
    kind: "Program report",
    quote: "Backup resistance heat ran for 6.4% of winter hours",
    cite: 3,
  },
  {
    title: "Installer sizing guide",
    kind: "Trade guide",
    quote: null,
    cite: 0,
  },
] as const;

const STEPS = [
  ["intake", "Scope fixed: Balanced, 12 searches", "0:04"],
  ["planner", "3 sub-questions drafted", "0:11"],
  ["approval_gate", "Approved by you, clock paused", "paused"],
  ["research_worker", "3 lanes, 9 searches, 10 sources", "2:47"],
  ["reflector", "Coverage 3 / 3, no loop needed", "0:09"],
  ["verifier", "5 claims reviewed", "0:38"],
  ["synthesizer", "Balanced report, version 1", "0:21"],
] as const;

const CHECKS = [
  [`COP of 1.9 at ${MINUS}20${DEG}`, "supports"],
  [`71% of rated capacity at ${MINUS}25${DEG}`, "supports"],
  ["Most homes can remove backup heat", "partially_supports"],
  ["Backup heat ran 6.4% of winter hours", "supports"],
  ["Running costs fall in every climate", "unrelated"],
] as const;

function SourcesView() {
  return (
    <table className="lp-tour-table">
      <thead>
        <tr>
          <th scope="col">#</th>
          <th scope="col">Source</th>
          <th scope="col">Relevant extract</th>
          <th scope="col">Assessment</th>
        </tr>
      </thead>
      <tbody>
        {SOURCES.map((source, index) => (
          <tr key={source.title} style={{ "--i": index } as CSSProperties}>
            <td>
              {source.cite ? (
                <span className="lp-source-index">{source.cite}</span>
              ) : (
                <span className="lp-tour-dash">-</span>
              )}
            </td>
            <td>
              <strong>{source.title}</strong>
              <small>{source.kind}</small>
            </td>
            <td>
              {source.quote ? (
                <q>{source.quote}</q>
              ) : (
                <span className="lp-tour-muted">Not quoted in the answer</span>
              )}
            </td>
            <td>
              <span
                className="lp-tour-pill"
                data-tone={source.cite ? "ok" : undefined}
              >
                {source.cite ? "Cited" : "Collected"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MethodView() {
  return (
    <ol className="lp-tour-steps">
      {STEPS.map(([node, detail, time], index) => (
        <li key={node} style={{ "--i": index } as CSSProperties}>
          <code>{node}</code>
          <span>{detail}</span>
          <small data-paused={time === "paused" || undefined}>
            {time === "paused" ? (
              <>
                <Icon name="clock" size={11} />
                Paused
              </>
            ) : (
              time
            )}
          </small>
        </li>
      ))}
    </ol>
  );
}

function ChecksView() {
  return (
    <ul className="lp-tour-checks">
      {CHECKS.map(([claim, verdict], index) => {
        const ok = verdict === "supports";
        return (
          <li
            key={claim}
            data-state={ok ? "ok" : "out"}
            style={{ "--i": index } as CSSProperties}
          >
            <span className="lp-gate-mark">
              <Icon name={ok ? "check" : "close"} size={11} />
            </span>
            <span className="lp-tour-claim">
              {claim}
              <small>
                {ok
                  ? "Exact span matched, published"
                  : "Excluded from the answer, reason kept"}
              </small>
            </span>
            <code>{verdict}</code>
          </li>
        );
      })}
    </ul>
  );
}

const VIEWS: Record<TabId, ComponentType> = {
  sources: SourcesView,
  method: MethodView,
  checks: ChecksView,
};

export function EvidenceTour() {
  const root = useRef<HTMLDivElement>(null);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);
  const [active, setActive] = useState(0);
  const [visible, setVisible] = useState(false);
  const [held, setHeld] = useState(false);

  useEffect(() => {
    const node = root.current;
    if (!node) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(entry?.isIntersecting ?? false),
      { threshold: 0.35 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const choose = (index: number, focus = false) => {
    const next = (index + TABS.length) % TABS.length;
    setActive(next);
    setHeld(true);
    if (focus) tabs.current[next]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const moves: Record<string, number> = {
      ArrowDown: active + 1,
      ArrowRight: active + 1,
      ArrowUp: active - 1,
      ArrowLeft: active - 1,
      Home: 0,
      End: TABS.length - 1,
    };
    const target = moves[event.key];
    if (target === undefined) return;
    event.preventDefault();
    choose(target, true);
  };

  const tab = TABS[active] ?? TABS[0];
  const View = VIEWS[tab.id];
  const running = visible && !held;

  return (
    <div
      ref={root}
      className="lp-tour"
      data-reveal
      data-running={running || undefined}
      onPointerEnter={() => setHeld(true)}
      onPointerLeave={() => setHeld(false)}
    >
      <div
        className="lp-tour-tabs"
        role="tablist"
        aria-label="Evidence panel views"
        aria-orientation="vertical"
        onKeyDown={onKeyDown}
      >
        {TABS.map((item, index) => {
          const selected = index === active;
          return (
            <button
              key={item.id}
              ref={(node) => {
                tabs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`lp-tour-tab-${item.id}`}
              aria-selected={selected}
              aria-controls="lp-tour-panel"
              tabIndex={selected ? 0 : -1}
              className="lp-tour-tab"
              onClick={() => choose(index)}
            >
              {selected && (
                <span
                  key={`${item.id}-${active}`}
                  className="lp-tour-progress"
                  aria-hidden="true"
                  onAnimationEnd={() =>
                    setActive((current) => (current + 1) % TABS.length)
                  }
                />
              )}
              <span className="lp-tour-tab-label">
                {item.label}
                <small>{item.kicker}</small>
              </span>
              <strong>{item.title}</strong>
              <span className="lp-tour-tab-body">
                <span>{item.body}</span>
              </span>
            </button>
          );
        })}
      </div>

      <div className="lp-tour-stage" data-spotlight>
        <div className="lp-tour-panel">
          <div className="lp-tour-bar" aria-hidden="true">
            {TABS.map((item, index) => (
              <span key={item.id} data-active={index === active || undefined}>
                {item.label}
                {"count" in item && <b>{item.count}</b>}
              </span>
            ))}
          </div>
          <div
            key={tab.id}
            id="lp-tour-panel"
            role="tabpanel"
            aria-labelledby={`lp-tour-tab-${tab.id}`}
            className="lp-tour-view"
            tabIndex={0}
          >
            <View />
          </div>
        </div>
      </div>
    </div>
  );
}
