/** Isolated Vite fixture only. Run as a single expression with playwright-cli run-code --filename. */
// CLI wraps this expression; a trailing statement semicolon is invalid there.
// prettier-ignore
async (page) => {
  const base = "http://127.0.0.1:3102/automation.html";
  const runId = "11111111-1111-4111-8111-111111111111";
  const claimId = "22222222-2222-4222-8222-222222222222";
  const sourceId = "33333333-3333-4333-8333-333333333333";
  const citationId = "44444444-4444-4444-8444-444444444444";
  const question = "Compare bounded research tools";
  const requirements = "Compare costs\nExplain evidence limitations";
  const checks = [];
  const defects = [];
  const assert = (condition, label) => {
    if (!condition) throw new Error(label);
    checks.push(label);
  };
  const draftKey = (id) => `research:draft:v1:${encodeURIComponent(id)}`;
  let account = "phase1-fixture";
  let status = "writing";
  let sourceCount = 1;
  let legacy = false;
  let failCreate = true;
  let historyRequests = 0;
  let pendingCreate = null;
  let heldSession = null;
  let completedCreates = 0;
  const releases = [];
  const hold = () => {
    let release;
    const promise = new Promise((resolve) => {
      release = resolve;
    });
    releases.push(release);
    return { promise, release };
  };
  const until = async (predicate) => {
    for (let attempt = 0; attempt < 100; attempt++) {
      if (predicate()) return;
      await page.waitForTimeout(25);
    }
    throw new Error("Fixture response did not settle");
  };
  let sessions = 0;
  const posts = [];
  const unexpected = [];
  const document = {
    version: 1,
    assessmentVersion: "evidence-links-v1",
    mode: "balanced",
    title: question,
    sections: [
      "overview",
      "mechanisms",
      "comparison",
      "risks",
      "implications",
    ].map((id) => ({
      id,
      title: id,
      claimIds: id === "overview" ? [claimId] : [],
    })),
    findings: [
      {
        id: claimId,
        text: "Bounded collection preserves evidence.",
        section: "overview",
        citationIds: [citationId],
        sourceIds: [sourceId],
      },
    ],
    requirements: [
      {
        id: "question",
        origin: "main_question",
        text: question,
        status: "unresolved",
        claimIds: [],
        basis: "not_established",
      },
      {
        id: "requirement-1",
        origin: "user_requirement",
        text: "Compare costs",
        status: "addressed",
        claimIds: [claimId],
        basis: "model_linked_verified_findings",
      },
      {
        id: "requirement-2",
        origin: "user_requirement",
        text: "Explain evidence limitations",
        status: "unresolved",
        claimIds: [],
        basis: "not_established",
      },
    ],
    questionCoverage: [],
    quality: {
      status: "partial",
      reason: "Evidence is linked; answer completeness is not established.",
      verifiedFindings: 1,
      excludedFindings: 0,
    },
  };
  const run = () => ({
    runId,
    status,
    originalQuestion: question,
    sourceCount,
    sourceLimit: 12,
    quickMode: false,
    errorCode: null,
    createdAt: "2026-10-15T10:00:00Z",
    updatedAt: "2026-10-15T10:01:00Z",
    budget: { maxSearchCalls: 12, maxEstimatedCostUsd: 1 },
    usage: { searchCalls: 1 },
    sources: [],
    subQuestions: [],
    events: [],
    report:
      status === "completed"
        ? {
            id: "report-fixture",
            version: 1,
            publishedAt: "2026-10-15T10:01:00Z",
            markdown: "## Findings\nBounded collection preserves evidence.",
            ...(legacy ? {} : { document }),
          }
        : null,
  });
  const api = async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const reply = (body, code = 200) =>
      route.fulfill({
        status: code,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/auth/session") {
      sessions++;
      const identity = account;
      const gate = heldSession;
      heldSession = null;
      if (gate) await gate;
      return reply({
        user: {
          id: identity,
          name: "Phase 1 Fixture",
          email: "phase1@example.test",
        },
      });
    }
    if (path === "/api/onboarding") return reply({ profile: null });
    if (path === "/api/research/runs" && request.method() === "GET") {
      historyRequests++;
      return reply({
        runs: [
          {
            runId,
            question,
            status: "writing",
            sourceCount: 1,
            createdAt: "2026-10-15T10:00:00Z",
            quickMode: false,
          },
        ],
      });
    }
    if (path === "/api/research/runs" && request.method() === "POST") {
      const failure = failCreate;
      posts.push({
        body: request.postDataJSON(),
        key: request.headers()["idempotency-key"],
        accountHint: request.headers()["x-research-account-id"],
      });
      if (request.headers()["x-research-account-id"] !== account) {
        await reply(
          { error: "Your account changed. Review the current account draft." },
          409,
        );
        completedCreates++;
        return;
      }
      if (pendingCreate) await pendingCreate;
      await (failure
        ? reply({ error: "Fixture creation failed" }, 503)
        : reply({ runId, status: "queued" }, 201));
      completedCreates++;
      return;
    }
    if (path === `/api/research/runs/${runId}`) return reply(run());
    if (
      request.method() === "GET" &&
      /^\/api\/research\/reports\/[^/]+\/shares$/.test(path)
    )
      return reply([]);
    unexpected.push(`${request.method()} ${path}`);
    return reply({ error: "Unexpected fixture API request" }, 501);
  };
  // No API request can fall through to a service, database, or provider.
  await page.route("**/api/**", api);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const composer = base + "?view=composer";
  const start = () =>
    page.getByRole("button", { name: "Start research", exact: true });
  const saved = (id) =>
    page.evaluate(
      (key) => JSON.parse(sessionStorage.getItem(key) ?? "null"),
      draftKey(id),
    );
  const noOverflow = () =>
    page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    );
  try {
    await page.goto(composer);
    await page.evaluate(
      (keys) => keys.forEach((key) => sessionStorage.removeItem(key)),
      [draftKey(account), draftKey("phase1-other-account")],
    );
    await page.reload();
    await page.getByLabel("What do you need to understand?").fill(question);
    await page
      .getByLabel("Report requirements", { exact: true })
      .fill(requirements);
    await page.getByRole("button", { name: /^Deep/ }).click();
    await page.getByLabel("Review the plan before research starts").uncheck();
    await page.waitForFunction(
      (key) =>
        JSON.parse(sessionStorage.getItem(key) ?? "null")?.draft.depth ===
        "Deep",
      draftKey(account),
    );
    await page.reload();
    await page.waitForFunction(
      () =>
        document.querySelector("#question")?.value ===
        "Compare bounded research tools",
    );
    assert(
      (await page
        .getByLabel("Report requirements", { exact: true })
        .inputValue()) === requirements,
      "Requirements and question survive reload",
    );
    assert(
      (await saved(account)).draft.depth === "Deep" &&
        !(await page
          .getByLabel("Review the plan before research starts")
          .isChecked()),
      "Depth and approval survive reload",
    );
    const sessionsBeforeSubmit = sessions;
    await start().click();
    await page.getByText("Fixture creation failed", { exact: true }).waitFor();
    assert(
      (await saved(account)).draft.requirementsText === requirements,
      "Failed creation retains the account draft",
    );
    assert(
      sessions === sessionsBeforeSubmit,
      "Creation uses the existing POST without an extra session roundtrip",
    );
    assert(
      posts[0].accountHint === account,
      "Creation binds the draft to an expected-account hint",
    );
    assert(
      JSON.stringify(posts[0].body.reportRequirements) ===
        JSON.stringify(requirements.split("\n")),
      "Existing reportRequirements API field carries each line",
    );
    assert(
      posts[0].body.budgetOverrides.maxSearchCalls === 20 &&
        posts[0].body.budgetOverrides.maxWallClockMs === 600000,
      "Selected Deep budget remains bounded",
    );
    await page.reload();
    await page.waitForFunction(
      () =>
        document.querySelector("#question")?.value ===
        "Compare bounded research tools",
    );
    assert(
      (await page
        .getByLabel("Report requirements", { exact: true })
        .inputValue()) === requirements,
      "Failed-submit draft remains recoverable after reload",
    );
    await page
      .getByLabel("What do you need to understand?")
      .fill("What is evidence verification?");
    await start().click();
    await page.getByText("Fixture creation failed", { exact: true }).waitFor();
    assert(
      posts.at(-1).body.budgetOverrides.maxSearchCalls === 2 &&
        posts.at(-1).body.budgetOverrides.maxWallClockMs === 120000,
      "Requirements do not raise the two-call quick-mode cap",
    );
    assert(
      await noOverflow(),
      "Desktop composer has no horizontal overflow under reduced motion",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await noOverflow(),
      "Mobile composer has no horizontal overflow under reduced motion",
    );
    failCreate = false;
    await start().click();
    await page.waitForURL(`**/research/${runId}`);
    assert(
      (await saved(account)) === null,
      "Successful creation clears only the account draft",
    );

    // navigation.tsx only changes the URL; navigate the full fixture to mount Run.
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + "?view=run");
    await page.getByRole("heading", { name: question, exact: true }).waitFor();
    await page.waitForFunction(() =>
      window.fixtureStreams.some((stream) => !stream.closed),
    );
    await page
      .locator(".workspace-sidebar .history-list .status-writing")
      .waitFor();
    const historyBefore = historyRequests;
    status = "completed";
    sourceCount = 3;
    await page.evaluate(() =>
      window.fixtureStreams
        .findLast((stream) => !stream.closed)
        .onmessage({
          data: JSON.stringify({ sequence: 1, type: "run.completed" }),
        }),
    );
    await page
      .getByRole("heading", {
        name: "Partial answer — review coverage",
        exact: true,
      })
      .waitFor();
    await page.waitForFunction(
      () =>
        document.querySelector(
          ".workspace-sidebar .history-list .status-completed",
        ) &&
        document
          .querySelector(".workspace-sidebar .history-list small")
          ?.textContent.includes("3 sources"),
    );
    assert(
      historyRequests === historyBefore,
      "Terminal SSE snapshot patches history status/count without another list request",
    );
    assert(
      await page
        .getByText(document.quality.reason, { exact: true })
        .isVisible(),
      "Schema-valid structured report displays partial quality reason",
    );
    await page
      .getByText("Question and report requirements", { exact: true })
      .click();
    assert(
      await page
        .locator(".report-quality")
        .getByText("Evidence linked; completeness not established", {
          exact: false,
        })
        .isVisible(),
      "Linked requirements explicitly avoid claiming completeness",
    );
    await page.setViewportSize({ width: 390, height: 844 });
    assert(
      await noOverflow(),
      "Mobile partial report has no horizontal overflow under reduced motion",
    );
    legacy = true;
    await page.goto(base + "?view=run");
    await page
      .getByRole("heading", { name: "Coverage not assessed", exact: true })
      .waitFor();
    assert(
      await page
        .locator(".report-quality")
        .getByText(
          "This historical report has no structured coverage assessment.",
          { exact: false },
        )
        .isVisible(),
      "Legacy reports remain explicitly not assessed",
    );

    // Old success AND old failure must not unlock a newer account's pending POST.
    for (const oldFailure of [false, true]) {
      account = "phase1-fixture";
      await page.goto(composer);
      await page
        .getByLabel("What do you need to understand?")
        .fill("Account A pending research");
      failCreate = oldFailure;
      const oldCreate = hold();
      pendingCreate = oldCreate.promise;
      const beforePost = posts.length;
      await start().click();
      // The create handler is held, so use observed route entry rather than waiting for its response.
      for (
        let attempt = 0;
        posts.length === beforePost && attempt < 20;
        attempt++
      )
        await page.waitForTimeout(25);
      assert(
        posts.length === beforePost + 1,
        "Account race fixture holds an actual in-flight creation",
      );
      await page.evaluate(
        (key) => sessionStorage.removeItem(key),
        draftKey("phase1-other-account"),
      );
      account = "phase1-other-account";
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await page.waitForFunction(
        () => document.querySelector("#question")?.value === "",
      );
      assert(
        (await saved(account))?.draft.question === "",
        "Account switch does not copy the previous account's draft",
      );
      await page
        .getByLabel("What do you need to understand?")
        .fill("Account B fresh draft");
      failCreate = true;
      const newCreate = hold();
      pendingCreate = newCreate.promise;
      const beforeNew = posts.length;
      await start().click();
      await until(() => posts.length === beforeNew + 1);
      const completedBefore = completedCreates;
      oldCreate.release();
      await until(() => completedCreates === completedBefore + 1);
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      if (new URL(page.url()).pathname !== "/automation.html")
        defects.push(
          "Late success from account A navigates account B to A's run",
        );
      assert(
        await page.getByLabel("What do you need to understand?").isDisabled(),
        `Old account ${oldFailure ? "failure" : "success"} leaves B's pending submission busy`,
      );
      await page.locator("form").evaluate((form) => form.requestSubmit());
      await page.waitForTimeout(50);
      assert(
        posts.length === beforeNew + 1,
        "Old completion cannot unlock duplicate B submissions",
      );
      newCreate.release();
      pendingCreate = null;
      await page
        .getByText("Fixture creation failed", { exact: true })
        .waitFor();
      assert(
        !(await page
          .getByLabel("What do you need to understand?")
          .isDisabled()),
        "B's own failure alone releases its composer",
      );
      await page
        .getByLabel("What do you need to understand?")
        .fill("Account B draft after own failure");
      assert(
        (await saved(account))?.draft.question ===
          "Account B draft after own failure",
        "B's draft still persists after both requests settle",
      );
      if (!defects.length)
        checks.push(
          "Late creation from the previous account cannot navigate or disable the current account draft",
        );
    }

    // Return an older A identity after the newest focus check has confirmed B.
    account = "phase1-fixture";
    const staleIdentity = hold();
    heldSession = staleIdentity.promise;
    const sessionBefore = sessions;
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await until(() => sessions > sessionBefore);
    account = "phase1-other-account";
    await page.evaluate(() => window.dispatchEvent(new Event("focus")));
    await until(() => sessions > sessionBefore + 1);
    staleIdentity.release();
    await page.waitForTimeout(100);
    assert(
      (await page
        .getByLabel("What do you need to understand?")
        .inputValue()) === "Account B draft after own failure",
      "Aborted older focus identity cannot replace the newest account draft",
    );
    await page
      .getByLabel("What do you need to understand?")
      .fill("Newest focus keeps B writable");
    assert(
      (await saved(account))?.draft.question ===
        "Newest focus keeps B writable",
      "Only the newest focus check controls draft readiness and scope",
    );
    const conflictingPost = posts.length;
    account = "phase1-fixture";
    await start().click();
    await until(() => posts.length === conflictingPost + 1);
    await page.waitForFunction(
      () =>
        document.querySelector("#question")?.value ===
        "Account A pending research",
    );
    assert(
      posts.at(-1).accountHint === "phase1-other-account",
      "Mock POST rejects an account hint that differs from the verified session",
    );
    assert(
      (await saved("phase1-other-account"))?.draft.question ===
        "Newest focus keeps B writable",
      "409 retains the original account draft and rehydrates the current account",
    );
    assert(
      unexpected.length === 0,
      "Every API request was fulfilled by an explicit fixture handler",
    );
    return { checks, defects, posts: posts.length, historyRequests };
  } finally {
    releases.forEach((release) => release());
    await page.goto("about:blank");
    await page.unroute("**/api/**", api);
  }
}
