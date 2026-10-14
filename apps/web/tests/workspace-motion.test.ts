import { afterEach, expect, it, vi } from "vitest";
import { useEntrance } from "../app/components/workspace-motion";

const motion = vi.hoisted(() => ({
  reduced: false,
  cleanup: undefined as (() => void) | undefined,
}));
vi.mock("@gsap/react", () => ({
  useGSAP: (callback: () => void) => callback(),
}));
vi.mock("gsap", () => ({
  default: {
    registerPlugin: vi.fn(),
    matchMedia: () => ({
      add: (_query: string, callback: () => (() => void) | undefined) => {
        if (!motion.reduced) motion.cleanup = callback();
      },
      revert: () => motion.cleanup?.(),
    }),
  },
}));
afterEach(() => {
  motion.cleanup?.();
  motion.cleanup = undefined;
  motion.reduced = false;
  vi.unstubAllGlobals();
});

function scope(modality = "pointer") {
  vi.stubGlobal("document", {
    documentElement: { dataset: { inputModality: modality } },
  });
  const cancel = vi.fn();
  const animate = vi.fn(
    (_frames: Keyframe[], _options: KeyframeAnimationOptions) => ({ cancel }),
  );
  return {
    ref: {
      current: {
        querySelectorAll: () => Array.from({ length: 8 }, () => ({ animate })),
      },
    } as unknown as { current: HTMLElement },
    animate,
    cancel,
  };
}

it("uses readable, bounded compositor keyframes and cancels all entrance effects", () => {
  const { ref, animate, cancel } = scope();
  useEntrance(ref, "evidence", ".panel", "right");
  expect(animate).toHaveBeenCalledTimes(8);
  expect(animate.mock.calls[0]).toEqual([
    [
      { opacity: 0.7, transform: "translateX(6px)" },
      { opacity: 1, transform: "none" },
    ],
    { duration: 200, delay: 0, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
  ]);
  expect(animate.mock.calls[7]?.[1]).toMatchObject({ delay: 60 });
  motion.cleanup?.();
  expect(cancel).toHaveBeenCalledTimes(8);
  // No fill mode or retained style hides content when an effect is cancelled.
  expect(animate.mock.calls[0]?.[1]).not.toHaveProperty("fill");
});

it("keeps keyboard navigation immediate", () => {
  const { ref, animate } = scope("keyboard");
  useEntrance(ref, "checks", ".panel");
  expect(animate).not.toHaveBeenCalled();
});

it("never starts entrance effects for reduced motion", () => {
  const { ref, animate } = scope();
  motion.reduced = true;
  useEntrance(ref, "checks", ".panel");
  expect(animate).not.toHaveBeenCalled();
});
