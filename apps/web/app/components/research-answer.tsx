"use client";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  CITATION_STYLES,
  formatReference,
  isCitationStyle,
  referenceText,
  siteName,
  type CitationStyle,
  type ReferenceInput,
} from "../../lib/citation-format";
import { methodSummary } from "../../lib/research-method";
import {
  chartDomain,
  chartSeries,
  formatValue,
  tableRows,
  toCsv,
  toTsv,
  type ChartSeries,
  type HastLike,
} from "../../lib/report-table";
import { Icon } from "./ui";
import "../research-answer.css";

const STYLE_KEY = "hogskin.citationStyle";

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Shows "Copied" briefly; returns false-y feedback when the clipboard is blocked. */
function useCopied() {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return [
    state,
    async (text: string) => {
      setState((await copyText(text)) ? "copied" : "failed");
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setState("idle"), 1600);
    },
  ] as const;
}

export type CitationPreviewData = {
  title: string;
  site: string;
  kind: string;
  published: string | null;
  quote: string | null;
  verified: boolean;
  claims: number;
};

type Placement = {
  left: number;
  width: number;
  top?: number;
  bottom?: number;
  above: boolean;
};

/**
 * One shared hover card for every inline citation. It listens by delegation so
 * hovering never re-renders the report; the card is a tooltip, not a dialog.
 */
export function CitationPreview({
  root,
  resolve,
}: {
  root: RefObject<HTMLElement | null>;
  resolve: (reference: number) => CitationPreviewData | null;
}) {
  const [data, setData] = useState<CitationPreviewData | null>(null);
  const [reference, setReference] = useState(0);
  const [place, setPlace] = useState<Placement | null>(null);
  const [open, setOpen] = useState(false);
  const resolver = useRef(resolve);
  resolver.current = resolve;

  useEffect(() => {
    const host = root.current;
    if (!host) return;
    let timer: number | undefined;
    let current: HTMLElement | null = null;
    let shown = false;
    const chipOf = (target: EventTarget | null) =>
      target instanceof Element
        ? target.closest<HTMLElement>(".citation-chip[data-ref]")
        : null;
    const hide = () => {
      window.clearTimeout(timer);
      current?.removeAttribute("aria-describedby");
      current = null;
      shown = false;
      setOpen(false);
    };
    const show = (chip: HTMLElement) => {
      const number = Number(chip.dataset.ref);
      const next = resolver.current(number);
      if (!next) return hide();
      const rect = chip.getBoundingClientRect();
      const width = Math.min(340, window.innerWidth - 24);
      const left = Math.min(
        Math.max(12, rect.left + rect.width / 2 - width / 2),
        window.innerWidth - width - 12,
      );
      const above = window.innerHeight - rect.bottom < 280;
      current?.removeAttribute("aria-describedby");
      current = chip;
      chip.setAttribute("aria-describedby", "citation-preview");
      shown = true;
      setData(next);
      setReference(number);
      setPlace(
        above
          ? { left, width, bottom: window.innerHeight - rect.top + 8, above }
          : { left, width, top: rect.bottom + 8, above },
      );
      setOpen(true);
    };
    const over = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const chip = chipOf(event.target);
      if (!chip || chip === current) return;
      window.clearTimeout(timer);
      // Once one card is open, moving along a citation group swaps instantly.
      timer = window.setTimeout(() => show(chip), shown ? 0 : 220);
    };
    const out = (event: PointerEvent) => {
      const chip = chipOf(event.target);
      if (!chip || chip.contains(event.relatedTarget as Node | null)) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(hide, 120);
    };
    const focus = (event: FocusEvent) => {
      const chip = chipOf(event.target);
      if (chip?.matches(":focus-visible")) show(chip);
    };
    const blur = (event: FocusEvent) => {
      if (chipOf(event.target)) hide();
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape" && shown) hide();
    };
    // Scrolling moves an open card off its chip; a pending one measures on open.
    const scrolled = () => {
      if (shown) hide();
    };
    host.addEventListener("pointerover", over);
    host.addEventListener("pointerout", out);
    host.addEventListener("focusin", focus);
    host.addEventListener("focusout", blur);
    host.addEventListener("click", hide);
    host.addEventListener("scroll", scrolled, { passive: true });
    window.addEventListener("resize", hide);
    document.addEventListener("keydown", key);
    return () => {
      window.clearTimeout(timer);
      current?.removeAttribute("aria-describedby");
      host.removeEventListener("pointerover", over);
      host.removeEventListener("pointerout", out);
      host.removeEventListener("focusin", focus);
      host.removeEventListener("focusout", blur);
      host.removeEventListener("click", hide);
      host.removeEventListener("scroll", scrolled);
      window.removeEventListener("resize", hide);
      document.removeEventListener("keydown", key);
    };
  }, [root]);

  if (!data || !place) return null;
  return createPortal(
    <div
      id="citation-preview"
      role="tooltip"
      className="cite-card"
      data-open={open}
      data-above={place.above}
      style={{
        left: place.left,
        width: place.width,
        top: place.top,
        bottom: place.bottom,
      }}
    >
      <div className="cite-card-meta">
        <span className="cite-card-monogram" aria-hidden="true">
          {data.site.charAt(0).toUpperCase() || "S"}
        </span>
        <span className="cite-card-site">{data.site || "Source"}</span>
        <span className="cite-card-ref">[{reference}]</span>
      </div>
      <strong className="cite-card-title">{data.title}</strong>
      <p className="cite-card-facts">
        {[data.kind, data.published].filter(Boolean).join(" · ")}
      </p>
      {data.quote ? (
        <figure className="cite-card-quote" data-verified={data.verified}>
          <figcaption>
            {data.verified ? (
              <>
                <Icon name="check" size={12} /> Exact passage matched
              </>
            ) : (
              "Quoted passage · match not recorded"
            )}
          </figcaption>
          <blockquote>{data.quote}</blockquote>
        </figure>
      ) : (
        <p className="cite-card-empty">
          No quoted passage was recorded for this source.
        </p>
      )}
      <p className="cite-card-hint">
        {data.claims > 0 &&
          `Supports ${data.claims} published ${data.claims === 1 ? "claim" : "claims"} · `}
        Click to inspect
      </p>
    </div>,
    document.body,
  );
}

