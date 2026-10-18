/** Isolated browser fixture: verified event, source navigation, final handoff. */
async (page) => {
  const runId = "11111111-1111-4111-8111-111111111111";
  const sourceId = "22222222-2222-4222-8222-222222222222";
  const claim = "A supported finding from the recorded source.";
  let completed = false;
  let previewRecorded = false;
  const source = {
    id: sourceId,
    title: "Original study",
    url: "https://example.org/study",
    provider: "tavily",
    sourceClass: "academic",
  };
  const preview = {
    sequence: 1,
    type: "assessment.findings_verified",
    label: "Evidence-checked findings available while the report finishes",
    occurredAt: "2026-10-18T11:00:00Z",
    verifiedFindings: [{ text: claim, sourceIds: [sourceId] }],
    verifiedClaimCount: 1,
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body;
    if (path.endsWith("/session"))
      body = { user: { id: "fixture-account", name: "Fixture", email: "fixture@example.test" } };
    else if (path.endsWith("/runs")) body = { runs: [] };
    else
      body = {
        runId,
        status: completed ? "completed" : "writing",
        originalQuestion: "What does the evidence show?",
        createdAt: "2026-10-18T10:59:00Z",
        errorCode: null,
        quickMode: false,
        sourceCount: 1,
        sourceLimit: 6,
        budget: { maxSearchCalls: 6, maxEstimatedCostUsd: 1 },
        usage: { searchCalls: 2 },
        sources: [source],
        subQuestions: [],
        events: previewRecorded ? [preview] : [],
        claimChecks: completed
          ? [{
              id: "claim-1",
              claim,
              caveats: [],
              status: "supported",
              publishedInReport: true,
              citations: [{
                id: "citation-1",
                sourceId,
                quote: claim,
                exactSpanVerified: true,
                verdict: "supports",
              }],
            }]
          : [],
        insights: {
          schemaVersion: "1.0",
          tasks: [],
          providerCalls: [],
          gaps: [],
          parentReportId: null,
          parentRunId: null,
          followupRuns: [],
          reportVersions: [],
        },
        report: completed
          ? {
              id: "report-1",
              version: 1,
              markdown: `## Findings\n${claim} [1]\n\n## Sources\n1. Original study — https://example.org/study`,
              publishedAt: "2026-10-18T11:01:00Z",
            }
          : null,
      };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://127.0.0.1:3102/automation.html?view=run");
  await page.locator(".report-pending").waitFor();
  previewRecorded = true;
  await page.evaluate((event) => {
    window.fixtureStreams.findLast((stream) => !stream.closed).onmessage({ data: JSON.stringify(event) });
  }, preview);
  const card = page.locator(".verified-preview");
  await card.getByText(claim).waitFor();
  if (!(await card.getByText("coverage review are still in progress", { exact: false }).isVisible()))
    throw new Error("Preview did not disclose that coverage is pending");
  await page.reload();
  await card.getByText(claim).waitFor();
  await card.getByRole("button", { name: "Inspect Original study" }).click();
  await page.locator(".selected-source", { hasText: "Original study" }).waitFor();
  completed = true;
  await page.evaluate(() => {
    window.fixtureStreams.findLast((stream) => !stream.closed).onmessage({
      data: JSON.stringify({ sequence: 2, type: "run.completed" }),
    });
  });
  await page.getByRole("button", { name: "Report", exact: true }).click();
  await page.locator(".report-article", { hasText: claim }).waitFor();
  if (await card.count()) throw new Error("Draft preview remained after final report loaded");
  return { previewVisible: true, reconnect: true, sourceNavigable: true, finalHandoff: true };
}
