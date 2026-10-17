"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Icon } from "./ui";
import "../report-actions.css";

type Format = "markdown" | "bibtex";

type ExportResponse = {
  id: string;
  downloadPath: string;
  reportVersion?: number;
  sizeBytes?: number;
  sha256?: string;
};

type ShareSummary = {
  id: string;
  createdAt?: string;
  expiresAt: string;
  revokedAt: string | null;
};

type Receipt = {
  format: Format;
  version?: number | undefined;
  sizeBytes?: number | undefined;
  sha256?: string | undefined;
};

const FORMATS: {
  format: Format;
  label: string;
  extension: string;
  detail: string;
}[] = [
  {
    format: "markdown",
    label: "Markdown",
    extension: ".md",
    detail: "Report text with citations",
  },
  {
    format: "bibtex",
    label: "BibTeX",
    extension: ".bib",
    detail: "Cited sources for a reference manager",
  },
];

const PANEL_WIDTH = 368;

function expiryLabel(expiresAt: string) {
  const ms = Date.parse(expiresAt) - Date.now();
  const hours = Math.max(1, Math.round(ms / 3_600_000));
  const relative =
    hours < 24
      ? `in ${hours} ${hours === 1 ? "hour" : "hours"}`
      : `in ${Math.round(hours / 24)} ${Math.round(hours / 24) === 1 ? "day" : "days"}`;
  return {
    relative,
    absolute: new Date(expiresAt).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }),
  };
}

