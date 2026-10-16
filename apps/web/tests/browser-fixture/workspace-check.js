async (page) => {
  const base = "http://127.0.0.1:3101";
  const checks = [];
  const assert = (condition, label) => { if (!condition) throw new Error(label); checks.push(label); };
  const open = () => page.goto(base + "/?view=run&answer=rich");
  const panelWidth = () => page.locator("#research-evidence").evaluate((element) => Math.round(element.getBoundingClientRect().width));
  await page.setViewportSize({ width: 1600, height: 960 });
  await page.goto(base + "/?view=run");
  await page.evaluate(() => { localStorage.removeItem("hogskin.evidenceWidth"); localStorage.removeItem("hogskin.sourceTable"); });
  await open();
  const article = page.locator(".report-article");
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();

  const handle = page.getByRole("separator", { name: "Resize evidence panel" });
  assert(await handle.isVisible(), "The report and evidence split has a resize handle");
  assert(Math.abs(await panelWidth() - 340) <= 1, "Evidence starts at the reading width");
  assert(await handle.getAttribute("aria-controls") === "research-evidence" && Number(await handle.getAttribute("aria-valuemin")) === 300, "Handle exposes its range and target");
  const columnBefore = await page.locator(".report-header").evaluate((element) => element.getBoundingClientRect().width);
  assert(columnBefore > 760, "The reading column uses the space it is given");

  const box = await handle.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x - 120, box.y + box.height / 2, { steps: 6 });
  await page.mouse.move(box.x - 260, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  const dragged = await panelWidth();
  assert(dragged >= 590 && dragged <= 610, `Dragging the handle widens the evidence panel (${dragged})`);
  assert(await page.evaluate(() => Number(localStorage.getItem("hogskin.evidenceWidth"))) === dragged, "Dragged width is remembered");
  assert(await page.locator(".report-grid").evaluate((element) => element.dataset.resizing === undefined), "Resizing state clears after release");

  const table = page.getByRole("region", { name: "Source comparison table" });
  await table.waitFor();
  assert(await table.getByRole("columnheader", { name: "Relevant extract" }).isVisible(), "A wide panel shows sources as a comparison table");
  const firstRow = await table.locator("tbody tr").first().innerText();
  assert(firstRow.includes("Provenance tracking") && firstRow.includes("Each claim retains a pointer") && firstRow.includes("Exact passage"), "Rows show the quoted extract and its match");
  const misaligned = await table.locator("tbody tr").evaluateAll((rows) => rows.filter((row) => {
    const edges = [...row.cells].map((cell) => cell.getBoundingClientRect());
    return edges.some((edge) => Math.abs(edge.top - edges[0].top) > 0.5 || Math.abs(edge.bottom - edges[0].bottom) > 0.5);
  }).length);
  assert(misaligned === 0, `Every cell in a source row shares its top and bottom edge (${misaligned} misaligned)`);
  await page.getByRole("combobox", { name: "Sort sources" }).selectOption("title");
  const titles = await table.locator(".source-table-title").allInnerTexts();
  assert(JSON.stringify(titles) === JSON.stringify([...titles].sort((a, b) => a.localeCompare(b))), "Title sort is alphabetical");
  await page.getByRole("group", { name: "Columns" }).getByRole("button", { name: "Relevant extract" }).click();
  assert(await table.getByRole("columnheader", { name: "Relevant extract" }).count() === 0, "Columns can be hidden");
  await page.getByRole("group", { name: "Columns" }).getByRole("button", { name: "Relevant extract" }).click();
  await table.getByRole("button", { name: /Why do readers trust/ }).click();
  await page.locator(".selected-source").waitFor();
  assert((await page.locator(".selected-source").innerText()).includes("Why do readers trust cited answers?"), "Choosing a table row opens the source");

  await handle.focus();
  await page.keyboard.press("Home");
  assert(Math.abs(await panelWidth() - 300) <= 1, "Home moves the handle to the minimum");
  await page.keyboard.press("ArrowLeft");
  assert(Math.abs(await panelWidth() - 324) <= 1, "Arrow keys resize in steps");
  assert(await page.locator(".evidence-list").isVisible() && await table.count() === 0, "Narrow panels return to the source list");

  const presets = page.getByRole("group", { name: "Evidence panel width" });
  await presets.getByRole("button", { name: "Split" }).click();
  const grid = await page.locator(".report-grid").evaluate((element) => Math.round(element.getBoundingClientRect().width));
  assert(Math.abs(await panelWidth() - Math.round(grid / 2)) <= 2, "Split preset shares the space evenly");
  await page.waitForFunction(() => document.querySelector('[aria-label="Evidence panel width"] [aria-pressed="true"]')?.textContent?.includes("Split"));
  checks.push("Active preset is marked");
  await presets.getByRole("button", { name: "Read" }).click();
  assert(Math.abs(await panelWidth() - 340) <= 1, "Read preset restores the narrow panel");
  await presets.getByRole("button", { name: "Evidence" }).click();
  const wide = await panelWidth();
  await open();
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();
  assert(Math.abs(await panelWidth() - wide) <= 1, "Panel width survives a reload");
  await page.getByRole("button", { name: "Hide evidence panel" }).click();
  assert(await handle.count() === 0 && !(await page.locator("#research-evidence").isVisible()), "The panel can be collapsed from its header");
  const columnWide = await page.locator(".report-header").evaluate((element) => element.getBoundingClientRect().width);
  assert(columnWide >= 900, `Collapsed evidence gives the report a wider column (${columnWide})`);
  const aligned = await page.evaluate(() => [".report-header", ".report-article"].map((s) => { const r = document.querySelector(s).getBoundingClientRect(); return `${Math.round(r.left)}:${Math.round(r.width)}`; }));
  assert(aligned[0] === aligned[1], "Header and article stay aligned");
  await page.getByRole("button", { name: "Show evidence" }).click();
  await page.evaluate(() => localStorage.removeItem("hogskin.evidenceWidth"));

  await open();
  await article.getByRole("heading", { name: "Executive summary", exact: true }).waitFor();
  assert(await article.locator(".katex").count() >= 2 && await article.locator(".katex-display").count() === 1, "Inline and display math render with KaTeX");
  assert(await article.locator(".katex-error").count() === 0, "Math renders without errors");
  assert((await article.innerText()).includes("$4 per report against $9"), "Currency amounts are not treated as math");

  const numeric = article.locator(".report-table").nth(1);
  await numeric.scrollIntoViewIfNeeded();
  assert(await article.locator(".report-table").first().getByRole("group", { name: "Table view" }).count() === 0, "Text-only tables offer no chart");
  const toggle = numeric.getByRole("group", { name: "Table view" });
  await toggle.getByRole("button", { name: "Chart" }).click();
  const bars = numeric.locator(".report-chart-bars li");
  assert(await bars.count() === 3, "Numeric tables can be shown as a chart");
  assert((await bars.first().innerText()).includes("91.4%"), "Chart values keep their unit and drop citation markers");
  await numeric.getByRole("combobox", { name: "Chart metric" }).selectOption({ label: "Reader checks" });
  assert((await bars.first().innerText()).includes("1,204"), "Chart metric can be switched");
  const widths = await bars.locator(".report-chart-bar").evaluateAll((items) => items.map((item) => parseFloat(item.style.width)));
  assert(widths[0] === 100 && widths[0] > widths[1] && widths[1] > widths[2], "Bar lengths are proportional from zero");
  await toggle.getByRole("button", { name: "Table" }).click();
  assert(await numeric.getByRole("region", { name: "Research comparison table" }).isVisible(), "Switching back shows the table");

  const download = page.waitForEvent("download");
  await numeric.getByRole("button", { name: "Download table as CSV" }).click();
  const file = await download;
  const csv = await file.createReadStream().then((stream) => new Promise((resolve) => { let data = ""; stream.on("data", (chunk) => { data += chunk; }); stream.on("end", () => resolve(data)); }));
  assert(file.suggestedFilename() === "hogskin-table.csv" && csv.includes('Exact span,91.4% [3],"1,204"'), "CSV export keeps citations and quotes numbers with commas");

  await numeric.getByRole("button", { name: "Expand table" }).click();
  const dialog = page.getByRole("dialog", { name: "Expanded table" });
  await dialog.waitFor();
  assert(await dialog.locator("table").isVisible() && await dialog.locator(".report-chart").isVisible(), "Expanded view shows the full table and chart");
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  checks.push("Escape closes the expanded table");

  await page.setViewportSize({ width: 390, height: 844 });
  await open();
  await page.locator(".answer-section").first().waitFor();
  assert(!(await page.getByRole("separator", { name: "Resize evidence panel" }).isVisible()), "Resizing is off on small screens");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Workspace does not overflow at 390px");
  await page.setViewportSize({ width: 1440, height: 900 });
  return { checksPassed: checks.length, checks };
}
