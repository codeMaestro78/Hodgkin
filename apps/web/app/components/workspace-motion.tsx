"use client";

import { useRef } from "react";
import type { RefObject } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";

gsap.registerPlugin(useGSAP);

/** Animates only on meaningful changes, never on polling or text input. */
export function useEntrance(
  scope: RefObject<HTMLElement | null>,
  change: string,
  selector: string,
  direction: "up" | "left" | "right" = "up",
) {
  useGSAP(
    () => {
      const media = gsap.matchMedia();
      media.add("(prefers-reduced-motion: no-preference)", () => {
        if (document.documentElement.dataset.inputModality === "keyboard")
          return;
        const targets = scope.current?.querySelectorAll(selector);
        if (!targets?.length) return;
        gsap.fromTo(
          targets,
          {
            opacity: 0.35,
            x: direction === "up" ? 0 : direction === "right" ? 10 : -10,
            y: direction === "up" ? 10 : 0,
          },
          {
            opacity: 1,
            x: 0,
            y: 0,
            duration: 0.28,
            stagger: 0.035,
            ease: "power3.out",
            clearProps: "transform,opacity",
          },
        );
      });
      return () => media.revert();
    },
    { scope, dependencies: [change, direction], revertOnUpdate: true },
  );
}

/** One compositor-only marker follows the selection, including resize/font load. */
export function useSlidingIndicator(
  scope: RefObject<HTMLElement | null>,
  value: string | number,
  selected = '[aria-selected="true"]',
) {
  const previous = useRef<{ x: number; width: number } | null>(null);
  const indicatorAnimation = useRef<Animation | null>(null);
  const updateSelection = useRef<((animate: boolean) => void) | null>(null);
  const attached = useRef<HTMLElement | null>(null);
  const dispose = useRef<(() => void) | null>(null);
  useGSAP(
    () => {
      if (attached.current !== scope.current) {
        dispose.current?.();
        attached.current = scope.current;
      }
      if (updateSelection.current) {
        updateSelection.current(true);
        return;
      }
      const parent = scope.current;
      const marker = parent?.querySelector<HTMLElement>(".selection-marker");
      if (!parent || !marker) return;
      const media = gsap.matchMedia();
      media.add(
        {
          reduce: "(prefers-reduced-motion: reduce)",
          normal: "(prefers-reduced-motion: no-preference)",
        },
        (context) => {
          const update = (animate: boolean) => {
            const active = parent.querySelector<HTMLElement>(selected);
            if (!active) return;
            const parentBox = parent.getBoundingClientRect();
            const box = active.getBoundingClientRect();
            const next = { x: box.left - parentBox.left, width: box.width };
            if (
              !animate &&
              previous.current?.x === next.x &&
              previous.current?.width === next.width
            )
              return;
            // Snapshot the visible position before interrupting an in-flight selection.
            const from = getComputedStyle(marker).transform;
            indicatorAnimation.current?.cancel();
            const transform = `translateX(${next.x}px) scaleX(${next.width})`;
            marker.style.transform = transform;
            marker.style.opacity = "1";
            if (
              animate &&
              previous.current &&
              !context.conditions?.reduce &&
              document.documentElement.dataset.inputModality !== "keyboard"
            ) {
              indicatorAnimation.current = marker.animate(
                [{ transform: from }, { transform }],
                { duration: 180, easing: "cubic-bezier(0.23, 1, 0.32, 1)" },
              );
            }
            previous.current = next;
          };
          const safeUpdate = context.add("updateIndicator", update);
          updateSelection.current = (animate) => safeUpdate(animate);
          updateSelection.current(false);
          const observer = new ResizeObserver(() => safeUpdate(false));
          observer.observe(parent);
          parent
            .querySelectorAll<HTMLElement>("button, label")
            .forEach((el) => observer.observe(el));
          return () => {
            indicatorAnimation.current?.cancel();
            indicatorAnimation.current = null;
            observer.disconnect();
            updateSelection.current = null;
            previous.current = null;
          };
        },
      );
      dispose.current = () => media.revert();
      return () => media.revert();
    },
    { scope, dependencies: [value, selected] },
  );
}
