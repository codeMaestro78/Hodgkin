import type { CSSProperties } from "react";
import "../../crew.css";

export type CritterKind = "folio" | "lens" | "seal" | "quill";

const INK = "#252522";

function Eyes({ left, right, y }: { left: number; right: number; y: number }) {
  return (
    <g className="crit-eyes">
      {[left, right].map((x) => (
        <g key={x}>
          <circle cx={x} cy={y} r="6.2" fill="#fff" />
          <g className="crit-pupil">
            <circle cx={x} cy={y} r="3" fill={INK} />
            <circle cx={x + 1.1} cy={y - 1.2} r="0.9" fill="#fff" />
          </g>
        </g>
      ))}
    </g>
  );
}

function Legs({
  x,
  from,
  to,
}: {
  x: [number, number];
  from: number;
  to: number;
}) {
  return (
    <g
      className="crit-legs"
      stroke={INK}
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    >
      {x.map((value, index) => (
        <path
          key={value}
          d={`M${value} ${from}L${value} ${to}l${index ? 3.5 : -3.5} 0`}
        />
      ))}
    </g>
  );
}

/* A folded research page. Calm; it keeps the notes. */
function Folio() {
  return (
    <>
      <Legs x={[24, 40]} from={60} to={71} />
      <g className="crit-body">
        <path
          d="M14 6h26l14 14v34a8 8 0 0 1-8 8H14a8 8 0 0 1-8-8V14a8 8 0 0 1 8-8Z"
          fill="#e5bd6d"
        />
        <path d="M40 6v8a6 6 0 0 0 6 6h8Z" fill="#f2d9a3" />
        <path
          d="M17 48h18M17 53h11"
          stroke="#c99844"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <Eyes left={22} right={38} y={28} />
        <path
          d="M27.5 37.5q2.5 2.6 5 0"
          stroke={INK}
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      </g>
    </>
  );
}

/* A magnifying lens. Curious; always looking closer. */
function Lens() {
  return (
    <>
      <Legs x={[24, 36]} from={54} to={71} />
      <g className="crit-body">
        <path
          d="M47 47l9 9"
          stroke="#6f9a7a"
          strokeWidth="8"
          strokeLinecap="round"
        />
        <circle cx="30" cy="30" r="25" fill="#93b89c" />
        <circle cx="30" cy="30" r="18.5" fill="#b8d5bf" />
        <path
          d="M17 22a15 15 0 0 1 9-8"
          stroke="#fff"
          strokeOpacity=".7"
          strokeWidth="2.6"
          strokeLinecap="round"
          fill="none"
        />
        <Eyes left={23} right={37} y={30} />
        <ellipse cx="30" cy="40.5" rx="2.4" ry="2" fill={INK} />
      </g>
    </>
  );
}

/* A diamond seal. Particular about whether a claim checks out. */
function Seal() {
  return (
    <>
      <Legs x={[26, 38]} from={57} to={71} />
      <g className="crit-body">
        <path
          d="M32 5 59 33 32 62 5 33Z"
          fill="#8fb0c9"
          stroke="#8fb0c9"
          strokeWidth="7"
          strokeLinejoin="round"
        />
        <path
          d="M32 12 51 33 32 54"
          fill="none"
          stroke="#a9c4d8"
          strokeWidth="3"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <Eyes left={25} right={39} y={30} />
        <path
          d="M27.5 40.5l3.2 3.2 6-6"
          stroke={INK}
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
      </g>
    </>
  );
}

/* A tall quill. Restless; it wants to write the answer. */
function Quill() {
  return (
    <>
      <Legs x={[26, 38]} from={62} to={71} />
      <g className="crit-body">
        <path d="M24 15 32 1l8 14Z" fill={INK} />
        <path
          d="M32 7v6"
          stroke="#e5bd6d"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <rect x="13" y="12" width="38" height="52" rx="19" fill="#d4948a" />
        <path
          d="M19 29a13 13 0 0 1 6-10"
          stroke="#fff"
          strokeOpacity=".45"
          strokeWidth="2.6"
          strokeLinecap="round"
          fill="none"
        />
        <ellipse cx="20.5" cy="43" rx="3.2" ry="1.9" fill="#c47c72" />
        <ellipse cx="43.5" cy="43" rx="3.2" ry="1.9" fill="#c47c72" />
        <Eyes left={25} right={39} y={34} />
        <path
          d="M29 43.5q3 2.8 6 0"
          stroke={INK}
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      </g>
    </>
  );
}

const BODIES = { folio: Folio, lens: Lens, seal: Seal, quill: Quill };

/*
 * Decorative research characters. Pure SVG so they render on the server;
 * <CrewEyes /> adds pointer-following pupils on the client.
 */
export function Critter({
  kind,
  size = 64,
  pose = "stand",
  delay = 0,
  className = "",
  style,
}: {
  kind: CritterKind;
  size?: number;
  pose?: "stand" | "peek";
  delay?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const Body = BODIES[kind];
  return (
    <span
      className={`critter critter-${kind} ${className}`.trim()}
      data-critter=""
      data-pose={pose}
      aria-hidden="true"
      style={
        {
          "--crit-size": `${size}px`,
          "--crit-delay": `${delay}ms`,
          ...style,
        } as CSSProperties
      }
    >
      <svg viewBox="0 0 64 74" width={size} height={(size * 74) / 64}>
        <Body />
      </svg>
    </span>
  );
}
