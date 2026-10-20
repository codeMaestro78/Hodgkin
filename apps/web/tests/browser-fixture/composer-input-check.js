/** Browser regression for text entry and blur without a document reload. */
// prettier-ignore
async (page) => {
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  const account = "composer-input-fixture";
  let submittedBody;
  await page.route("**/api/auth/session", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: account } }) }));
  await page.route("**/api/onboarding", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ profile: null }) }));
  await page.route("**/api/research/runs", (route) => {
    if (route.request().method() === "POST") {
      submittedBody = route.request().postDataJSON();
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ runId: "test-run" }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) });
  });
  await page.addInitScript(() => {
    window.__deskRiseStarts = 0;
    document.addEventListener("animationstart", (event) => {
      if (event.animationName === "desk-rise") window.__deskRiseStarts += 1;
    });
  });
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.goto("http://127.0.0.1:3102/automation.html?view=composer");
  const question = page.getByLabel("What do you need to understand?");
  const requirements = page.getByLabel("Report requirements", { exact: true });
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .filter((animation) => animation.animationName === "desk-rise")
      .every((animation) => animation.playState === "finished"),
  );
  assert(
    (await page.evaluate(() => window.__deskRiseStarts)) > 0,
    "Expected the one-time page entrance animation to run initially",
  );
  await question.click();
  await page.keyboard.type("Compare two evidence methods");
  const entranceCountBeforeBlur = await page.evaluate(
    () => window.__deskRiseStarts,
  );
  await requirements.click();
  assert(
    (await page.evaluate(() => window.__deskRiseStarts)) ===
      entranceCountBeforeBlur,
    "Clicking another field replayed the page entrance animation",
  );
  await page.keyboard.type("Compare costs\nExplain limitations");
  await page.waitForFunction((key) => {
    const saved = JSON.parse(sessionStorage.getItem(key) ?? "null");
    return saved?.draft.question === "Compare two evidence methods" && saved?.draft.requirementsText === "Compare costs\nExplain limitations";
  }, `research:draft:v2:${account}`);
  await page.evaluate(() => {
    window.__composerQuestion = document.querySelector("#question");
    window.__composerTimeOrigin = performance.timeOrigin;
  });
  await page.getByRole("heading", { name: "Start a research brief." }).click();
  assert(await question.inputValue() === "Compare two evidence methods", "Question changed after blur");
  assert(await requirements.inputValue() === "Compare costs\nExplain limitations", "Requirements changed after blur");
  assert(await page.evaluate(() => window.__composerQuestion === document.querySelector("#question")), "Question field was remounted after blur");
  assert(await page.evaluate(() => window.__composerTimeOrigin === performance.timeOrigin), "Composer caused a full document navigation");
  assert(new URL(page.url()).pathname === "/automation.html", "Blur unexpectedly navigated away from the composer");
  assert(
    await page.evaluate(
      (expected) => window.__deskRiseStarts === expected,
      entranceCountBeforeBlur,
    ),
    "Clicking elsewhere replayed the page entrance animation",
  );
  await page.locator(".desk-toggle-item").nth(2).click();
  assert(await question.inputValue() === "Compare two evidence methods", "Question changed after an unrelated form update");
  assert(await requirements.inputValue() === "Compare costs\nExplain limitations", "Requirements changed after an unrelated form update");
  await page.getByRole("button", { name: "Start research", exact: true }).click();
  await page.waitForFunction(() => location.pathname === "/research/test-run");
  assert(submittedBody?.question === "Compare two evidence methods", "Submission did not use the latest question text");
  assert(submittedBody?.reportRequirements?.join("\n") === "Compare costs\nExplain limitations", "Submission did not use the latest requirements");
  console.log("Text entry persists across blur without remounting or document navigation");
}