/** Tables keep their scroll region and gain a copy-as-TSV action. */
function downloadText(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function ReportChart({
  series,
  caption,
}: {
  series: ChartSeries[];
  caption: string;
}) {
  const [index, setIndex] = useState(0);
  const active = series[Math.min(index, series.length - 1)];
  if (!active) return null;
  const { min, max } = chartDomain(active.points.map((point) => point.value));
  const span = max - min;
  const zero = (-min / span) * 100;
  return (
    <div className="report-chart">
      <div className="report-chart-head">
        <p id={`${caption}-title`}>
          {active.name}
          {active.unit && active.unit !== "%" ? ` (${active.unit})` : ""}
        </p>
        {series.length > 1 && (
          <label className="answer-select">
            <span className="sr-only">Chart metric</span>
            <select
              value={index}
              onChange={(event) => setIndex(Number(event.target.value))}
            >
              {series.map((item, i) => (
                <option key={item.name + i} value={i}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <ol
        key={index}
        className="report-chart-bars"
        aria-labelledby={`${caption}-title`}
        style={{ "--zero": `${zero}%` } as CSSProperties}
      >
        {active.points.map((point, i) => {
          const size = (Math.abs(point.value) / span) * 100;
          const negative = point.value < 0;
          return (
            <li
              key={point.label + i}
              style={{ "--i": i } as CSSProperties}
              data-negative={negative || undefined}
            >
              <span className="report-chart-label">{point.label}</span>
              <span className="report-chart-track" aria-hidden="true">
                <span
                  className="report-chart-bar"
                  style={{
                    left: `${negative ? zero - size : zero}%`,
                    width: `${Math.max(size, 0.4)}%`,
                  }}
                />
              </span>
              <span className="report-chart-value">
                {formatValue(point.value, active.unit)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="report-chart-note">
        Values as reported in the table. Bars start at zero.
      </p>
    </div>
  );
}

export function ReportTable({
  children,
  node,
}: {
  children: ReactNode;
  node?: HastLike | undefined;
}) {
  const table = useRef<HTMLTableElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const id = useId();
  const [state, copy] = useCopied();
  const [view, setView] = useState<"table" | "chart">("table");
  const [expanded, setExpanded] = useState(false);
  const rows = useMemo(() => tableRows(node), [node]);
  const series = useMemo(() => chartSeries(tableRows(node, false)), [node]);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (expanded && !element.open) element.showModal();
    if (!expanded && element.open) element.close();
  }, [expanded]);
  function domRows() {
    return Array.from(table.current?.rows ?? [], (row) =>
      Array.from(row.cells, (cell) => {
        const clone = cell.cloneNode(true) as HTMLElement;
        clone
          .querySelectorAll(".citation-chip")
          .forEach((chip) => chip.replaceWith(`[${chip.textContent}]`));
        return (clone.textContent ?? "").replace(/\s+/g, " ").trim();
      }),
    );
  }
  const data = () => (rows.length ? rows : domRows());
  const body = (
    <div
      className="report-table-wrap"
      tabIndex={0}
      role="region"
      aria-label="Research comparison table"
    >
      <table ref={table}>{children}</table>
    </div>
  );
  return (
    <figure className="report-table" data-view={view}>
      <div className="report-table-bar">
        {series.length ? (
          <div
            className="report-table-switch"
            role="group"
            aria-label="Table view"
          >
            {(["table", "chart"] as const).map((item) => (
              <button
                key={item}
                type="button"
                aria-pressed={view === item}
                onClick={() => setView(item)}
              >
                {item === "table" ? "Table" : "Chart"}
              </button>
            ))}
          </div>
        ) : (
          <span>Table</span>
        )}
        <div className="report-table-tools">
          <button
            type="button"
            className="answer-ghost"
            onClick={() => void copy(toTsv(data()))}
            aria-label="Copy table"
          >
            <Icon name={state === "copied" ? "check" : "copy"} size={14} />
            <span aria-live="polite">
              {state === "copied"
                ? "Copied"
                : state === "failed"
                  ? "Copy unavailable"
                  : "Copy"}
            </span>
          </button>
          <button
            type="button"
            className="answer-ghost"
            onClick={() =>
              downloadText(
                "\ufeff" + toCsv(data()),
                "hogskin-table.csv",
                "text/csv;charset=utf-8",
              )
            }
            aria-label="Download table as CSV"
          >
            <Icon name="download" size={14} />
            <span>CSV</span>
          </button>
          <button
            type="button"
            className="answer-icon"
            onClick={() => setExpanded(true)}
            aria-label="Expand table"
            aria-haspopup="dialog"
          >
            <Icon name="columns" size={14} />
          </button>
        </div>
      </div>
      {view === "chart" && series.length ? (
        <ReportChart series={series} caption={id} />
      ) : (
        body
      )}
      <dialog
        ref={dialog}
        className="report-table-dialog"
        aria-label="Expanded table"
        onClose={() => setExpanded(false)}
        onClick={(event) => {
          if (
            event.target === event.currentTarget ||
            (event.target as HTMLElement).closest(".citation-chip")
          )
            setExpanded(false);
        }}
      >
        {expanded && (
          <div className="report-table-dialog-body">
            <header>
              <p>Table</p>
              <button
                type="button"
                className="answer-icon"
                onClick={() => setExpanded(false)}
                aria-label="Close expanded table"
                autoFocus
              >
                <Icon name="close" size={16} />
              </button>
            </header>
            <div className="report-table-wrap" tabIndex={0}>
              <table>{children}</table>
            </div>
            {series.length > 0 && (
              <ReportChart series={series} caption={`${id}-expanded`} />
            )}
          </div>
        )}
      </dialog>
    </figure>
  );
}

export type ReferenceRow = ReferenceInput & { sourceId?: string | undefined };

export function ReferenceList({
  references,
  onOpen,
}: {
  references: ReferenceRow[];
  onOpen: (number: number, origin: HTMLButtonElement) => void;
}) {
  const [style, setStyle] = useState<CitationStyle>("apa");
  const [all, copyAll] = useCopied();
  const [copiedRow, setCopiedRow] = useState<number | null>(null);
  const rowTimer = useRef<number | undefined>(undefined);
  useEffect(() => {
    const saved = window.localStorage.getItem(STYLE_KEY);
    if (isCitationStyle(saved)) setStyle(saved);
    return () => window.clearTimeout(rowTimer.current);
  }, []);
  if (!references.length) return null;
  const formatted = references.map((reference) => ({
    reference,
    parts: formatReference(reference, style),
  }));
  return (
    <section className="answer-references" aria-labelledby="answer-refs">
      <header>
        <h2 id="answer-refs">References</h2>
        <div className="answer-references-tools">
          <label className="answer-select">
            <span className="sr-only">Citation style</span>
            <Icon name="quote" size={14} />
            <select
              value={style}
              onChange={(event) => {
                const next = event.target.value;
                if (!isCitationStyle(next)) return;
                setStyle(next);
                window.localStorage.setItem(STYLE_KEY, next);
              }}
            >
              {CITATION_STYLES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="answer-ghost"
            onClick={() =>
              void copyAll(
                formatted
                  .map(({ parts, reference }) =>
                    style === "ieee"
                      ? referenceText(parts)
                      : `${reference.number}. ${referenceText(parts)}`,
                  )
                  .join("\n"),
              )
            }
          >
            <Icon name={all === "copied" ? "check" : "copy"} size={14} />
            <span aria-live="polite">
              {all === "copied"
                ? "Copied"
                : all === "failed"
                  ? "Copy unavailable"
                  : "Copy all"}
            </span>
          </button>
        </div>
      </header>
      <p className="answer-references-note">
        Formatted from recorded metadata. Authors are not collected, so the
        publisher or site stands in as author. Check before submission.
      </p>
      <ol>
        {formatted.map(({ reference, parts }) => (
          <li key={reference.number}>
            <button
              type="button"
              className="answer-ref-number"
              aria-label={`Inspect reference ${reference.number}`}
              disabled={!reference.sourceId}
              onClick={(event) => onOpen(reference.number, event.currentTarget)}
            >
              {reference.number}
            </button>
            <p>
              {parts.map((part, index) =>
                part.em ? (
                  <em key={index}>{part.text}</em>
                ) : (
                  // The number button already shows IEEE's "[n]" label.
                  <span key={index}>
                    {index === 0
                      ? part.text.replace(/^\[\d+\]\s*/, "")
                      : part.text}
                  </span>
                ),
              )}
            </p>
            <button
              type="button"
              className="answer-icon"
              aria-label={`Copy reference ${reference.number}`}
              onClick={async () => {
                const ok = await copyText(referenceText(parts));
                setCopiedRow(ok ? reference.number : null);
                window.clearTimeout(rowTimer.current);
                rowTimer.current = window.setTimeout(
                  () => setCopiedRow(null),
                  1600,
                );
              }}
            >
              <Icon
                name={copiedRow === reference.number ? "check" : "copy"}
                size={14}
              />
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

type MethodProps = {
  sources: Parameters<typeof methodSummary>[0];
  subQuestions: Parameters<typeof methodSummary>[1];
  calls: number;
  callLimit: number;
  inspect: (sourceId: string) => void;
  statusLabel: (status: string) => ReactNode;
};

export function MethodSummary({
  sources,
  subQuestions,
  calls,
  callLimit,
  inspect,
  statusLabel,
}: MethodProps) {
  const summary = methodSummary(sources, subQuestions);
  const order = summary.providers.map((provider) => provider.id);
  const dot = (id: string) =>
    ({
      "--dot": `var(--provider-${Math.max(order.indexOf(id), 0) % 4})`,
    }) as CSSProperties;
  return (
    <section className="method-summary" aria-labelledby="method-searches">
      <header>
        <h3 id="method-searches">
          <Icon name="search" size={15} />
          Searches the agents ran
        </h3>
        <span>
          {subQuestions.length}{" "}
          {subQuestions.length === 1 ? "question" : "questions"} ·{" "}
          {sources.length} {sources.length === 1 ? "source" : "sources"}
        </span>
      </header>
      <dl className="method-stats">
        <div>
          <dt>Provider calls</dt>
          <dd>
            {calls}
            <small> / {callLimit}</small>
          </dd>
        </div>
        <div>
          <dt>{summary.providers.length === 1 ? "Provider" : "Providers"}</dt>
          <dd>{summary.providers.length}</dd>
        </div>
        <div>
          <dt>Sources kept</dt>
          <dd>{sources.length}</dd>
        </div>
      </dl>
      {summary.providers.length > 0 && (
        <ul className="method-providers" aria-label="Sources by provider">
          {summary.providers.map((provider) => (
            <li key={provider.id} data-provider={provider.id}>
              <i aria-hidden="true" style={dot(provider.id)} />
              {provider.label}
              <strong>{provider.count}</strong>
            </li>
          ))}
        </ul>
      )}
      {summary.questions.length ? (
        <ol className="method-questions">
          {summary.questions.map((item, index) => (
            <li key={item.id}>
              <details>
                <summary>
                  <span className="method-index">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="method-question">
                    <strong>{item.question}</strong>
                    <span className="method-chips">
                      {item.providers.map((provider) => (
                        <span key={provider.id} data-provider={provider.id}>
                          <i aria-hidden="true" style={dot(provider.id)} />
                          {provider.label}
                          <b>{provider.count}</b>
                        </span>
                      ))}
                      {statusLabel(item.status)}
                    </span>
                  </span>
                  <span className="method-count">
                    {item.sources.length}{" "}
                    {item.sources.length === 1 ? "source" : "sources"}
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="m6 4 4 4-4 4" />
                    </svg>
                  </span>
                </summary>
                {item.sources.length ? (
                  <ul className="method-source-list">
                    {item.sources.map((source) => (
                      <li key={source.id}>
                        <button
                          type="button"
                          onClick={() => inspect(source.id)}
                        >
                          <span>{source.title || siteName(source.url)}</span>
                          <small>{siteName(source.url)}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="method-none">
                    No kept source is attributed to this question.
                  </p>
                )}
              </details>
            </li>
          ))}
        </ol>
      ) : (
        <p className="panel-empty">No research plan has been recorded yet.</p>
      )}
      {summary.unattributed > 0 && (
        <p className="method-footnote">
          {summary.unattributed}{" "}
          {summary.unattributed === 1 ? "source has" : "sources have"} no
          recorded discovery path to a plan question.
        </p>
      )}
    </section>
  );
}

export function FollowupSuggestions({
  suggestions,
  disabled,
  choose,
}: {
  suggestions: string[];
  disabled: boolean;
  choose: (question: string) => void;
}) {
  if (!suggestions.length) return null;
  return (
    <div className="answer-followups" role="group" aria-label="Follow-up">
      <span>Follow-up</span>
      <ul>
        {suggestions.map((question, index) => (
          <li key={question} style={{ "--i": index } as CSSProperties}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => choose(question)}
            >
              <Icon name="spark" size={14} />
              <span>{question}</span>
              <Icon name="arrow" size={14} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
