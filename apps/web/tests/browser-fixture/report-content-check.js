async (page) => {
  const base = "http://127.0.0.1:3101";
  const checks = [];
  const assert = (condition, label) => { if (!condition) throw new Error(label); checks.push(label); };
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(base + "/?view=run&answer=backend");
  const article = page.locator(".report-article");
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();

  const headings = await article.locator("h2").allInnerTexts();
  const order = ["Key figures", "Evidence by source", "Evidence coverage", "Limitations", "Methodology"];
  assert(order.every((name) => headings.includes(name)), "Generated report has figures, source and coverage sections");
  assert(order.map((name) => headings.indexOf(name)).every((at, i, all) => i === 0 || at > all[i - 1]), "Generated sections appear before limitations and methodology");
  assert(await article.getByRole("heading", { level: 3, name: "Span match rate" }).isVisible(), "Each figure table is titled by its metric");

  const tables = article.locator(".report-table");
  assert(await tables.count() === 3, "Figures, source comparison and coverage render as report tables");
  const text = await article.innerText();
  assert(!text.includes("\\|") && !text.includes("$$") && !text.includes("\\["), "Escapes and math delimiters never show as raw text");

  const figures = tables.nth(0);
  const cells = await figures.locator("tbody tr").evaluateAll((rows) => rows.map((row) => [...row.cells].map((cell) => cell.innerText.trim())));
  assert(cells.length === 3 && cells[1][0] === "Sentence window | v2" && cells[1][1] === "63.8%", "Figure cells keep escaped labels and verbatim values");
  assert(await figures.locator("tbody .citation-chip").count() === 3, "Each figure links to its source as a citation chip");
  await figures.scrollIntoViewIfNeeded();
  await figures.getByRole("group", { name: "Table view" }).getByRole("button", { name: "Chart" }).click();
  const bars = figures.locator(".report-chart-bars li");
  assert(await bars.count() === 3 && (await bars.first().innerText()).includes("91.4%"), "Figure tables chart a single metric");

  const sources = tables.nth(1);
  assert(await sources.locator("tbody tr").count() === 3, "Source comparison lists each cited source once");
  assert(await sources.locator("tbody .citation-chip").count() === 3, "Source rows link their citation number");
  await sources.scrollIntoViewIfNeeded();
  await sources.getByRole("group", { name: "Table view" }).getByRole("button", { name: "Chart" }).click();
  await sources.getByRole("combobox", { name: "Chart metric" }).selectOption({ label: "Shared findings" });
  assert((await sources.locator(".report-chart-bars li").first().innerText()).includes("2"), "Source counts can be charted per metric");

  const coverage = tables.nth(2);
  assert(await coverage.locator("tbody tr").count() === 5, "Coverage lists the summary and every analysis section");
  assert(await coverage.getByRole("group", { name: "Table view" }).count() === 1, "Coverage counts are chartable");

  const method = article.locator('.answer-section[data-kind="method"]');
  assert(await method.locator(".katex-display").count() === 1 && await method.locator(".katex-error").count() === 0, "Publication share renders as display math");
  assert((await method.locator(".katex-mathml annotation").textContent()).includes("\\frac{6}{9}"), "Formula uses the recorded finding counts");
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Generated tables do not overflow at 390px");
  await page.setViewportSize({ width: 1440, height: 900 });
  return { checksPassed: checks.length, checks };
}
