/** Browser regression for draft continuity while the session is rechecked. */
// prettier-ignore
async (page) => {
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
  };
  let account = "composer-focus-fixture";
  let holdSession = false;
  let releaseSession;
  let failNext = false;
  await page.route("**/api/auth/session", async (route) => {
    if (failNext) {
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ error: "Sign in to continue." }) });
      return;
    }
    if (holdSession) await new Promise((resolve) => { releaseSession = resolve; });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ user: { id: account, name: "Test" } }) });
  });
  await page.route("**/api/onboarding", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ profile: null }) }));
  await page.route("**/api/research/runs", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }) }));
  await page.goto("http://127.0.0.1:3102/automation.html?view=composer");
  await page.evaluate(() => sessionStorage.clear());
  const question = page.getByLabel("What do you need to understand?");
  const requirements = page.getByLabel("Report requirements", { exact: true });
  const submit = page.getByRole("button", { name: "Start research", exact: true });
  await question.fill("Compare two evidence methods");
  await requirements.fill("Compare costs\nExplain limitations");
  await submit.waitFor({ state: "visible" });
  assert(await submit.isEnabled(), "Initial composer did not become ready");
  await page.waitForFunction((key) => JSON.parse(sessionStorage.getItem(key) ?? "null")?.draft.requirementsText === "Compare costs\nExplain limitations", `research:draft:v2:${account}`);
  await page.evaluate(() => { window.__composerQuestion = document.querySelector("#question"); });
  holdSession = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForFunction(() => document.querySelector("#question")?.value === "Compare two evidence methods");
  assert(await submit.isEnabled(), "Composer was disabled by a background session recheck");
  assert(await requirements.inputValue() === "Compare costs\nExplain limitations", "Requirements changed during recheck");
  assert(await page.evaluate(() => window.__composerQuestion === document.querySelector("#question")), "Composer input was remounted");
  for (let attempt = 0; attempt < 50 && !releaseSession; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  assert(Boolean(releaseSession), "Focus recheck did not reach the session endpoint");
  holdSession = false;
  releaseSession();
  await page.reload();
  await page.waitForFunction(() => document.querySelector("#question")?.value === "Compare two evidence methods");
  assert(await question.inputValue() === "Compare two evidence methods", "Question did not survive reload");
  assert(await requirements.inputValue() === "Compare costs\nExplain limitations", "Requirements did not survive reload");
  account = "composer-other-account";
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForFunction(() => document.querySelector("#question")?.value === "");
  assert(await requirements.inputValue() === "", "Previous account requirements leaked to the new account");
  await question.fill("Draft text under probe failure");
  await requirements.fill("Probe failure requirements");
  await page.evaluate(() => { window.__composerQuestion = document.querySelector("#question"); });
  // A failed session probe (401) says nothing about identity and must not
  // wipe the composer the way a real account switch does.
  failNext = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForTimeout(400);
  assert(await question.inputValue() === "Draft text under probe failure", "A failed session probe blanked the question");
  assert(await requirements.inputValue() === "Probe failure requirements", "A failed session probe blanked the requirements");
  assert(await page.evaluate(() => window.__composerQuestion === document.querySelector("#question")), "A failed session probe remounted the composer");
  failNext = false;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForTimeout(400);
  assert(await question.inputValue() === "Draft text under probe failure", "Draft did not survive the recheck after a probe failure");
  // Whitespace-only junk (left by spacebar page-scrolling while focused) must
  // clear itself on blur and never inflate the visible character counter.
  await question.fill("                 ");
  await page.mouse.click(10, 10);
  await page.waitForTimeout(250);
  assert(await question.inputValue() === "", "Whitespace-only draft survived blur");
  const counterText = await page.evaluate(() => {
    const span = Array.from(document.querySelectorAll("span")).find((s) => /\/1000$/.test(s.textContent || ""));
    return span ? span.textContent : null;
  });
  assert(counterText === "0/1000", "Whitespace-only draft inflated the character counter");
  console.log("Composer retains drafts across focus/reload/probe failure and isolates a changed account");
}
