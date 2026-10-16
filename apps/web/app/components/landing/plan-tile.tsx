"use client";
import { Icon } from "../ui";
import { useLoopStep } from "./use-loop-step";

const TASKS = [
  ["Measured efficiency from \u221215 to \u221225\u00a0\u00b0C", 4],
  ["Where rated figures differ from field data", 3],
  ["Backup heat and sizing on the coldest days", 4],
] as const;

// 0-2: the planner writes tasks in; 3-5: each runs in turn; 6: all done; then hold.
const STEPS = 9;
const STEP_MS = 950;
// Shown without motion: one done, one running, one queued.
const STILL = 4;

function stateOf(step: number, index: number) {
  const runAt = TASKS.length + index;
  if (step < index) return "hidden";
  if (step < runAt) return "waiting";
  if (step === runAt) return "active";
  return "done";
}

export function PlanTile() {
  const [root, step] = useLoopStep<HTMLDivElement>({
    steps: STEPS,
    ms: STEP_MS,
    still: STILL,
  });

  const states = TASKS.map((_, index) => stateOf(step, index));
  const written = states.filter((state) => state !== "hidden").length;
  const sources = TASKS.reduce(
    (total, [, count], index) => total + (states[index] === "done" ? count : 0),
    0,
  );
  const finished = states.every((state) => state === "done");

  return (
    <div ref={root} className="lp-plan" aria-hidden="true">
      <p className="lp-plan-head">
        Research plan
        <span>{written}</span>
        <small data-done={finished || undefined}>
          {finished ? "Coverage 3 / 3" : `${sources} sources read`}
        </small>
      </p>
      <ul>
        {TASKS.map(([task], index) => (
          <li key={task} data-state={states[index]}>
            <span>
              <Icon name="check" size={11} />
            </span>
            {task}
          </li>
        ))}
      </ul>
    </div>
  );
}
