"use client";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
} from "react";
import {
  EVIDENCE_DEFAULT,
  EVIDENCE_MIN,
  clampEvidenceWidth,
  evidencePreset,
} from "../../lib/report-table";
import { Icon } from "./ui";
import "../research-workspace.css";

const WIDTH_KEY = "hogskin.evidenceWidth";
/** Panel width at which sources switch from a list to a comparison table. */
export const WIDE_PANEL = 560;

type Preset = "reading" | "split" | "wide";

/**
 * Owns the evidence panel width. The live value is a CSS variable on the grid;
 * dragging writes it directly so a long report never re-renders per frame.
 */
export function useEvidenceLayout(
  grid: RefObject<HTMLElement | null>,
  panel: RefObject<HTMLElement | null>,
  ready: boolean,
) {
  const [width, setWidth] = useState(EVIDENCE_DEFAULT);
  const [measured, setMeasured] = useState({ panel: 0, grid: 0 });
  const measure = useRef<() => void>(() => undefined);
  useEffect(() => {
    const saved = Number(window.localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(saved) && saved >= EVIDENCE_MIN) setWidth(saved);
  }, []);
  useEffect(() => {
    const gridElement = grid.current;
    const panelElement = panel.current;
    if (!gridElement || !panelElement) return;
    const read = () =>
      setMeasured((current) => {
        const next = {
          panel: Math.round(panelElement.getBoundingClientRect().width),
          grid: Math.round(gridElement.getBoundingClientRect().width),
        };
        return next.panel === current.panel && next.grid === current.grid
          ? current
          : next;
      });
    measure.current = read;
    read();
    // Dragging writes the width directly; measure once on release instead of per frame.
    const observer = new ResizeObserver(() => {
      if (!gridElement.dataset.resizing) read();
    });
    observer.observe(gridElement);
    observer.observe(panelElement);
    return () => observer.disconnect();
  }, [grid, panel, ready]);
  const commit = useCallback(
    (next: number) => {
      const container = grid.current?.getBoundingClientRect().width ?? 0;
      const value = container ? clampEvidenceWidth(next, container) : next;
      grid.current?.style.setProperty("--evidence-width", `${value}px`);
      setWidth(value);
      requestAnimationFrame(() => measure.current());
      try {
        window.localStorage.setItem(WIDTH_KEY, String(value));
      } catch {
        // Storage can be unavailable in private modes; the width still applies.
      }
    },
    [grid],
  );
  const applyPreset = useCallback(
    (preset: Preset) => {
      const container = grid.current?.getBoundingClientRect().width ?? 0;
      if (container) commit(evidencePreset(preset, container));
    },
    [commit, grid],
  );
  const preset: Preset | null = useMemo(() => {
    if (!measured.grid) return null;
    for (const name of ["reading", "split", "wide"] as const)
      if (Math.abs(evidencePreset(name, measured.grid) - measured.panel) <= 4)
        return name;
    return null;
  }, [measured]);
  return {
    width,
    panelWidth: measured.panel,
    gridWidth: measured.grid,
    wide: measured.panel >= WIDE_PANEL,
    preset,
    commit,
    applyPreset,
  };
}

