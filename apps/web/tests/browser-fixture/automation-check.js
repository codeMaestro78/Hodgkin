async (page) => {
  const base = "http://127.0.0.1:3102/automation.html";
  const checks = [];
  const assert = (value, message) => {
    if (!value) throw new Error(message);
    checks.push(message);
  };
  const posts = [];
  let failWrites = true;
  let failLists = false;
  let status = "awaiting_approval";
  let approvalState = "pending";
  let schedules = [
    {
      id: "schedule-a",
      question: "Compare research tools",
      intervalMinutes: 60,
      enabled: true,
      nextRunAt: "2026-10-15T10:00:00Z",
    },
  ];
  let pendingWrite;
  const run = () => ({
    runId: "11111111-1111-4111-8111-111111111111",
    status,
    originalQuestion: "Compare research tools",
    sourceCount: 0,
    errorCode: null,
    quickMode: false,
    createdAt: "2026-10-14T10:00:00Z",
    budget: { maxSearchCalls: 12, maxEstimatedCostUsd: 1 },
    usage: { searchCalls: 0 },
    report: null,
    sources: [],
    subQuestions: [],
    events: [],
    approval: {
      planId: "22222222-2222-4222-8222-222222222222",
      state: approvalState,
      questions: [{ id: "q1", question: "Which tools verify citations?" }],
    },
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
        path,
        body: request.postDataJSON(),
        key: request.headers()["idempotency-key"],
      });
      if (pendingWrite) await pendingWrite;
      if (failWrites) return reply({ detail: "Fixture write failed" }, 503);
      if (path.endsWith("/approve")) {
        approvalState = request.postDataJSON().decision;
        status = approvalState === "approve" ? "queued" : "cancelled";
        return reply({ runId: run().runId });
      }
      if (path.endsWith("/disable")) {
        schedules = schedules.map((value) => ({ ...value, enabled: false }));
        return reply({});
      }
      if (path.endsWith("/batches"))
        return reply({ batchId: "batch-a", runIds: [run().runId] });
      if (path.endsWith("/schedules")) return reply({ id: "schedule-b" });
      return reply({ runId: run().runId });
    }
    if (path === "/api/auth/session")
      return reply({
        user: { id: "fixture-account", name: "Fixture", email: "fixture@example.test" },
      });
    if (path === "/api/onboarding") return reply({ profile: null });
    if (path === "/api/research/runs") return reply({ runs: [] });
    if (path.endsWith("/batches"))
      return failLists
        ? reply({ error: "Fixture list failed" }, 503)
        : reply({ batches: [] });
    if (path.endsWith("/schedules")) return reply({ schedules });
    return reply(run());
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base + "?view=composer");
  const approvalToggle = page.getByLabel(
    "Review the plan before research starts",
  );
  assert(
    await approvalToggle.isChecked(),
    "Composer requires approval by default",
  );
  await page
    .getByLabel("What do you need to understand?")
    .fill("Compare research tools");
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  const firstRun = posts.at(-1);
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  assert(
    posts.at(-1).key === firstRun.key,
    "Composer retry retains its idempotency key",
  );
  await approvalToggle.uncheck();
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  assert(
    posts.at(-1).key !== firstRun.key &&
      posts.at(-1).body.requireApproval === false,
    "Changing approval updates the payload and idempotency fingerprint",
  );

  await page.goto(base);
  await page.getByRole("button", { name: "Refresh lists" }).waitFor();
  await page
    .getByText("Loading batches and schedules…")
    .waitFor({ state: "hidden" });
  assert(
    await page
      .getByLabel("Review each plan before research starts")
      .first()
      .isChecked(),
    "Batch approval defaults to true",
  );
  await page
    .getByLabel("Questions, one per line")
    .fill(
      Array.from(
        { length: 21 },
        (_, index) => `Research question ${index}`,
      ).join("\n"),
    );
  const before = posts.length;
  await page.getByRole("button", { name: "Create batch", exact: true }).click();
  await page
    .getByText(
      "Enter 1–20 questions, one per line, each between 5 and 10,000 characters.",
    )
    .waitFor();
  assert(
    posts.length === before,
    "Over-limit batches are blocked before submission",
  );
  await page
    .getByLabel("Questions, one per line")
    .fill("Compare research tools\nVerify evidence quality");
  await page.locator("#batch-limit").fill("6");
  await page.getByRole("button", { name: "Create batch", exact: true }).click();
  await page.getByText("Fixture write failed", { exact: true }).waitFor();
  const firstBatch = posts.at(-1).body;
  assert(
    firstBatch.questions.length === 2 &&
      firstBatch.requireApproval === true &&
      firstBatch.budgetOverrides.maxSearchCalls === 6,
    "Batch submits questions, approval and budget",
  );
  await page.getByRole("button", { name: "Create batch", exact: true }).click();
  await page.getByText("Fixture write failed", { exact: true }).waitFor();
  assert(
    posts.at(-1).body.idempotencyKey === firstBatch.idempotencyKey,
    "Batch retry retains its UUID request key",
  );
  await page.locator("#batch-approval").uncheck();
  failWrites = false;
  let release;
  pendingWrite = new Promise((resolve) => {
    release = resolve;
  });
  await page.getByRole("button", { name: "Create batch", exact: true }).click();
  assert(
    await page.getByRole("button", { name: "Creating batch…" }).isDisabled(),
    "Batch pending state disables repeat submission",
  );
  release();
  pendingWrite = undefined;
  await page.getByText("Batch created with 1 runs.").waitFor();
  assert(
    posts.at(-1).body.idempotencyKey !== firstBatch.idempotencyKey,
    "Changed batch approval gets a new request key",
  );
  await page.getByText("Batch batch-a · 1 runs").click();
  assert(
    await page.getByRole("link", { name: /^Open run/ }).isVisible(),
    "Created batch links to its actual run IDs",
  );

  failWrites = true;
  await page
    .getByLabel("Research question", { exact: true })
    .fill("Compare research tools");
  await page.getByLabel("Repeat every (minutes)").fill("59");
  const beforeSchedule = posts.length;
  await page
    .getByRole("button", { name: "Create schedule", exact: true })
    .click();
  assert(
    posts.length === beforeSchedule,
    "Schedule intervals below 60 minutes are blocked",
  );
  await page.getByLabel("Repeat every (minutes)").fill("60");
  await page
    .getByRole("button", { name: "Create schedule", exact: true })
    .click();
  await page
    .locator("#schedule-title")
    .locator("..")
    .getByRole("alert")
    .waitFor();
  const firstSchedule = posts.at(-1).body;
  assert(
    firstSchedule.intervalMinutes === 60 && firstSchedule.requireApproval,
    "Schedule sends its interval and approval default",
  );
  await page
    .getByRole("button", { name: "Create schedule", exact: true })
    .click();
  await page
    .locator("#schedule-title")
    .locator("..")
    .getByRole("alert")
    .waitFor();
  assert(
    posts.at(-1).body.idempotencyKey === firstSchedule.idempotencyKey,
    "Schedule retry retains its request key",
  );
  failWrites = false;
  await page
    .getByRole("button", { name: "Create schedule", exact: true })
    .click();
  await page.getByText("Schedule created.", { exact: true }).waitFor();
  await page
    .getByText("Loading batches and schedules…")
    .waitFor({ state: "hidden" });
  await page
    .getByRole("button", { name: "Disable schedule: Compare research tools" })
    .click();
  await page.getByText("Schedule disabled.").waitFor();
  assert(
    posts.at(-1).path.endsWith("/schedule-a/disable") &&
      JSON.stringify(posts.at(-1).body) === "{}",
    "Disable sends the selected schedule ID and empty JSON body",
  );
  assert(
    await page
      .getByRole("button", { name: "Disable schedule: Compare research tools" })
      .isDisabled(),
    "Disabled schedules cannot be disabled again",
  );
  failLists = true;
  await page.getByRole("button", { name: "Refresh lists" }).click();
  await page.getByText(/Batches couldn’t be loaded/).waitFor();
  assert(
    await page.getByText("Compare research tools", { exact: true }).isVisible(),
    "A failed batch list leaves successfully loaded schedules usable",
  );
  await page.setViewportSize({ width: 390, height: 844 });
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Automation fits the mobile viewport",
  );
  await page.screenshot({
    path: "/tmp/research-automation-mobile.png",
    fullPage: true,
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base + "?view=run");
  await page
    .getByRole("heading", { name: "Review the research plan" })
    .waitFor();
  assert(
    await page.getByText("Which tools verify citations?").isVisible(),
    "Pending approval shows the proposed plan questions",
  );
  failWrites = true;
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  await page.getByRole("alert").waitFor();
  const firstDecision = posts.at(-1).body;
  assert(
    firstDecision.planId === run().approval.planId &&
      firstDecision.decision === "approve",
    "Approval posts the exact plan reference and decision",
  );
  failWrites = false;
  await page.getByRole("button", { name: "Approve plan", exact: true }).click();
  await page.getByText("Plan approved. Research is queued.").waitFor();
  assert(
    JSON.stringify(posts.at(-1).body) === JSON.stringify(firstDecision),
    "An approval retry replays the same decision",
  );
  assert(
    (await page
      .getByRole("button", { name: "Approve plan", exact: true })
      .count()) === 0,
    "Approval controls disappear once the plan is approved",
  );
  status = "awaiting_approval";
  approvalState = "pending";
  await page.goto(base + "?view=run");
  await page.getByRole("button", { name: "Reject plan", exact: true }).click();
  await page
    .locator(".run-status-rail strong")
    .filter({ hasText: "Research stopped" })
    .waitFor();
  assert(
    posts.at(-1).body.decision === "reject",
    "Reject posts its decision and refreshes to the cancelled run",
  );
  status = "researching";
  approvalState = "pending";
  await page.goto(base + "?view=run");
  await page
    .getByRole("heading", { name: "Compare research tools", exact: true })
    .waitFor();
  assert(
    (await page
      .getByRole("button", { name: "Approve plan", exact: true })
      .count()) === 0,
    "Pending plan outside awaiting_approval has no decision controls",
  );
  status = "awaiting_approval";
  approvalState = "approve";
  await page.goto(base + "?view=run");
  await page
    .getByRole("heading", { name: "Compare research tools", exact: true })
    .waitFor();
  assert(
    (await page
      .getByRole("button", { name: "Approve plan", exact: true })
      .count()) === 0,
    "Resolved approval in awaiting_approval has no decision controls",
  );
  return { checksPassed: checks.length, checks };
}
