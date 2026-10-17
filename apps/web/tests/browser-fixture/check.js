async (page) => {
  const base = "http://127.0.0.1:3101";
  const checks = [];
  const assert = (value, label) => {
    if (!value) throw new Error(label);
    checks.push(label);
  };
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base + "/");
  await page
    .getByRole("heading", { name: "Start a research brief." })
    .waitFor();
  await page.getByRole("button", { name: /^Focused/ }).click();
  assert(
    (await page
      .getByRole("button", { name: /^Focused/ })
      .getAttribute("aria-pressed")) === "true",
    "Focused is the selected accessible control",
  );
  await page
    .getByLabel("What do you need to understand?")
    .fill("Compare research orchestration platforms");
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  assert(
    (await page.evaluate(
      () => window.fixtureSubmission.budgetOverrides.maxSearchCalls,
    )) === 6,
    "Focused submits six provider/source budget units",
  );
  assert(
    (await page.getByLabel("What do you need to understand?").inputValue()) ===
      "Compare research orchestration platforms",
    "Submission failure preserves question",
  );
  await page.getByRole("button", { name: /^Balanced/ }).click();
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  assert(
    (await page.evaluate(
      () => window.fixtureSubmission.budgetOverrides.maxSearchCalls,
    )) === 12,
    "Balanced submits twelve budget units",
  );
  await page.getByRole("button", { name: /^Deep/ }).click();
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  await page.getByRole("alert").waitFor();
  assert(
    (await page.evaluate(
      () => window.fixtureSubmission.budgetOverrides.maxSearchCalls,
    )) === 20,
    "Deep submits twenty budget units",
  );
  await page
    .getByLabel("What do you need to understand?")
    .fill("What is OpenAI?");
  assert(
    await page
      .locator("#scope-note")
      .textContent()
      .then((text) => text.includes("two sources")),
    "Fast explainer adjustment is explained before submission",
  );
  await page
    .getByRole("button", { name: "Start research", exact: true })
    .click();
  assert(
    (await page.evaluate(
      () => window.fixtureSubmission.budgetOverrides.maxSearchCalls,
    )) === 2,
    "Fast explainer uses its disclosed ceiling",
  );
  await page
    .getByLabel("What do you need to understand?")
    .fill("x".repeat(1000));
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Long composer input causes no horizontal overflow",
  );
  await page.getByRole("button", { name: "Collapse history sidebar" }).click();
  assert(
    await page.locator(".workspace-sidebar").isHidden(),
    "Desktop history collapses",
  );
  await page.getByRole("button", { name: "Expand history sidebar" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open research history" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("dialog", { name: "Research history" }).waitFor();
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  assert(
    await page
      .getByRole("button", { name: "Open research history" })
      .evaluate((el) => el === document.activeElement),
    "History sheet returns keyboard focus",
  );
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Mobile composer has no overflow",
  );
  await page.goto(base + "/?view=run");
  await page
    .getByRole("heading", { name: "Direct answer", exact: true })
    .waitFor();
  assert(
    await page.locator(".evidence-panel").isHidden(),
    "Mobile starts with the report, not stacked evidence",
  );
  await page.getByRole("button", { name: "Open source 1" }).click();
  await page.locator(".selected-source").waitFor();
  assert(
    await page.locator(".report-scroll").isHidden(),
    "Citation opens mobile evidence view",
  );
  assert(
    (await page.locator(".selected-source blockquote").textContent()) ===
      "Evidence must remain inspectable.",
    "Selected source exposes the stored exact quote",
  );
  await page.getByRole("button", { name: "Close source details" }).click();
  assert(
    await page.locator(".report-scroll").isVisible(),
    "Closing source restores report view",
  );
  assert(
    await page
      .getByRole("button", { name: "Open source 1" })
      .evaluate((el) => el === document.activeElement),
    "Closing citation restores originating focus",
  );
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await page.getByRole("tab", { name: /^Checks/ }).click();
  assert(
    await page.getByText("Exact quote matched").isVisible(),
    "Claim checks display actual stored verification",
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("tab", { name: /^Sources/ }).click();
  await page.getByLabel("Search collected evidence").fill("missing source");
  await page.getByText("No sources match. Try a title or publisher.").waitFor();
  assert(
    await page
      .getByText("No sources match. Try a title or publisher.")
      .isVisible(),
    "Evidence search has an explicit empty state",
  );
  const scroll = await page.evaluate(() => {
    const report = document.querySelector(".report-scroll");
    const history = document.querySelector(".history-list");
    report.scrollTop = 300;
    return {
      report: report.scrollTop,
      history: history.scrollTop,
      page: window.scrollY,
    };
  });
  assert(
    scroll.report > 0 && scroll.history === 0 && scroll.page === 0,
    "Report scroll does not move history or the page",
  );
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open research history" }).click();
  assert(
    (await page
      .locator(".desk-sheet-popup")
      .evaluate((el) => getComputedStyle(el).transitionDuration)) === "0s",
    "Reduced motion bypasses sheet movement",
  );
  await page.keyboard.press("Escape");
  await page.goto(base + "/?view=run&state=failed");
  await page.getByText("Research failed", { exact: true }).first().waitFor();
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  assert(
    await page
      .getByRole("button", { name: /^Inspect Architecture/ })
      .isVisible(),
    "Failed run retains collected evidence",
  );
  await page.goto(base + "/?view=run&state=writing");
  await page.getByText("Writing report", { exact: true }).first().waitFor();
  assert(
    await page.getByLabel("Questions being explored").isVisible(),
    "Working run displays actual question states",
  );
  await page.getByRole("button", { name: "Stop research" }).click();
  assert(
    await page.getByRole("button", { name: "Stopping…" }).isDisabled(),
    "Stop requested is distinct from cancelled and blocks duplicate requests",
  );
  await page.goto(base + "/?view=reports");
  await page.setViewportSize({ width: 768, height: 1000 });
  await page
    .getByRole("heading", { name: "Your research, ready to revisit." })
    .waitFor();
  await page.getByLabel("Search completed reports").fill("no match");
  await page.getByText("No matching reports").waitFor();
  assert(true, "Saved report library supports search and an empty state");
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    "Tablet report library has no horizontal overflow",
  );
  await page.goto(base + "/?view=run&state=empty");
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await page.getByText("Sources appear here as research develops.").waitFor();
  assert(true, "Empty evidence has a truthful loading state");
  await page.getByRole("tab", { name: /^Checks/ }).click();
  await page.getByText("No claim checks recorded").waitFor();
  assert(true, "Missing claim data never invents verification");
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(base + "/?view=run");
  await page.getByRole("heading", { name: "Direct answer", exact: true }).waitFor();
  // Stop entrance movement before comparing static layout geometry.
  await page.emulateMedia({ reducedMotion: "reduce" });
  const aligned = await page.evaluate(() => {
    const rects = [".report-header", ".research-signal", ".report-progress", ".report-article"]
      .map((selector) => document.querySelector(selector).getBoundingClientRect());
    return rects.every((rect) => Math.abs(rect.left - rects[0].left) < 1 && Math.abs(rect.width - rects[0].width) < 1);
  });
  assert(aligned, "Title, metrics, progress and brief share one aligned column");
  assert(await page.locator(".new-research").evaluate((el) => getComputedStyle(el).backgroundColor === "rgb(37, 37, 34)"),
    "Workspace primary buttons use the landing ink pill; copper stays reserved for citations");
  return { checksPassed: checks.length, checks };
}
