/** Run with a fresh browser page and the isolated automation Vite fixture. */
async (page, scenario = "all") => {
  const base = "http://127.0.0.1:3102/automation.html";
  const checks = [];
  const assert = (condition, label) => {
    if (!condition) throw new Error(label);
    checks.push(label);
  };
  await page.emulateMedia({ reducedMotion: "reduce" });
  if (scenario === "terminal" || scenario === "all") {
    let status = "writing";
    let outage = false;
    let remainingFailures = 0;
    let snapshots = 0;
    const runId = "11111111-1111-4111-8111-111111111111";
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      const reply = (body, code = 200) =>
        route.fulfill({
          status: code,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      if (path === "/api/auth/session")
        return reply({
          user: { name: "Fixture", email: "fixture@example.test" },
        });
      if (path === "/api/research/runs") return reply({ runs: [] });
      if (path === "/api/onboarding") return reply({ profile: null });
      snapshots++;
      if (outage || remainingFailures-- > 0)
        return reply({ error: "Snapshot temporarily unavailable" }, 503);
      return reply({
        runId,
        status,
        originalQuestion: "Compare research tools",
        sourceCount: 0,
        quickMode: false,
        errorCode: null,
        createdAt: "2026-10-14T10:00:00Z",
        budget: { maxSearchCalls: 12, maxEstimatedCostUsd: 1 },
        usage: { searchCalls: 0 },
        sources: [],
        subQuestions: [],
        events: [],
        report:
          status === "completed"
            ? {
                id: "report",
                version: 1,
                markdown: "## Findings\nRecovered report is ready.",
                publishedAt: "2026-10-14T10:01:00Z",
              }
            : null,
      });
    });
    const complete = () =>
      page.evaluate(() => {
        window.fixtureStreams
          .findLast((stream) => !stream.closed)
          .onmessage({
            data: JSON.stringify({ sequence: 1, type: "run.completed" }),
          });
      });
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Compare research tools", exact: true })
      .waitFor();
    status = "completed";
    remainingFailures = 2;
    await complete();
    await page
      .getByText("Recovered report is ready.", { exact: true })
      .first()
      .waitFor({ timeout: 6000 });
    assert(
      snapshots === 4,
      "Terminal reconciliation recovers automatically after two failed snapshots",
    );
    assert(
      (await page.locator(".run-status-rail strong").innerText()) ===
        "Complete",
      "Successful reconciliation clears the connection error",
    );

    status = "writing";
    snapshots = 0;
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Compare research tools", exact: true })
      .waitFor();
    status = "completed";
    outage = true;
    await complete();
    await page.waitForTimeout(8500);
    assert(
      snapshots === 5,
      "A persistent terminal outage stops after the initial request and three retries",
    );
    await page.waitForTimeout(1200);
    assert(snapshots === 5, "Exhausted retries do not keep polling");
    outage = false;
    await page
      .getByRole("button", { name: "Refresh recorded state", exact: true })
      .click();
    await page
      .getByText("Recovered report is ready.", { exact: true })
      .first()
      .waitFor();
    assert(
      snapshots === 6,
      "Manual refresh recovers the same run without creating paid work",
    );

    status = "writing";
    snapshots = 0;
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Compare research tools", exact: true })
      .waitFor();
    await complete();
    await page.waitForFunction(() =>
      window.fixtureStreams.every((stream) => stream.closed),
    );
    await page.waitForTimeout(100);
    assert(
      (await page.locator(".run-status-rail strong").innerText()) ===
        "Complete",
      "A stale successful snapshot cannot resurrect an active run",
    );
    status = "completed";
    await page
      .getByText("Recovered report is ready.", { exact: true })
      .first()
      .waitFor({ timeout: 3000 });
    assert(
      snapshots === 3,
      "Stale snapshots retry until terminal state is reconciled",
    );

    // Manual refresh replaces the effect while the component remains mounted.
    status = "writing";
    snapshots = 0;
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Compare research tools", exact: true })
      .waitFor();
    await page.evaluate(() => {
      window.oldFixtureStream = window.fixtureStreams.findLast(
        (stream) => !stream.closed,
      );
    });
    status = "completed";
    outage = true;
    await complete();
    await page
      .getByRole("button", { name: "Refresh recorded state", exact: true })
      .waitFor();
    outage = false;
    await page
      .getByRole("button", { name: "Refresh recorded state", exact: true })
      .click();
    await page
      .getByText("Recovered report is ready.", { exact: true })
      .first()
      .waitFor();
    const refreshed = snapshots;
    await page.evaluate(() =>
      window.oldFixtureStream.onmessage({
        data: JSON.stringify({ sequence: 99, type: "run.failed" }),
      }),
    );
    await page.waitForTimeout(2200);
    assert(
      snapshots === refreshed &&
        (await page.locator(".run-status-rail strong").innerText()) ===
          "Complete",
      "Effect replacement clears pending retries and ignores obsolete stream callbacks",
    );

    status = "writing";
    snapshots = 0;
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Compare research tools", exact: true })
      .waitFor();
    outage = true;
    await complete();
    await page
      .getByRole("button", { name: "Refresh recorded state", exact: true })
      .waitFor();
    await page.goto(base + "?view=composer");
    await page
      .getByRole("heading", { name: "Start a research brief.", exact: true })
      .waitFor();
    const before = snapshots;
    await page.waitForTimeout(2200);
    assert(
      snapshots === before,
      "Navigation disposes terminal retry timers and old snapshot requests",
    );
    await page.unroute("**/api/**");
  }
  if (scenario === "defaults" || scenario === "all") {
    const posts = [];
    let releaseDefaults;
    const defaultsReady = new Promise((resolve) => {
      releaseDefaults = resolve;
    });
    await page.route("**/api/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname;
      const reply = (body, code = 200) =>
        route.fulfill({
          status: code,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      if (request.method() === "POST") {
        posts.push({
          body: request.postData(),
          key: request.headers()["idempotency-key"],
        });
        return route.abort("connectionreset");
      }
      if (path === "/api/onboarding") {
        await defaultsReady;
        return reply({
          profile: {
            role: "Researcher",
            field: "Engineering",
            workplace: "Independent",
            workplaceName: "",
            topic: "Saved onboarding question",
            depth: "Deep",
            version: 1,
            step: 6,
            status: "completed",
            updatedAt: "2026-10-14T10:00:00Z",
          },
        });
      }
      if (path === "/api/auth/session")
        return reply({
          user: { name: "Fixture", email: "fixture@example.test" },
        });
      return reply({ runs: [] });
    });
    await page.goto(base + "?view=composer");
    await page
      .getByLabel("What do you need to understand?")
      .fill("Compare research tools");
    await page
      .getByRole("button", { name: "Start research", exact: true })
      .click();
    await page.getByRole("alert").waitFor();
    releaseDefaults();
    await page.waitForResponse("**/api/onboarding");
    await page.waitForTimeout(100);
    assert(
      (await page
        .getByRole("button", { name: /^Balanced/ })
        .getAttribute("aria-pressed")) === "true",
      "Late onboarding defaults cannot change a submitted draft",
    );
    await page
      .getByRole("button", { name: "Start research", exact: true })
      .click();
    await page.getByRole("alert").waitFor();
    assert(
      posts.length === 2 &&
        posts[0].body === posts[1].body &&
        posts[0].key === posts[1].key,
      "Retry after a lost response retains the submitted payload and idempotency key",
    );
    await page.unroute("**/api/**");
  }
  if (scenario === "mobile" || scenario === "all") {
    await page.route("**/api/**", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          runs: [],
          profile: null,
          user: { name: "Fixture", email: "fixture@example.test" },
        }),
      }),
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + "?view=composer");
    await page
      .getByRole("button", { name: "Open research history", exact: true })
      .click();
    const preferences = page
      .getByRole("dialog")
      .getByRole("link", { name: "Research preferences", exact: true });
    await preferences.waitFor({ timeout: 2000 });
    await preferences.focus();
    assert(
      await preferences.evaluate(
        (element) => document.activeElement === element,
      ),
      "Mobile preferences are visible and keyboard accessible",
    );
    assert(
      (await preferences.getAttribute("href")) === "/onboarding",
      "Mobile preferences lead to the account setup editor",
    );
    await preferences.press("Enter");
    await page.getByRole("dialog").waitFor({ state: "hidden" });
    assert(
      new URL(page.url()).pathname === "/onboarding",
      "Opening preferences closes mobile navigation",
    );
    await page.unroute("**/api/**");
  }
  return { checksPassed: checks.length, checks };
};
