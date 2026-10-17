async (page) => {
  const checks = [];
  const assert = (value, label) => {
    if (!value) throw new Error(label);
    checks.push(label);
  };
  let completed = false;
  let snapshots = 0;
  const runId = "11111111-1111-4111-8111-111111111111";
  const unansweredQuestion = "How do the approaches compare in fault tolerance?";
  const gaps = Array.from({ length: 18 }, (_, index) => ({
    id: `22222222-2222-4222-8222-${String(index).padStart(12, "0")}`,
    description: `Draft assertion requires evidence: unsupported draft ${index}`,
    why: "The assertion failed the evidence checks.",
    suggestedQuery: `Investigate unsupported thermal-pricing assertion ${index}`,
    status: "open",
    claimIds: [],
    subQuestionIds: [],
  }));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body;
    if (path.endsWith("/session"))
      body = { user: { id: "fixture-account", name: "Fixture", email: "fixture@example.test" } };
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
        subQuestions: [{ id: "q1", question: unansweredQuestion, status: "complete" }],
        events: [],
        claimChecks: [],
        insights: {
          schemaVersion: "1.0",
          tasks: [],
          providerCalls: [],
          gaps,
          parentReportId: null,
          parentRunId: null,
          followupRuns: [],
          reportVersions: [],
        },
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
    .filter({ hasText: "Research finished—answer not established" })
    .waitFor();
  assert(
    (await page.locator(".run-status-rail").innerText()).includes(
      "No findings passed the evidence checks",
    ),
    "Empty verified findings are clearly labeled as a limited result",
  );
  assert(
    (await page.locator(".report-article .answer-section, .report-article h2, .report-outline").count()) === 0 &&
      !(await page.locator(".report-article").innerText()).includes("No factual findings were published"),
    "Zero-findings report does not render the empty Markdown body or section outline",
  );
  const gapSummary = page.getByText("Review 18 research gaps", { exact: true });
  const gapDetails = page.locator("details").filter({ has: gapSummary });
  assert(
    !(await gapDetails.evaluate((element) => element.open)) &&
      (await page.locator('.research-gaps[aria-label="Research gaps"] .desk-claim:visible').count()) === 0,
    "Rejected draft cards are collapsed by default",
  );
  const suggestions = page.getByRole("group", { name: "Follow-up", exact: true });
  assert(
    (await suggestions.getByRole("button").count()) === 1 &&
      (await suggestions.innerText()).includes(unansweredQuestion) &&
      !(await suggestions.innerText()).includes("thermal-pricing"),
    "Follow-up suggestions use unanswered plan questions, not unsupported draft prompts",
  );
  await suggestions.getByRole("button").click();
  assert(
    (await page.getByLabel("Continue this research", { exact: true }).inputValue()) === unansweredQuestion,
    "Suggested follow-up prefills the unanswered research question",
  );
  await gapSummary.focus();
  await page.keyboard.press("Enter");
  assert(
    (await gapDetails.evaluate((element) => element.open)) &&
      (await page.locator('.research-gaps[aria-label="Research gaps"] .desk-claim:visible').count()) === 18,
    "Keyboard users can expand and inspect every recorded draft gap",
  );
  await page.keyboard.press("Enter");
  assert(!(await gapDetails.evaluate((element) => element.open)), "Research gaps can be collapsed again with the keyboard");
  assert(
    (await page.locator(".run-busy-track").count()) === 0,
    "Activity motion stops when execution completes",
  );
  await page.screenshot({
    path: "/tmp/research-limited-result.png",
    fullPage: true,
  });
  return { checksPassed: checks.length, checks };
}