export function EvidenceResizer({
  grid,
  panelWidth,
  gridWidth,
  onCommit,
}: {
  grid: RefObject<HTMLElement | null>;
  panelWidth: number;
  gridWidth: number;
  onCommit: (width: number) => void;
}) {
  const drag = useRef<{ x: number; width: number; last: number } | null>(null);
  const max = gridWidth
    ? clampEvidenceWidth(Number.MAX_SAFE_INTEGER, gridWidth)
    : EVIDENCE_MIN;
  function end(element: HTMLElement, pointer: number) {
    const state = drag.current;
    drag.current = null;
    if (element.hasPointerCapture(pointer))
      element.releasePointerCapture(pointer);
    delete grid.current?.dataset.resizing;
    if (state) onCommit(state.last);
  }
  function onPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !grid.current) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus({ preventScroll: true });
    drag.current = { x: event.clientX, width: panelWidth, last: panelWidth };
    grid.current.dataset.resizing = "true";
  }
  function onPointerMove(event: PointerEvent<HTMLDivElement>) {
    const state = drag.current;
    const element = grid.current;
    if (!state || !element) return;
    const container = element.getBoundingClientRect().width;
    state.last = clampEvidenceWidth(
      state.width + state.x - event.clientX,
      container,
    );
    element.style.setProperty("--evidence-width", `${state.last}px`);
  }
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey ? 80 : 24;
    const next =
      event.key === "ArrowLeft"
        ? panelWidth + step
        : event.key === "ArrowRight"
          ? panelWidth - step
          : event.key === "Home"
            ? EVIDENCE_MIN
            : event.key === "End"
              ? max
              : event.key === "Enter"
                ? EVIDENCE_DEFAULT
                : null;
    if (next === null) return;
    event.preventDefault();
    onCommit(next);
  }
  return (
    <div
      className="evidence-resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize evidence panel"
      aria-controls="research-evidence"
      aria-valuemin={EVIDENCE_MIN}
      aria-valuemax={Math.max(max, EVIDENCE_MIN)}
      aria-valuenow={panelWidth || EVIDENCE_DEFAULT}
      aria-valuetext={`Evidence panel ${panelWidth || EVIDENCE_DEFAULT} pixels wide`}
      tabIndex={0}
      title="Drag to resize. Double-click to reset."
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => end(event.currentTarget, event.pointerId)}
      onPointerCancel={(event) => end(event.currentTarget, event.pointerId)}
      onLostPointerCapture={(event) => {
        if (drag.current) end(event.currentTarget, event.pointerId);
      }}
      onDoubleClick={() => onCommit(EVIDENCE_DEFAULT)}
      onKeyDown={onKeyDown}
    >
      <span aria-hidden="true" />
    </div>
  );
}

const PRESETS: { id: Preset; label: string; hint: string }[] = [
  { id: "reading", label: "Read", hint: "Narrow evidence, wide report" },
  { id: "split", label: "Split", hint: "Report and evidence side by side" },
  { id: "wide", label: "Evidence", hint: "Wide evidence with source table" },
];

