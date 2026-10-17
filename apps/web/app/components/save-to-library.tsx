"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { LibraryItemSchema } from "@research/contracts";
import { Button } from "./workbench-ui";

export function SaveToLibrary({
  reportId,
  sourceId,
}:
  | { reportId: string; sourceId?: never }
  | { sourceId: string; reportId?: never }) {
  const [state, setState] = useState<"idle" | "saving" | "saved" | "failed">(
    "idle",
  );
  const pending = useRef<AbortController | null>(null);
  const id = reportId ?? sourceId;
  useEffect(() => {
    setState("idle");
    pending.current?.abort();
    pending.current = null;
    return () => {
      pending.current?.abort();
    };
  }, [id]);

  async function save() {
    if (pending.current || state === "saved") return;
    const controller = new AbortController();
    pending.current = controller;
    setState("saving");
    try {
      const response = await fetch("/api/research/library/items", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(reportId ? { reportId } : { sourceId }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error();
      const item = LibraryItemSchema.parse(await response.json());
      if (reportId ? item.reportId !== reportId : item.sourceId !== sourceId)
        throw new Error();
      if (!controller.signal.aborted) setState("saved");
    } catch {
      if (!controller.signal.aborted) setState("failed");
    } finally {
      if (pending.current === controller) pending.current = null;
    }
  }

  return (
    <span className="library-save">
      <Button
        variant="outline"
        disabled={state === "saving" || state === "saved"}
        onClick={() => void save()}
      >
        {state === "saving" ? (
          "Saving…"
        ) : state === "saved" ? (
          <>
            Saved<span className="library-save-detail"> to library</span>
          </>
        ) : state === "failed" ? (
          "Retry save"
        ) : (
          <>
            Save<span className="library-save-detail"> to library</span>
          </>
        )}
      </Button>
      {state === "saved" ? (
        <Link
          href="/research/library"
          aria-label="Organize this saved item in your library"
        >
          Organize
        </Link>
      ) : null}
      {state === "failed" ? (
        <span role="alert">Couldn’t save this item. Try again.</span>
      ) : null}
      <span className="sr-only" role="status">
        {state === "saved" ? "Item saved to your private library." : ""}
      </span>
    </span>
  );
}
