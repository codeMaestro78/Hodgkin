"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  Empty,
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
  SheetClose,
  Skeleton,
} from "./workbench-ui";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Brand, dateLabel, Icon } from "./ui";
import { useEntrance } from "./workspace-motion";
import {
  patchResearchHistory,
  subscribeResearchHistorySnapshots,
  type ResearchHistorySnapshot,
} from "../../lib/research-history-events";

export type HistoryRun = {
  runId: string;
  question: string;
  status: string;
  sourceCount: number;
  createdAt: string;
  quickMode: boolean;
};

export function WorkspaceShell({
  children,
  activeRunId,
  title = "Research workspace",
  toolbar,
}: {
  children: ReactNode;
  activeRunId?: string;
  title?: string;
  toolbar?: ReactNode;
}) {
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const [account, setAccount] = useState<{
    name: string;
    email: string;
  } | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [accountError, setAccountError] = useState("");
  const content = useRef<HTMLElement>(null);
  useEntrance(
    content,
    activeRunId ?? "composer",
    ".composer-intro, .composer-bezel, .example-section, .run-opening",
  );

  useEffect(() => {
    const keyboard = () => {
      document.documentElement.dataset.inputModality = "keyboard";
    };
    const pointer = () => {
      document.documentElement.dataset.inputModality = "pointer";
    };
    document.addEventListener("keydown", keyboard, true);
    document.addEventListener("pointerdown", pointer, true);
    return () => {
      document.removeEventListener("keydown", keyboard, true);
      document.removeEventListener("pointerdown", pointer, true);
    };
  }, []);

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1001px)");
    const closeOnDesktop = () => {
      if (desktop.matches) setOpen(false);
    };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // Replay snapshots received during a list request over its older response.
    const snapshots = new Map<string, ResearchHistorySnapshot>();
    const unsubscribe = subscribeResearchHistorySnapshots((snapshot) => {
      if (snapshots.size >= 100 && !snapshots.has(snapshot.runId))
        snapshots.delete(snapshots.keys().next().value!);
      snapshots.set(snapshot.runId, snapshot);
      setHistory((current) => patchResearchHistory(current, snapshot));
    });
    setLoading(true);
    fetch("/api/research/runs", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("History unavailable");
        const body = (await response.json()) as { runs?: HistoryRun[] };
        if (controller.signal.aborted) return;
        let runs = body.runs ?? [];
        for (const snapshot of snapshots.values())
          runs = patchResearchHistory(runs, snapshot);
        setHistory(runs);
        setFailed(false);
      })
      .catch((error) => {
        if (error.name !== "AbortError") setFailed(true);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      unsubscribe();
    };
  }, [activeRunId, historyRevision]);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/session", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (response.status === 401) {
          window.location.assign("/login");
          return;
        }
        if (response.ok) setAccount((await response.json()).user);
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  async function signOut() {
    if (signingOut) return;
    setSigningOut(true);
    setAccountError("");
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Sign-out failed. Please try again.");
      window.location.assign("/login");
    } catch {
      setAccountError("Sign-out failed. Please try again.");
      setSigningOut(false);
    }
  }
  const visible = history.filter((item) =>
    item.question.toLowerCase().includes(filter.toLowerCase()),
  );
  const sidebar = (
    <>
      {" "}
      <div className="sidebar-brand">
        <Brand />
        <button
          className="icon-button mobile-only"
          onClick={() => setOpen(false)}
          aria-label="Close history"
        >
          <Icon name="close" />
        </button>
      </div>
      <Link
        className="new-research"
        href="/research"
        onClick={() => setOpen(false)}
      >
        <Icon name="plus" size={18} />
        New research
      </Link>
      <Link
        className="desk-library-link"
        href="/research/reports"
        aria-current={pathname === "/research/reports" ? "page" : undefined}
        onClick={() => setOpen(false)}
      >
        <Icon name="book" size={17} /> Reports
      </Link>
      <Link
        className="desk-library-link"
        href="/research/automation"
        aria-current={pathname === "/research/automation" ? "page" : undefined}
        onClick={() => setOpen(false)}
      >
        <Icon name="layers" size={17} /> Automation
      </Link>
      <Link
        className="desk-library-link"
        href="/onboarding"
        onClick={() => setOpen(false)}
      >
        <Icon name="book" size={17} /> Research preferences
      </Link>
      <label className="history-search">
        <Icon name="search" size={16} />
        <input
          aria-label="Search research history"
          placeholder="Find research…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </label>
      <div className="history-label">
        <span>Recent research</span>
        <span>{loading ? "…" : history.length}</span>
        <button
          type="button"
          className="icon-button"
          aria-label="Refresh research history"
          disabled={loading}
          onClick={() => setHistoryRevision((revision) => revision + 1)}
        >
          <Icon name="arrow" size={14} />
        </button>
      </div>
      <nav className="history-list" aria-label="Saved research">
        {loading ? (
          <div
            className="history-placeholder"
            role="status"
            aria-label="Loading research history"
          >
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </div>
        ) : failed ? (
          <div className="history-placeholder">
            History couldn’t be loaded. Refresh to try again.
          </div>
        ) : visible.length ? (
          visible.map((item) => (
            <Link
              href={`/research/${item.runId}`}
              key={item.runId}
              aria-current={item.runId === activeRunId ? "page" : undefined}
              onClick={() => setOpen(false)}
            >
              <span className={`history-dot status-${item.status}`} />
              <span>
                <strong>{item.question}</strong>
                <small>
                  {item.sourceCount} sources <span> / </span>
                  {dateLabel(item.createdAt)}
                </small>
              </span>
            </Link>
          ))
        ) : (
          <div className="history-placeholder">
            <Empty
              title={
                filter ? "No matching research" : "Your workspace is ready"
              }
            >
              {filter
                ? "Try a different question or clear the search."
                : "Start a question to build your research history."}
            </Empty>
          </div>
        )}
      </nav>
      <div className="sidebar-bottom">
        <div className="local-avatar">
          <Icon name="layers" size={18} />
        </div>
        <div>
          <strong>{account?.name ?? "Your workspace"}</strong>
          <span>{account?.email ?? "Private research history"}</span>
        </div>
        <button
          className="icon-button"
          onClick={() => void signOut()}
          disabled={signingOut}
          aria-label="Sign out"
        >
          <Icon name="external" size={16} />
        </button>
      </div>
      {accountError && (
        <p className="account-error" role="alert">
          {accountError}
        </p>
      )}
    </>
  );
  return (
    <div
      className={clsx(
        "workspace-shell",
        "evidence-desk",
        collapsed && "sidebar-collapsed",
      )}
    >
      <a className="skip-link" href="#workspace-content">
        Skip to workspace
      </a>
      <aside className="workspace-sidebar" aria-label="Research history">
        {sidebar}
      </aside>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent>
          <SheetTitle className="sr-only">Research history</SheetTitle>
          <div className="desk-mobile-history">{sidebar}</div>
          <SheetClose className="sr-only">Close history</SheetClose>
        </SheetContent>
        <div className="workspace-body">
          <header className="workspace-toolbar">
            <div>
              <SheetTrigger
                className="icon-button mobile-only"
                aria-label="Open research history"
              >
                <Icon name="menu" />
              </SheetTrigger>
              <button
                className="icon-button desktop-only"
                onClick={() => setCollapsed((value) => !value)}
                aria-label={
                  collapsed
                    ? "Expand history sidebar"
                    : "Collapse history sidebar"
                }
                aria-expanded={!collapsed}
              >
                <Icon name="menu" />
              </button>
              <Icon name="book" size={17} />
              <span>{title}</span>
            </div>
            <div className="toolbar-actions">
              {toolbar}
              <Link className="toolbar-home" href="/onboarding">
                Research preferences
              </Link>
              <Link className="toolbar-home" href="/">
                Overview
                <Icon name="external" size={13} />
              </Link>
            </div>
          </header>
          <main
            ref={content}
            id="workspace-content"
            className="workspace-content"
          >
            {children}
          </main>
        </div>
      </Sheet>
    </div>
  );
}
