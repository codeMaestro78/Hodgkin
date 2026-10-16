"use client";
import { useEffect, useRef, useState } from "react";

/*
 * Drives a small looping scene. Counts 0..steps-1 while the element is on
 * screen and the tab is visible, restarting from 0 each time it scrolls into
 * view. With reduced motion it holds on `still`, a readable mid-point.
 * `durations` may give a length per step; otherwise every step lasts `ms`.
 */
export function useLoopStep<T extends HTMLElement>({
  steps,
  ms,
  still,
  durations,
}: {
  steps: number;
  ms: number;
  still: number;
  durations?: readonly number[];
}) {
  const ref = useRef<T>(null);
  const [step, setStep] = useState(still);
  const timing = useRef(durations);
  timing.current = durations;

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer = 0;
    let visible = false;
    let current = 0;
    const stop = () => {
      window.clearTimeout(timer);
      timer = 0;
    };
    const schedule = () => {
      timer = window.setTimeout(() => {
        current = (current + 1) % steps;
        setStep(current);
        schedule();
      }, timing.current?.[current] ?? ms);
    };
    const start = () => {
      if (timer || !visible || document.hidden || reduce.matches) return;
      schedule();
    };
    const sync = () => {
      if (reduce.matches) {
        stop();
        setStep(still);
      } else start();
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry?.isIntersecting ?? false;
      if (visible) {
        if (!reduce.matches) {
          current = 0;
          setStep(0);
        }
        start();
      } else stop();
    });
    observer.observe(node);
    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);
    reduce.addEventListener("change", sync);
    sync();
    return () => {
      stop();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduce.removeEventListener("change", sync);
    };
  }, [steps, ms, still]);

  return [ref, step] as const;
}
