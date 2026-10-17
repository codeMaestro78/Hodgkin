"use client";
import { useEffect, useRef } from "react";

const SPACING = 22;
const INK = "37, 37, 34";
const COPPER = "169, 97, 66";

function hash(x: number, y: number) {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

type Cell = { x: number; y: number; kind: number; base: number; seed: number };

/*
 * Ambient field of small marks behind the hero. Marks are quietest where the
 * headline sits, a slow diagonal band brightens them, and a few briefly turn
 * copper, like evidence being picked out of the noise.
 */
export function EvidenceField() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let cells: Cell[] = [];
    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;
    let elapsed = 0;
    let visible = true;

    const build = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      cells = [];
      const cols = Math.ceil(width / SPACING) + 1;
      const rows = Math.ceil(height / SPACING) + 1;
      const offsetX = (width - (cols - 1) * SPACING) / 2;
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const x = offsetX + col * SPACING;
          const y = 12 + row * SPACING;
          const nx = (x - width / 2) / (width / 2);
          const ny = y / height;
          // Clear a soft ellipse for the headline, fade to the edges and bottom.
          const title = Math.hypot(nx * 1.25, (ny - 0.26) * 3.1);
          const clearing = Math.min(1, Math.max(0, (title - 0.55) / 0.6));
          const edge = Math.min(1, (1 - Math.abs(nx)) * 2.4);
          const bottom = Math.min(1, Math.max(0, (1 - ny) * 1.8));
          const base = clearing * edge * bottom;
          if (base < 0.04) continue;
          const roll = hash(col, row);
          const kind = roll > 0.93 ? 3 : roll > 0.8 ? 2 : roll > 0.36 ? 1 : 0;
          if (kind === 0) continue;
          cells.push({ x, y, kind, base, seed: hash(row, col) });
        }
      }
    };

    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      const band = ((time / 9000) % 1) * (width + height) * 1.4 - height;
      for (const cell of cells) {
        const distance = cell.x + cell.y * 0.6 - band;
        const wave = Math.exp(-(distance * distance) / 26000);
        const pulse = Math.max(
          0,
          Math.sin(time / 1700 + cell.seed * 60) * 1.6 - 0.6,
        );
        const cited = cell.kind === 3 && pulse > 0.35;
        const alpha = Math.min(
          0.8,
          cell.base * (0.13 + wave * 0.32 + (cited ? pulse * 0.45 : 0)),
        );
        context.fillStyle = `rgba(${cited ? COPPER : INK}, ${alpha})`;
        if (cell.kind === 1) {
          context.fillRect(cell.x - 0.75, cell.y - 0.75, 1.5, 1.5);
        } else if (cell.kind === 2) {
          context.fillRect(cell.x - 2, cell.y - 2, 4, 4);
        } else {
          context.beginPath();
          context.moveTo(cell.x, cell.y - 3.2);
          context.lineTo(cell.x + 3.2, cell.y);
          context.lineTo(cell.x, cell.y + 3.2);
          context.lineTo(cell.x - 3.2, cell.y);
          context.closePath();
          context.fill();
        }
      }
    };

    const tick = (now: number) => {
      frame = 0;
      if (!visible || document.hidden || reduce.matches) return;
      // 30fps is plenty for an ambient field and halves the paint cost.
      if (now - last >= 33) {
        elapsed += Math.min(now - last, 100);
        last = now;
        draw(elapsed);
      }
      frame = requestAnimationFrame(tick);
    };

    const start = () => {
      if (frame || reduce.matches) return;
      last = performance.now();
      frame = requestAnimationFrame(tick);
    };
    const stop = () => {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    };
    const refresh = () => {
      build();
      draw(elapsed);
      if (reduce.matches) stop();
      else start();
    };

    refresh();
    const resize = new ResizeObserver(refresh);
    resize.observe(canvas);
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry?.isIntersecting ?? false;
      if (visible) start();
      else stop();
    });
    observer.observe(canvas);
    const onVisibility = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVisibility);
    reduce.addEventListener("change", refresh);
    return () => {
      stop();
      resize.disconnect();
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      reduce.removeEventListener("change", refresh);
    };
  }, []);

  return <canvas ref={ref} className="lp-field" aria-hidden="true" />;
}
