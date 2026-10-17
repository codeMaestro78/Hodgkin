"use client";
import { useEffect } from "react";

const REACH = 2.4;

/*
 * One pointer listener and one rAF loop for every character on the page.
 * Pupils lean toward the cursor through CSS variables, so React never
 * re-renders while they move.
 */
export function CrewEyes() {
  useEffect(() => {
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || reduce.matches) return;
    const root = document.documentElement;
    root.classList.add("crew-tracking");
    let pointer: { x: number; y: number } | null = null;
    let frame = 0;
    const current = new WeakMap<HTMLElement, { x: number; y: number }>();
    const lean = new WeakMap<HTMLElement, { x: number; y: number }>();

    const tick = () => {
      frame = 0;
      if (!pointer) return;
      let moving = false;
      document.querySelectorAll<HTMLElement>("[data-critter]").forEach((el) => {
        const rect = el.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) return;
        const dx = pointer!.x - (rect.left + rect.width / 2);
        const dy = pointer!.y - (rect.top + rect.height * 0.4);
        const distance = Math.hypot(dx, dy) || 1;
        const pull = Math.min(1, distance / 260);
        const target = { x: (dx / distance) * pull, y: (dy / distance) * pull };
        const now = current.get(el) ?? { x: 0, y: 0 };
        now.x += (target.x - now.x) * 0.2;
        now.y += (target.y - now.y) * 0.2;
        current.set(el, now);
        /* The body is heavier than the gaze: it trails with a slower lerp. */
        const body = lean.get(el) ?? { x: 0, y: 0 };
        body.x += (target.x - body.x) * 0.075;
        body.y += (target.y - body.y) * 0.075;
        lean.set(el, body);
        if (
          Math.abs(target.x - now.x) + Math.abs(target.y - now.y) > 0.01 ||
          Math.abs(target.x - body.x) + Math.abs(target.y - body.y) > 0.004
        )
          moving = true;
        el.style.setProperty("--lx", (now.x * REACH).toFixed(2));
        el.style.setProperty("--ly", (now.y * REACH).toFixed(2));
        el.style.setProperty("--px", body.x.toFixed(3));
        el.style.setProperty("--py", body.y.toFixed(3));
      });
      if (moving) frame = requestAnimationFrame(tick);
    };
    const move = (event: PointerEvent) => {
      pointer = { x: event.clientX, y: event.clientY };
      if (!frame) frame = requestAnimationFrame(tick);
    };
    const scroll = () => {
      if (pointer && !frame) frame = requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", move, { passive: true });
    window.addEventListener("scroll", scroll, { passive: true, capture: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("scroll", scroll, { capture: true });
      cancelAnimationFrame(frame);
      root.classList.remove("crew-tracking");
    };
  }, []);
  return null;
}
