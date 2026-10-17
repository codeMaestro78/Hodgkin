"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type SharedReport = {
  title: string;
  version: number;
  publishedAt: string;
  markdown: string;
};

export default function SharedReportPage() {
  const shareToken = useRef<string | null>(null);
  if (shareToken.current === null && typeof window !== "undefined") {
    shareToken.current = new URLSearchParams(window.location.hash.slice(1)).get(
      "share",
    );
  }
  const [report, setReport] = useState<SharedReport | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const token = shareToken.current;
    if (!token || !/^[A-Za-z0-9_-]{40,100}$/.test(token)) {
      setFailed(true);
      return;
    }
    // Remove the capability from browser history before making the request.
    window.history.replaceState(null, "", "/s");
    let active = true;
    void fetch("/api/shares", {
      headers: { authorization: `ResearchShare ${token}` },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("unavailable");
        return (await response.json()) as SharedReport;
      })
      .then((value) => active && setReport(value))
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
    };
  }, []);

  if (failed)
    return (
      <main className="shared-report">
        <h1>Report unavailable</h1>
        <p>This link may have expired or been revoked.</p>
      </main>
    );
  if (!report)
    return (
      <main className="shared-report" aria-busy="true">
        <p>Loading shared research…</p>
      </main>
    );
  return (
    <main className="shared-report">
      <header>
        <p>Shared research brief · Version {report.version}</p>
        <h1>{report.title}</h1>
        <time dateTime={report.publishedAt}>
          {new Date(report.publishedAt).toLocaleDateString()}
        </time>
      </header>
      <article>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {report.markdown}
        </ReactMarkdown>
      </article>
    </main>
  );
}
