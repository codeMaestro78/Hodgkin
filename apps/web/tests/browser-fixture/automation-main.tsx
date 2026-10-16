/** Isolated browser fixture: all API calls are intercepted by automation-check.js. */
import { createRoot } from "react-dom/client";
import Automation from "../../app/(research)/research/automation/page";
import Composer from "../../app/(research)/research/page";
import Run from "../../app/(research)/research/[runId]/page";
import "../../app/styles.css";

class FixtureEventSource {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror = null;
  closed = false;
  constructor() {
    (
      window as unknown as { fixtureStreams: FixtureEventSource[] }
    ).fixtureStreams.push(this);
  }
  close() {
    this.closed = true;
  }
}
(window as unknown as { fixtureStreams: FixtureEventSource[] }).fixtureStreams =
  [];
(window as unknown as { EventSource: unknown }).EventSource =
  FixtureEventSource;
const view = new URLSearchParams(location.search).get("view");
// Next's font loader is absent in this isolated fixture; use the system fallback.
document.documentElement.style.setProperty("--font-outfit", "system-ui");
createRoot(document.getElementById("root")!).render(
  view === "run" ? (
    <Run />
  ) : view === "composer" ? (
    <Composer />
  ) : (
    <Automation />
  ),
);
