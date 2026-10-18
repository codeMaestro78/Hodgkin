import type { RunInsights } from "./research-insights";

type Accounting = NonNullable<RunInsights["retrievalAccounting"]>;

const providerLabels: Record<string, string> = {
  openalex: "OpenAlex",
  serper: "Serper",
  tavily: "Tavily",
  parallel: "Parallel",
  browser: "Browser",
  internal: "Internal",
};

function measured(value: number | null, label: string) {
  return value === null ? `${label}: not recorded` : `${value} ${label}`;
}

function noun(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function providerSummary(row: Accounting["providers"][number]) {
  const hasDiscoveryCounts = [
    row.discovered,
    row.shortlisted,
    row.excluded,
  ].some((value) => value !== null);
  const parts = hasDiscoveryCounts
    ? [
        measured(row.discovered, "discovered"),
        measured(row.shortlisted, "shortlisted"),
        measured(row.excluded, "excluded"),
      ]
    : ["discovery counts not recorded"];
  parts.push(
    noun(row.extractedSources, "source extracted", "sources extracted"),
    noun(
      row.citedInVerifiedFinding,
      "source cited in verified findings",
      "sources cited in verified findings",
    ),
  );
  if (row.duplicateWork !== null)
    parts.push(measured(row.duplicateWork, "duplicate works"));
  if (row.duplicateUrl != null)
    parts.push(measured(row.duplicateUrl, "duplicate URL results"));
  if (row.unavailable !== null)
    parts.push(measured(row.unavailable, "without an extractable location"));
  const status = row.countsComplete ? "" : " · some counts not recorded";
  return `${providerLabels[row.provider] ?? row.provider}: ${parts.join(", ")}${status}`;
}

export function RetrievalAccountingPanel({
  accounting,
  publishedSnapshot = false,
}: {
  accounting: Accounting | undefined;
  publishedSnapshot?: boolean;
}) {
  if (!accounting) return null;

  const discoveryComplete =
    accounting.providers.length > 0 &&
    accounting.providers.every(
      (provider) =>
        provider.countsComplete &&
        provider.discovered !== null &&
        provider.shortlisted !== null,
    );
  const discoveredRecords = discoveryComplete
    ? accounting.providers.reduce(
        (total, provider) => total + (provider.discovered ?? 0),
        0,
      )
    : null;
  const shortlistedRecords = discoveryComplete
    ? accounting.providers.reduce(
        (total, provider) => total + (provider.shortlisted ?? 0),
        0,
      )
    : null;

  return (
    <section
      className="retrieval-accounting"
      aria-labelledby="retrieval-accounting-title"
    >
      <h3 id="retrieval-accounting-title">Discovery and evidence accounting</h3>
      <p className="desk-help">
        {publishedSnapshot
          ? "Frozen with this published report version. Missing historical or provider counters are shown as not recorded."
          : "Live run-level provider activity; this is not a frozen report snapshot. Missing historical or provider counters are shown as not recorded."}
      </p>
      <dl className="retrieval-funnel" aria-label="Source lifecycle summary">
        <div>
          <dt>Discovered records</dt>
          <dd>{discoveredRecords ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Shortlisted records</dt>
          <dd>{shortlistedRecords ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Extracted sources</dt>
          <dd>{accounting.extractedSources}</dd>
        </div>
        <div>
          <dt>Cited in findings</dt>
          <dd>{accounting.citedInVerifiedFinding}</dd>
        </div>
      </dl>
      <p className="desk-help">
        Discovery totals count provider records, not distinct works. A missing
        provider counter makes the total unavailable; citation is not a
        relevance or independence assessment.
      </p>
      {accounting.schemaVersion === "1.2" && (
        <p>
          {accounting.exactDuplicateSources ?? 0} additional exact-content
          duplicate source record
          {accounting.exactDuplicateSources === 1 ? "" : "s"} among extracted
          records. Source-type labels (not a quality assessment):{" "}
          {Object.entries(accounting.sourceClasses ?? {})
            .map(([sourceClass, count]) => `${sourceClass} ${count}`)
            .join(", ") || "not recorded"}.
        </p>
      )}
      <ul>
        {accounting.providers.map((provider) => (
          <li key={provider.provider}>{providerSummary(provider)}</li>
        ))}
        {accounting.providers.length === 0 && (
          <li>No successful search calls were recorded.</li>
        )}
      </ul>
      <p>
        {noun(
          accounting.extractionCalls,
          "extraction call",
          "extraction calls",
        )}{" "}
        ·{" "}
        {noun(
          accounting.extractedSources,
          "source extracted",
          "sources extracted",
        )}{" "}
        ·{" "}
        {noun(
          accounting.citedInVerifiedFinding,
          "source cited in verified findings",
          "sources cited in verified findings",
        )}
      </p>
      <p>
        Extraction outcomes: {accounting.extractionOutcomes.succeeded}{" "}
        succeeded, {accounting.extractionOutcomes.failed} failed,{" "}
        {accounting.extractionOutcomes.uncertain} uncertain,{" "}
        {accounting.extractionOutcomes.pending} pending,{" "}
        {accounting.extractionOutcomes.other} unclassified.
      </p>
      <p>
        Citation checks: {accounting.citationChecks}; exact spans verified:{" "}
        {accounting.exactSpanVerifiedCitations}; published claims:{" "}
        {accounting.publishedClaims}.
      </p>
      <p>
        Semantic review: {accounting.semanticReviewOutcomes.supports} supported,{" "}
        {accounting.semanticReviewOutcomes.partially_supports} partially
        supported, {accounting.semanticReviewOutcomes.contradicts} contradicted,{" "}
        {accounting.semanticReviewOutcomes.unrelated} unrelated,{" "}
        {accounting.semanticReviewOutcomes.notRecorded} not recorded.
      </p>
      <p className="desk-help">
        Dimension relevance: not assessed. Source independence: not assessed.
        Answer usefulness: not assessed. Citation checks measure recorded
        verification outcomes, not the completeness or usefulness of the report.
        Search rank, lexical overlap, and different URLs do not establish
        relevance or independence.
      </p>
    </section>
  );
}