export function EvidencePresets({
  active,
  onPreset,
  onCollapse,
}: {
  active: Preset | null;
  onPreset: (preset: Preset) => void;
  onCollapse: () => void;
}) {
  return (
    <div className="evidence-layout-bar">
      <div
        className="evidence-presets"
        role="group"
        aria-label="Evidence panel width"
      >
        {PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            aria-pressed={active === preset.id}
            title={preset.hint}
            onClick={() => onPreset(preset.id)}
          >
            <i data-preset={preset.id} aria-hidden="true" />
            {preset.label}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="evidence-collapse"
        onClick={onCollapse}
        aria-label="Hide evidence panel"
        title="Hide evidence panel"
      >
        <Icon name="close" size={14} />
      </button>
    </div>
  );
}

export type SourceRow = {
  id: string;
  title: string;
  url: string | undefined;
  domain: string;
  citation: number | null;
  publisher: string | null;
  publishedAt: string | null;
  kind: string;
  repeated: boolean;
  extracts: { id: string; quote: string; verified: boolean }[];
};

type Sort = "citation" | "title" | "newest";
type Column = "extract" | "assessment";

const SHOW_KEY = "hogskin.sourceTable";

function dateText(value: string | null) {
  if (!value) return "Date unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unknown"
    : new Intl.DateTimeFormat(undefined, {
        year: "numeric",
        month: "short",
      }).format(date);
}

export function sortSources(rows: SourceRow[], sort: Sort) {
  const time = (row: SourceRow) => {
    const value = row.publishedAt ? Date.parse(row.publishedAt) : NaN;
    return Number.isNaN(value) ? -Infinity : value;
  };
  return [...rows].sort((a, b) =>
    sort === "title"
      ? a.title.localeCompare(b.title)
      : sort === "newest"
        ? time(b) - time(a)
        : (a.citation ?? Infinity) - (b.citation ?? Infinity),
  );
}

export function SourcesTable({
  rows,
  activeSource,
  onSelect,
}: {
  rows: SourceRow[];
  activeSource: string | null;
  onSelect: (id: string) => void;
}) {
  const [sort, setSort] = useState<Sort>("citation");
  const [limit, setLimit] = useState(10);
  const [hidden, setHidden] = useState<Column[]>([]);
  useEffect(() => {
    try {
      const saved = JSON.parse(
        window.localStorage.getItem(SHOW_KEY) ?? "{}",
      ) as { hidden?: unknown };
      if (Array.isArray(saved.hidden))
        setHidden(
          saved.hidden.filter(
            (item): item is Column =>
              item === "extract" || item === "assessment",
          ),
        );
    } catch {
      // Ignore malformed preferences.
    }
  }, []);
  function toggle(column: Column) {
    setHidden((current) => {
      const next = current.includes(column)
        ? current.filter((item) => item !== column)
        : [...current, column];
      try {
        window.localStorage.setItem(SHOW_KEY, JSON.stringify({ hidden: next }));
      } catch {
        // Preference only.
      }
      return next;
    });
  }
  const sorted = useMemo(() => sortSources(rows, sort), [rows, sort]);
  const shown = limit ? sorted.slice(0, limit) : sorted;
  const show = (column: Column) => !hidden.includes(column);
  return (
    <div className="source-table-view">
      <div className="source-table-tools">
        <label className="answer-select">
          <span>Sort</span>
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as Sort)}
            aria-label="Sort sources"
          >
            <option value="citation">Citation order</option>
            <option value="title">Title</option>
            <option value="newest">Newest first</option>
          </select>
        </label>
        <label className="answer-select">
          <span>Show</span>
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            aria-label="Sources shown"
          >
            <option value={10}>10</option>
            <option value={25}>25</option>
            <option value={0}>All</option>
          </select>
        </label>
        <div className="source-table-columns" role="group" aria-label="Columns">
          {(
            [
              ["extract", "Relevant extract"],
              ["assessment", "Assessment"],
            ] as const
          ).map(([column, label]) => (
            <button
              key={column}
              type="button"
              aria-pressed={show(column)}
              onClick={() => toggle(column)}
            >
              <Icon name={show(column) ? "check" : "plus"} size={12} />
              {label}
            </button>
          ))}
        </div>
      </div>
      <div
        className="source-table-wrap"
        role="region"
        aria-label="Source comparison table"
        tabIndex={0}
      >
        <table className="source-table">
          <thead>
            <tr>
              <th scope="col" className="source-table-num">
                #
              </th>
              <th scope="col">Source</th>
              {show("extract") && <th scope="col">Relevant extract</th>}
              {show("assessment") && <th scope="col">Assessment</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, index) => (
              <tr
                key={row.id}
                data-selected={activeSource === row.id || undefined}
                style={{ "--i": Math.min(index, 12) } as CSSProperties}
              >
                <td className="source-table-num">
                  {row.citation ? (
                    <span className="source-table-cite">{row.citation}</span>
                  ) : (
                    <span className="source-table-uncited">-</span>
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="source-table-title"
                    aria-pressed={activeSource === row.id}
                    onClick={() => onSelect(row.id)}
                  >
                    {row.title}
                  </button>
                  <span className="source-table-meta">
                    <span>{row.domain}</span>
                    {row.publisher && row.publisher !== row.domain && (
                      <span>{row.publisher}</span>
                    )}
                    <span>{dateText(row.publishedAt)}</span>
                    <a
                      href={row.url}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Open ${row.title} in a new tab`}
                    >
                      <Icon name="external" size={12} />
                    </a>
                  </span>
                </td>
                {show("extract") && (
                  <td className="source-table-extract">
                    {row.extracts[0] ? (
                      <>
                        <q>{row.extracts[0].quote}</q>
                        <span className="source-table-flags">
                          <span
                            data-verified={
                              row.extracts[0].verified || undefined
                            }
                          >
                            {row.extracts[0].verified
                              ? "Exact passage"
                              : "Match not recorded"}
                          </span>
                          {row.extracts.length > 1 && (
                            <span>+{row.extracts.length - 1} more</span>
                          )}
                        </span>
                      </>
                    ) : (
                      <span className="source-table-none">
                        Not quoted in the answer
                      </span>
                    )}
                  </td>
                )}
                {show("assessment") && (
                  <td>
                    <span className="source-table-assess">
                      <span>{row.kind}</span>
                      <span data-cited={row.citation ? true : undefined}>
                        {row.citation ? "Cited in brief" : "Collected"}
                      </span>
                      {row.repeated && <span data-warn>Repeated material</span>}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length < sorted.length && (
        <button
          type="button"
          className="source-table-more"
          onClick={() => setLimit(0)}
        >
          Show all {sorted.length} sources
        </button>
      )}
    </div>
  );
}
