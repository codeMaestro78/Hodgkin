async (page) => {
  const base = "http://127.0.0.1:3101";
  const checks = [];
  const assert = (condition, label) => { if (!condition) throw new Error(label); checks.push(label); };
  await page.setViewportSize({ width: 1440, height: 900 });
  const open = () => page.goto(base + "/?view=run&answer=rich");
  await page.goto(base + "/?view=run");
  await page.evaluate(() => localStorage.removeItem("hogskin.citationStyle"));
  await open();
  const article = page.locator(".report-article");
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();
  assert(await page.locator(".report-scroll[data-answer-ready]").count() === 1, "Completed report switches to the answer-first layout");
  assert(await page.locator('.report-quality[data-quality="partial"]').isVisible(), "Quality strip carries the assessed status tone");
  const kinds = await article.locator(".answer-section").evaluateAll((sections) => sections.map((section) => section.dataset.kind));
  assert(JSON.stringify(kinds) === JSON.stringify(["lead", "body", "body", "limitations", "method"]), "Sections are classified as lead, body, limitations and method");

  const chip = article.locator(".citation-chip").first();
  const card = page.locator("#citation-preview");
  await chip.scrollIntoViewIfNeeded();
  await chip.hover();
  await card.locator(".cite-card-title").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.querySelector("#citation-preview")?.dataset.open === "true");
  const text = await card.innerText();
  assert(text.includes("Provenance tracking in retrieval-augmented systems") && text.includes("Each claim retains a pointer"), "Citation hover card shows the source title and quoted passage");
  assert(text.includes("Exact passage matched"), "Citation hover card states the passage match");
  assert(await chip.getAttribute("aria-describedby") === "citation-preview", "Hovered citation is described by the card");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelector("#citation-preview")?.dataset.open !== "true");
  assert(await chip.getAttribute("aria-describedby") === null, "Escape closes the citation card");
  const second = article.locator(".citation-chip").nth(1);
  await second.hover();
  await page.waitForFunction(() => document.querySelector("#citation-preview")?.dataset.open === "true");
  assert((await card.innerText()).includes("match not recorded"), "Unverified quotes are labelled as such");
  await page.mouse.move(4, 4);

  const table = article.locator(".report-table").first();
  assert(await table.getByRole("button", { name: "Copy" }).isVisible() && await table.getByRole("region", { name: "Research comparison table" }).isVisible(), "Tables have a copy action and a labelled scroll region");

  const references = page.getByRole("region", { name: "References" });
  await references.scrollIntoViewIfNeeded();
  const items = references.getByRole("listitem");
  assert(await items.count() === 3, "References list every source");
  const apa = await items.first().innerText();
  assert(apa.includes("Provenance Lab. (2024, June 11).") && !apa.startsWith("[1]"), "APA reference uses publisher and date");
  assert((await items.nth(2).innerText()).includes("(n.d.)"), "Missing dates read n.d.");
  await references.getByRole("combobox").selectOption("ieee");
  const ieee = await items.first().innerText();
  assert(ieee.includes("[Online]. Available:") && ieee.includes("Accessed: Mar. 14, 2026"), "Switching to IEEE reformats the references");
  assert(await page.evaluate(() => localStorage.getItem("hogskin.citationStyle")) === "ieee", "Citation style persists");
  await references.getByRole("button", { name: "Inspect reference 2" }).click();
  await page.locator(".selected-source").waitFor();
  assert((await page.locator(".selected-source").innerText()).includes("Why do readers trust cited answers?"), "Reference number opens its source");

  await open();
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();
  assert(await page.getByRole("region", { name: "References" }).getByRole("combobox").inputValue() === "ieee", "Stored citation style is restored");
  await page.evaluate(() => localStorage.removeItem("hogskin.citationStyle"));

  const followups = page.getByRole("group", { name: "Follow-up" });
  await followups.scrollIntoViewIfNeeded();
  const options = followups.getByRole("button");
  assert(await options.count() === 2, "Follow-up suggestions come from open gaps and unresolved questions");
  const suggestion = (await options.first().innerText()).trim();
  await options.first().click();
  const field = page.locator(".report-followup textarea");
  assert(await field.inputValue() === suggestion, "Choosing a suggestion fills the follow-up question");
  assert(await page.evaluate(() => document.activeElement?.tagName) === "TEXTAREA", "Choosing a suggestion focuses the question");

  await page.getByRole("tab", { name: /Methodology/ }).click();
  const method = page.getByRole("region", { name: "Searches the agents ran" });
  await method.waitFor();
  const stats = await method.locator(".method-stats").innerText();
  assert(/4\s*\/\s*6/.test(stats) && stats.includes("Providers") && stats.includes("Sources kept"), "Methodology shows calls, providers and kept sources");
  const questions = method.locator(".method-questions > li");
  assert(await questions.count() === 2 && (await questions.first().innerText()).startsWith("01"), "Research questions are numbered");
  await questions.first().locator("summary").click();
  const list = questions.first().locator(".method-source-list button");
  assert(await list.count() === 2, "Expanding a question lists the sources it found");

  await page.setViewportSize({ width: 390, height: 844 });
  await open();
  await page.locator(".answer-section").first().waitFor();
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Answer layout does not overflow at 390px");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await open();
  const chipAgain = page.locator(".report-article .citation-chip").first();
  await chipAgain.scrollIntoViewIfNeeded();
  await chipAgain.hover();
  await page.waitForFunction(() => document.querySelector("#citation-preview")?.dataset.open === "true");
  assert(await page.locator("#citation-preview").evaluate((element) => getComputedStyle(element).transform === "none"), "Reduced motion removes the card movement");
  await page.emulateMedia({ reducedMotion: null });
  return { checksPassed: checks.length, checks };
}
