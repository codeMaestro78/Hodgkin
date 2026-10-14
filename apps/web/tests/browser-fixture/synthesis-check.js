async (page) => {
  const checks = [];
  const assert = (value, label) => {
    if (!value) throw new Error(label);
    checks.push(label);
  };
  let completed = false;
  let snapshots = 0;
  const runId = "11111111-1111-4111-8111-111111111111";
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body;
    if (path.endsWith("/session"))
      body = { user: { name: "Fixture", email: "fixture@example.test" } };
    else if (path.endsWith("/runs")) body = { runs: [] };
    else {
      snapshots += 1;
      body = {
        runId,
        status: completed ? "completed" : "writing",
        originalQuestion: "Compare fintech workflow architectures",
        createdAt: "2026-10-14T16:30:00Z",
        errorCode: null,
        quickMode: false,
        sourceCount: 6,
        sourceLimit: 6,
        budget: { maxSearchCalls: 6, maxEstimatedCostUsd: 1 },
        usage: { searchCalls: 6 },
        sources: [],
        subQuestions: [],
        events: [],
        claimChecks: [],
        report: completed
          ? {
              id: "report",
              version: 1,
              markdown:
                "## Findings\nNo factual findings were published.\n\n## Limitations\nEvidence remains available.",
              publishedAt: "2026-10-14T16:31:00Z",
            }
          : null,
      };
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("http://127.0.0.1:3102/automation.html?view=run");
  await page.locator(".run-busy-track").waitFor();
  assert(
    (await page
      .locator(".run-busy-track span")
      .evaluate((el) => getComputedStyle(el).animationName)) ===
      "run-busy-travel",
    "Working state uses a compositor-friendly activity line",
  );
  const before = snapshots;
  await page.evaluate(() => {
    const stream = window.fixtureStreams.findLast((value) => !value.closed);
    for (let sequence = 1; sequence <= 20; sequence++) {
      stream.onmessage({
        data: JSON.stringify({ sequence, type: "source.discovered" }),
      });
    }
  });
  await page.waitForTimeout(500);
  assert(
    snapshots === before,
    "A source burst does not immediately trigger expensive snapshots",
  );
  await page.waitForTimeout(1200);
  assert(
    snapshots === before + 1,
    "Twenty source events coalesce into one snapshot",
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert(
    (await page
      .locator(".run-busy-track span")
      .evaluate((el) => getComputedStyle(el).animationName)) === "none",
    "Reduced motion stops activity travel",
  );
  completed = true;
  await page.evaluate(() =>
    window.fixtureStreams
      .findLast((value) => !value.closed)
      .onmessage({
        data: JSON.stringify({ sequence: 21, type: "run.completed" }),
      }),
  );
  await page
    .locator(".run-status-rail strong")
    .filter({ hasText: "Evidence record ready" })
    .waitFor();
  assert(
    (await page.locator(".run-status-rail").innerText()).includes(
      "limited result, not a full answer",
    ),
    "Empty verified findings are clearly labeled as a limited result",
  );
  assert(
    (await page.locator(".run-busy-track").count()) === 0,
    "Activity motion stops when execution completes",
  );
  await page.screenshot({
    path: "/tmp/research-limited-result.png",
    fullPage: true,
  });
  return { checksPassed: checks.length, checks };
};