function sizeLabel(bytes: number) {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

export function ReportActions({ reportId }: { reportId: string }) {
  const [busy, setBusy] = useState<
    "share" | Format | `revoke:${string}` | null
  >(null);
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState<"info" | "success" | "error">("info");
  const [shares, setShares] = useState<ShareSummary[]>([]);
  const [shareUrl, setShareUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const linkInput = useRef<HTMLInputElement>(null);
  const id = useId();
  const panelId = `report-share-${id.replaceAll(":", "")}`;

  // Busy controls are disabled, which would drop keyboard focus to the page
  // and break the popover's focus return. Park focus on the panel instead.
  const holdFocus = () => {
    if (panel.current?.contains(document.activeElement))
      panel.current.focus({ preventScroll: true });
  };

  const report = (text: string, nextTone: typeof tone) => {
    setMessage(text);
    setTone(nextTone);
  };

  const refreshShares = useCallback(async () => {
    try {
      const response = await fetch(`/api/research/reports/${reportId}/shares`, {
        cache: "no-store",
      });
      if (!response.ok) return;
      const body: unknown = await response.json();
      setShares(Array.isArray(body) ? (body as ShareSummary[]) : []);
    } catch {
      // Share management remains available through creating/revoking actions.
    }
  }, [reportId]);

  useEffect(() => {
    void refreshShares();
  }, [refreshShares]);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  // The panel lives in the top layer, so it is placed against the trigger
  // before it opens and kept there while the page scrolls or resizes.
  useEffect(() => {
    const element = panel.current;
    if (!element) return;
    const place = () => {
      const anchor = trigger.current?.getBoundingClientRect();
      if (!anchor) return;
      const width = Math.min(PANEL_WIDTH, window.innerWidth - 16);
      const left = Math.min(
        Math.max(8, anchor.right - width),
        window.innerWidth - width - 8,
      );
      element.style.setProperty("--share-top", `${anchor.bottom + 8}px`);
      element.style.setProperty("--share-left", `${left}px`);
    };
    const onBeforeToggle = (event: Event) => {
      if ((event as Event & { newState?: string }).newState !== "open") return;
      place();
      setOpen(true);
      void refreshShares();
      window.addEventListener("resize", place);
      window.addEventListener("scroll", place, true);
    };
    const onToggle = (event: Event) => {
      if ((event as Event & { newState?: string }).newState === "open") return;
      setOpen(false);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
    element.addEventListener("beforetoggle", onBeforeToggle);
    element.addEventListener("toggle", onToggle);
    return () => {
      element.removeEventListener("beforetoggle", onBeforeToggle);
      element.removeEventListener("toggle", onToggle);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [refreshShares]);

  async function createShare() {
    holdFocus();
    setBusy("share");
    setMessage("");
    setCopied(false);
    try {
      const response = await fetch(`/api/research/reports/${reportId}/shares`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ expiresInHours: 168 }),
      });
      const body = (await response.json()) as {
        sharePath?: string;
        error?: string;
      };
      if (!response.ok || !body.sharePath)
        throw new Error(body.error ?? "A share link could not be created.");
      const url = new URL(body.sharePath, window.location.origin).toString();
      setShareUrl(url);
      try {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        report("Private link copied. It expires in 7 days.", "success");
      } catch {
        report(
          "Share link created. Copy it below; it expires in 7 days.",
          "info",
        );
        requestAnimationFrame(() => linkInput.current?.select());
      }
      await refreshShares();
    } catch (error) {
      report(
        error instanceof Error
          ? error.message
          : "Could not create the share link.",
        "error",
      );
    } finally {
      setBusy(null);
    }
  }

  async function revokeShare(shareId: string) {
    holdFocus();
    setBusy(`revoke:${shareId}`);
    try {
      const response = await fetch(
        `/api/research/reports/${reportId}/shares/${shareId}/revoke`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{}",
        },
      );
      if (!response.ok) throw new Error("This share could not be revoked.");
      await refreshShares();
      report("Share link revoked. New visits are blocked.", "success");
    } catch (error) {
      report(
        error instanceof Error ? error.message : "Could not revoke this link.",
        "error",
      );
    } finally {
      setBusy(null);
    }
  }

  async function copyShareUrl() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      report("Share link copied.", "success");
    } catch {
      linkInput.current?.select();
      report(
        "Clipboard access is unavailable. Select and copy the link above.",
        "info",
      );
    }
  }

  async function exportReport(format: Format) {
    holdFocus();
    setBusy(format);
    setMessage("");
    setReceipt(null);
    try {
      const created = await fetch(`/api/research/reports/${reportId}/exports`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ format }),
      });
      const data = (await created.json()) as ExportResponse & {
        error?: string;
      };
      if (!created.ok || !data.downloadPath)
        throw new Error(data.error ?? `Could not prepare ${format} export.`);
      const download = await fetch(data.downloadPath, { cache: "no-store" });
      if (!download.ok)
        throw new Error("The saved export could not be downloaded.");
      const blob = await download.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `research-${reportId}.${format === "markdown" ? "md" : "bib"}`;
      anchor.click();
      URL.revokeObjectURL(objectUrl);
      setReceipt({
        format,
        version: data.reportVersion,
        sizeBytes: data.sizeBytes,
        sha256: data.sha256,
      });
      report(
        `${format === "markdown" ? "Markdown" : "BibTeX"} export downloaded.`,
        "success",
      );
    } catch (error) {
      report(
        error instanceof Error ? error.message : "Export failed. Please retry.",
        "error",
      );
    } finally {
      setBusy(null);
    }
  }

  const activeShares = shares
    .filter(
      (share) => !share.revokedAt && Date.parse(share.expiresAt) > Date.now(),
    )
    .sort((a, b) => Date.parse(b.expiresAt) - Date.parse(a.expiresAt));
  const closedShares = shares.length - activeShares.length;

  return (
    <div className="report-actions">
      <button
        ref={trigger}
        type="button"
        className="text-button toolbar-action share-trigger"
        popoverTarget={panelId}
        aria-haspopup="dialog"
        aria-label="Share and export report"
        data-open={open || undefined}
      >
        <Icon name="link" size={16} />
        <span className="toolbar-label">Share</span>
        {activeShares.length > 0 && (
          <span className="share-trigger__count" aria-hidden="true">
            {activeShares.length}
          </span>
        )}
      </button>
      <div
        ref={panel}
        id={panelId}
        popover="auto"
        role="dialog"
        tabIndex={-1}
        aria-labelledby={`${panelId}-title`}
        className="share-pop"
      >
        <header className="share-pop__head">
          <div>
            <h2 id={`${panelId}-title`}>Share and export</h2>
            <p>Links open this exact version, read-only. Revoke any time.</p>
          </div>
          <button
            type="button"
            className="share-pop__close"
            popoverTarget={panelId}
            popoverTargetAction="hide"
            aria-label="Close share and export"
          >
            <Icon name="close" size={14} />
          </button>
        </header>

        <section
          className="share-pop__section"
          aria-labelledby={`${panelId}-links`}
        >
          <div className="share-pop__row">
            <h3 id={`${panelId}-links`}>Private link</h3>
            <button
              type="button"
              className="share-pop__primary"
              onClick={() => void createShare()}
              disabled={busy !== null}
              data-busy={busy === "share" || undefined}
            >
              {busy === "share" && (
                <span className="share-pop__spinner" aria-hidden="true" />
              )}
              {busy === "share"
                ? "Creating link…"
                : shareUrl
                  ? "New link"
                  : "Create link"}
            </button>
          </div>
          {shareUrl && (
            <div className="share-pop__link">
              <label htmlFor={`share-link-${reportId}`}>
                Copyable, expiring share link
              </label>
              <div className="share-pop__field">
                <input
                  ref={linkInput}
                  id={`share-link-${reportId}`}
                  readOnly
                  value={shareUrl}
                  onFocus={(event) => event.currentTarget.select()}
                />
                <button
                  type="button"
                  className="share-pop__copy"
                  onClick={() => void copyShareUrl()}
                  data-copied={copied || undefined}
                  aria-label={copied ? "Link copied" : "Copy link"}
                >
                  <Icon name={copied ? "check" : "copy"} size={14} />
                  <span>{copied ? "Copied" : "Copy"}</span>
                </button>
              </div>
            </div>
          )}
          {activeShares.length ? (
            <ul className="share-pop__list" aria-label="Active share links">
              {activeShares.map((share) => {
                const expiry = expiryLabel(share.expiresAt);
                const revoking = busy === `revoke:${share.id}`;
                return (
                  <li key={share.id} data-revoking={revoking || undefined}>
                    <span className="share-pop__live" aria-hidden="true" />
                    <span className="share-pop__expiry">
                      <strong>Expires {expiry.relative}</strong>
                      <small>{expiry.absolute}</small>
                    </span>
                    <button
                      type="button"
                      className="share-pop__revoke"
                      onClick={() => void revokeShare(share.id)}
                      disabled={busy !== null}
                      aria-label={`Revoke share link expiring ${new Date(share.expiresAt).toLocaleDateString()}`}
                    >
                      {revoking ? "Revoking…" : "Revoke"}
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="share-pop__empty">
              No active links. New links expire after 7 days.
            </p>
          )}
          {closedShares > 0 && (
            <p className="share-pop__footnote">
              {closedShares} revoked or expired{" "}
              {closedShares === 1
                ? "link no longer opens"
                : "links no longer open"}
              .
            </p>
          )}
        </section>

        <section
          className="share-pop__section"
          aria-labelledby={`${panelId}-export`}
        >
          <h3 id={`${panelId}-export`}>Export</h3>
          <div className="share-pop__formats">
            {FORMATS.map((item) => {
              const preparing = busy === item.format;
              const done = receipt?.format === item.format;
              return (
                <button
                  key={item.format}
                  type="button"
                  className="share-pop__format"
                  onClick={() => void exportReport(item.format)}
                  disabled={busy !== null}
                  data-state={preparing ? "busy" : done ? "done" : undefined}
                  aria-label={`Export ${item.label}`}
                >
                  <span className="share-pop__ext" aria-hidden="true">
                    {item.extension}
                  </span>
                  <span className="share-pop__format-text">
                    <strong>{preparing ? "Preparing…" : item.label}</strong>
                    <small>{item.detail}</small>
                  </span>
                  <span className="share-pop__format-icon" aria-hidden="true">
                    {preparing ? (
                      <span className="share-pop__spinner" />
                    ) : (
                      <Icon name={done ? "check" : "download"} size={15} />
                    )}
                  </span>
                </button>
              );
            })}
          </div>
          {receipt && (
            <p className="share-pop__receipt">
              {[
                receipt.version != null && `Version ${receipt.version}`,
                receipt.sizeBytes != null && sizeLabel(receipt.sizeBytes),
                receipt.sha256 &&
                  `SHA-256 ${receipt.sha256.slice(0, 8)}…${receipt.sha256.slice(-4)}`,
              ]
                .filter(Boolean)
                .join(" · ")}
              <span>Checksum verified on download</span>
            </p>
          )}
        </section>

        <p
          className="share-pop__status"
          role="status"
          aria-live="polite"
          data-tone={message ? tone : undefined}
        >
          {message}
        </p>
      </div>
    </div>
  );
}
