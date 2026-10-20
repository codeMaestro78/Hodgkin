/** Synthetic requests only; checks the real composer and SSE refresh call sites. */
// prettier-ignore
async (page) => {
  const base = "http://127.0.0.1:3102/automation.html";
  const runId = "11111111-1111-4111-8111-111111111111";
  let releaseDefaults;
  const defaults = new Promise(resolve => { releaseDefaults = resolve; });
  let defaultsRequested = false;
  let status = "researching";
  const snapshots = [];
  const results = [];
  const api = async route => {
    const path = new URL(route.request().url()).pathname;
    const reply = body => route.fulfill({ contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/auth/session") return reply({ user: { id: "latency-fixture", name: "Fixture" } });
    if (path === "/api/billing/entitlement") return reply({ status: "not_configured" });
    if (path === "/api/onboarding") {
      defaultsRequested = true;
      await defaults;
      return reply({ profile: null });
    }
    if (path === "/api/research/runs") return reply({ runs: [] });
    if (path === `/api/research/runs/${runId}`) {
      snapshots.push(Date.now());
      return reply({ runId, status, originalQuestion: "Compare reliable research workflows", sourceCount: 1,
        quickMode: false, errorCode: null, createdAt: new Date().toISOString(),
        budget: { maxSearchCalls: 6, maxEstimatedCostUsd: 1 }, usage: { searchCalls: 1 },
        sources: [], subQuestions: [], events: [{ sequence: 1, type: "node.started", label: "Reading public evidence", occurredAt: new Date().toISOString() }], report: null });
    }
    throw new Error(`Unexpected API request: ${path}`);
  };
  await page.route("**/api/**", api);
  try {
    await page.goto(base + "?view=composer");
    await page.getByLabel("What do you need to understand?").fill("Compare reliable research workflows");
    for (let i = 0; !defaultsRequested && i < 80; i++) await page.waitForTimeout(25);
    if (!defaultsRequested) throw new Error("Identity/draft hydration did not reach defaults");
    const start = page.getByRole("button", { name: "Start research", exact: true });
    results.push({ check: "Verified composer is usable while optional defaults are pending", passed: await start.isEnabled() });
    releaseDefaults();
    await page.goto(base + "?view=run");
    await page.waitForFunction(() => window.fixtureStreams?.length > 0);
    for (let i = 0; snapshots.length === 0 && i < 80; i++) await page.waitForTimeout(25);
    const initialSnapshotRequests = snapshots.length;
    await page.waitForTimeout(1800);
    const quietSnapshotRequests = snapshots.length;
    results.push({ check: "Active event stream does not poll full snapshots while quiet", passed: initialSnapshotRequests === 1 && quietSnapshotRequests === 1 });
    const started = Date.now();
    await page.evaluate(() => {
      const stream = window.fixtureStreams.at(-1);
      // A routine source event is already waiting when a meaningful stage arrives.
      stream.onmessage({ data: JSON.stringify({ sequence: 1, type: "source.discovered" }) });
      stream.onmessage({ data: JSON.stringify({ sequence: 2, type: "node.started", nodeId: "verifier" }) });
    });
    try {
      await page.waitForFunction(() => document.querySelector(".run-status-rail strong")?.textContent === "Checking evidence", null, { timeout: 650 });
      results.push({ check: "Stage change preempts source debounce", passed: true, elapsedMs: Date.now() - started });
    } catch {
      results.push({ check: "Stage change preempts source debounce", passed: false, elapsedMs: Date.now() - started });
    }
    // The durable event updates the visible phase locally; snapshots remain cadence-bounded.
    await page.waitForFunction(() => document.querySelector(".run-status-rail strong")?.textContent === "Checking evidence");
    const burstStart = snapshots.length;
    await page.evaluate(() => {
      const stream = window.fixtureStreams.at(-1);
      for (let sequence = 3; sequence < 23; sequence++)
        stream.onmessage({ data: JSON.stringify({ sequence, type: "source.discovered" }) });
    });
    await page.waitForTimeout(5200);
    results.push({ check: "20 source events coalesce into at most one cadence-bounded snapshot", passed: snapshots.length - burstStart === 1 });
    results.push({ check: "Recorded stage updates immediately without an eager full snapshot", passed: burstStart === initialSnapshotRequests });
    results.push({ check: "Waiting surface shows actual recorded activity", passed: await page.getByRole("region", { name: "Latest recorded activity" }).getByText("Reading public evidence").isVisible() });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 390, height: 844 });
    results.push({ check: "Mobile viewport has no horizontal overflow", passed: await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1) });
    results.push({ check: "Reduced motion disables activity entrance transitions", passed: await page.locator(".research-activity li").first().evaluate(element => getComputedStyle(element).transitionDuration === "0s") });
    status = "failed";
    const snapshotsBeforeTerminal = snapshots.length;
    const failedAt = Date.now();
    await page.evaluate(() => window.fixtureStreams.at(-1).onmessage({ data: JSON.stringify({ sequence: 23, type: "run.failed", errorCode: "wall_clock_limit_exceeded" }) }));
    await page.waitForFunction(() => document.querySelector(".run-status-rail")?.getAttribute("data-status") === "failed", null, { timeout: 650 });
    results.push({ check: "Failure is visible in the status rail immediately", passed: true, elapsedMs: Date.now() - failedAt });
    for (let i = 0; snapshots.length < snapshotsBeforeTerminal + 1 && i < 80; i++) await page.waitForTimeout(25);
    await page.waitForTimeout(1800);
    const terminalSnapshotRequests = snapshots.length;
    results.push({ check: "Terminal stream closes after one final snapshot with no recurring refresh", passed: terminalSnapshotRequests === snapshotsBeforeTerminal + 1, snapshots: terminalSnapshotRequests });
    results.push({ check: "Terminal event closes its stream", passed: await page.evaluate(() => window.fixtureStreams.at(-1).closed) });
    if (results.some(item => !item.passed)) throw new Error(JSON.stringify(results));
    return { results, passed: results.every(item => item.passed) };
  } finally {
    releaseDefaults();
    await page.goto("about:blank");
    await page.unroute("**/api/**", api);
  }
}
