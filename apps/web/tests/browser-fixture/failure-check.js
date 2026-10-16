async (page) => {
  const checks = [];
  const assert = (value, name) => {
    if (!value) throw new Error(name);
    checks.push(name);
  };
  let status = "awaiting_approval";
  let block = false;
  let release;
  let waited;
  let retryUrl = "";
  const snapshot = () => ({
    runId: "11111111-1111-4111-8111-111111111111",
    status,
    originalQuestion: "Comparing workflow architectures for fintech ledgers",
    sourceCount: 14,
    sourceLimit: 20,
    errorCode: status === "failed" ? "wall_clock_limit_exceeded" : null,
    quickMode: false,
    createdAt: "2026-10-14T16:30:00Z",
    report: null,
    budget: {
      maxSearchCalls: 20,
      maxEstimatedCostUsd: 5,
      maxWallClockMs: 120000,
    },
    usage: { searchCalls: 8 },
    sources: [],
    events: [],
    subQuestions: Array.from({ length: 16 }, (_, i) => ({
      id: `q${i}`,
      question: `Question ${i}: compare the evidence, deployment constraints, failure modes, verification requirements and reliability of the platforms.`,
      status: "pending",
    })),
    approval: {
      planId: "22222222-2222-4222-8222-222222222222",
      state: "pending",
      questions: [{ id: "q1", question: "Compare architectures" }],
    },
  });
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const reply = (body, code = 200) =>
      route.fulfill({
        status: code,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (req.method() === "POST") {
      if (url.pathname.endsWith("/approve")) {
        status = "researching";
        return reply({});
      }
      if (url.pathname.endsWith("/retry")) {
        retryUrl = url.toString();
        return reply({ error: "Mock retry prevented paid work" }, 503);
      }
    }
    if (url.pathname.endsWith("/session"))
      return reply({
        user: { name: "Fixture", email: "fixture@example.test" },
      });
    if (url.pathname.endsWith("/runs")) return reply({ runs: [] });
    if (block)
      await new Promise((resolve) => {
        release = resolve;
        waited?.();
      });
    return reply(snapshot());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("http://127.0.0.1:3102/automation.html?view=run");
  await page
    .getByRole("button", { name: "Approve plan", exact: true })
    .waitFor();
  await page.evaluate(() => {
    const el = document.querySelector(".report-scroll");
    el.dataset.persistToken = "original";
  });
  block = true;
  const loading = new Promise((resolve) => {
    waited = resolve;
  });
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  await loading;
  assert(
    (await page
      .locator(".report-scroll")
      .getAttribute("data-persist-token")) === "original",
    "Approval refresh does not unmount the report or show a loading flash",
  );
  block = false;
  release();
  await page
    .locator(".run-status-rail strong")
    .filter({ hasText: "Collecting evidence" })
    .waitFor();
  assert(
    (await page
      .getByText("Plan approved. Research is queued.", { exact: true })
      .count()) === 0,
    "Outdated approval feedback disappears once collection starts",
  );
  await page.evaluate(() => {
    document.querySelector(".report-scroll").scrollTop = 1000;
  });
  assert(
    (await page.locator(".report-scroll").evaluate((el) => el.scrollTop)) > 0,
    "Reproduction starts with content scrolled away from its header",
  );
  block = true;
  await page.evaluate(() => {
    const stream = window.fixtureStreams.findLast((value) => !value.closed);
    stream.onmessage({
      data: JSON.stringify({
        sequence: 99,
        type: "run.failed",
        errorCode: "wall_clock_limit_exceeded",
        occurredAt: "2026-10-14T16:32:00Z",
      }),
    });
  });
  await page
    .getByRole("alert")
    .filter({ hasText: "active-time limit" })
    .waitFor();
  assert(
    await page.locator(".run-status-rail").isVisible(),
    "Failure is visible without scrolling or waiting for snapshot refresh",
  );
  const box = await page.locator(".run-status-rail").boundingBox();
  assert(
    box.y >= 0 && box.y + box.height <= 900,
    "Failure status stays inside the viewport above both scrolling panels",
  );
  assert(
    (await page
      .getByRole("button", { name: "Retry · 10-min limit", exact: true })
      .count()) === 1,
    "Old two-minute Deep runs disclose a ten-minute retry limit",
  );
  assert(
    await page
      .locator(".research-signal")
      .innerText()
      .then((text) => text.includes("Research failed")),
    "The current step says failed rather than queued",
  );
  block = false;
  release?.();
  await page.waitForTimeout(800);
  assert(
    (await page.locator(".run-status-rail strong").innerText()) ===
      "Research failed",
    "An older researching snapshot cannot resurrect a terminal failure",
  );
  await page
    .locator(".run-status-rail")
    .getByRole("button", { name: "Retry · 10-min limit", exact: true })
    .click();
  assert(
    new URL(retryUrl).searchParams.get("maxWallClockMs") === "600000",
    "Retry forwards only the explicitly shown time allowance",
  );
  status = "failed";
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("http://127.0.0.1:3102/automation.html?view=run");
  await page
    .getByRole("alert")
    .filter({ hasText: "active-time limit" })
    .waitFor();
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Failure controls fit the mobile viewport",
  );
  assert(
    (await page
      .locator(".run-status-rail")
      .evaluate((el) => getComputedStyle(el).transitionDuration)) === "0s",
    "Reduced motion disables status transitions",
  );
  await page.screenshot({
    path: "/tmp/research-failure-mobile.png",
    fullPage: true,
  });
  return { checksPassed: checks.length, checks };
};
