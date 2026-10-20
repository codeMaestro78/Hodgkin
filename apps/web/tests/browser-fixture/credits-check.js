async (page) => {
  const base = "http://127.0.0.1:3102/automation.html?view=composer";
  const question = "Check a research question with limited credits";
  let currentPlan = "scholar";
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const reply = (body, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (path === "/api/auth/session")
      return reply({
        user: {
          id: "fixture-account",
          name: "Fixture",
          email: "fixture@example.test",
        },
      });
    if (path === "/api/onboarding") return reply({ profile: null });
    if (path === "/api/research/runs" && request.method() === "POST")
      return reply(
        {
          detail: {
            message: "insufficient research units",
            requiredUnits: 2,
            availableUnits: 0,
            periodEnd: "2026-11-19T00:00:00Z",
          },
        },
        402,
      );
    if (path === "/api/research/runs") return reply({ runs: [] });
    if (path === "/api/billing/entitlement")
      return reply({
        status: "active",
        planKey: currentPlan,
        periodEnd: "2026-11-19T00:00:00Z",
        allowanceUnits: currentPlan === "free" ? 5 : 20,
        consumedUnits: currentPlan === "free" ? 5 : 4,
        reservedUnits: currentPlan === "free" ? 0 : 16,
        availableUnits: 0,
      });
    if (path === "/api/billing/credit-packs")
      return reply({
        enabled: true,
        currency: "USD",
        packs: [{ key: "small", amountMinor: 199, units: 5, expiryDays: null }],
      });
    if (path === "/api/billing/credit-balance")
      return reply({ enabled: true, availableUnits: 0, reservedUnits: 0, frozen: false });
    return reply({});
  });
  await page.goto(base);
  await page.getByLabel("What do you need to understand?").fill(question);
  await page.getByRole("button", { name: "Start research", exact: true }).click();
  const dialog = page.getByRole("dialog", {
    name: "Your research units are used up",
  });
  await dialog.waitFor();
  const content = await dialog.innerText();
  if (
    !content.includes("2 units") ||
    !content.includes("16 units are reserved") ||
    !content.includes("Nov 19, 2026") ||
    !content.includes("Scholar monthly allowance") ||
    !content.includes("4 of 20 monthly units used") ||
    !content.includes("5 units · $1.99") ||
    !content.includes("do not unlock modes excluded from your plan")
  )
    throw new Error("Dialog omitted clear monthly balance, purchased credit, reservation, or reset information");
  if (
    (await page.getByLabel("What do you need to understand?").inputValue()) !==
    question
  )
    throw new Error("The question was not preserved after the 402 response");
  if (
    (await dialog.getByRole("link", { name: "Plan details" }).getAttribute("href")) !==
    "/pricing"
  )
    throw new Error("Plan details link is missing for the paid-plan state");
  await dialog.getByRole("button", { name: "Keep editing" }).click();
  await dialog.waitFor({ state: "hidden" });
  currentPlan = "free";
  await page.reload();
  await page.getByLabel("What do you need to understand?").fill(question);
  await page.getByRole("button", { name: "Start research", exact: true }).click();
  const freeDialog = page.getByRole("dialog", { name: "Your research units are used up" });
  await freeDialog.waitFor();
  if (
    !(await freeDialog.getByRole("link", { name: "Explore plans" }).isVisible()) ||
    !(await freeDialog.getByText(/Upgrade your plan for a larger monthly allowance/).isVisible())
  )
    throw new Error("Free-plan dialog did not explain the upgrade path");
  await freeDialog.getByRole("button", { name: "Keep editing" }).click();
  await freeDialog.waitFor({ state: "hidden" });
  return {
    checksPassed: 6,
    checks: [
      "Separates monthly allowance from purchased credits and explains required units, reservations, and reset date",
      "Preserves the question draft",
      "Shows eligible credit pack and preserves the plan-mode restriction",
      "Uses a plan-details action for a paid-plan account",
      "Offers a clear upgrade path for a free-plan account",
      "Dialog can be dismissed while keeping the draft",
    ],
  };
}
