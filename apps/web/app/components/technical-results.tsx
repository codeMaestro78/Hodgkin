import type { ReportDocumentV5, ReportDocumentV6 } from "@research/contracts";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export function TechnicalResults({
  document,
  sourceTitles,
  onOpenSource,
}: {
  document: ReportDocumentV5 | ReportDocumentV6;
  sourceTitles: Map<string, string>;
  onOpenSource: (sourceId: string, origin: HTMLButtonElement) => void;
}) {
  const findings = new Map(
    document.findings.map((finding) => [finding.id, finding]),
  );
  return (
    <section
      className="technical-results"
      aria-labelledby="technical-results-title"
    >
      <h2 id="technical-results-title">Source-stated technical results</h2>
      <p className="desk-help">
        Literal expressions match extracted passages. The original PDF equation,
        theorem proof, and source-reported measurements have not been
        independently checked.
      </p>
      {document.technicalResults.length === 0 ? (
        <p className="desk-help" role="status">
          No source-located technical results passed this report’s evidence
          checks. This does not establish that the collected sources contain no
          equations or theorems.
        </p>
      ) : (
        <div className="technical-results-list">
          {document.technicalResults.map((result, index) => {
            const finding = findings.get(result.claimId);
            return (
              <article
                className="technical-result-card"
                key={`${result.claimId}-${index}`}
              >
                <p className="technical-result-kind">
                  Record type · {result.kind.replaceAll("_", " ")}
                </p>
                <h3>{result.title}</h3>
                {finding && <p>{finding.text}</p>}
                {result.assumptions.length > 0 && (
                  <div>
                    <h4>Source-stated conditions</h4>
                    <ul>
                      {result.assumptions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.notation.length > 0 && (
                  <div>
                    <h4>Notation from source</h4>
                    <ul>
                      {result.notation.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {result.expression && (
                  <div className="technical-result-expression">
                    <h4>Literal source expression</h4>
                    {result.expression.representation === "latex" &&
                    !result.expression.sourceText.includes("$$") ? (
                      <ReactMarkdown
                        remarkPlugins={[
                          [remarkMath, { singleDollarTextMath: false }],
                        ]}
                        rehypePlugins={[
                          [
                            rehypeKatex,
                            {
                              throwOnError: false,
                              trust: false,
                              maxExpand: 200,
                              maxSize: 20,
                            },
                          ],
                        ]}
                      >
                        {`$$\n${result.expression.sourceText}\n$$`}
                      </ReactMarkdown>
                    ) : (
                      <pre>
                        <code>{result.expression.sourceText}</code>
                      </pre>
                    )}
                  </div>
                )}
                <p className="desk-help">
                  {result.sourceLocation
                    ? `Recorded location: ${result.sourceLocation}. `
                    : "Precise section or page not recorded. "}
                  {result.expression
                    ? "Expression checked literally; no symbolic transformation. "
                    : "No source-verified expression recorded. "}
                  Source integrity: {result.sourceArtifactHash.slice(0, 12)}…
                </p>
                <div className="technical-result-sources">
                  {result.sourceIds.map((sourceId) => (
                    <button
                      key={sourceId}
                      type="button"
                      onClick={(event) =>
                        onOpenSource(sourceId, event.currentTarget)
                      }
                    >
                      Inspect {sourceTitles.get(sourceId) ?? "source"}
                    </button>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {document.version === 6 && (
        <section
          className="report-measurements"
          aria-labelledby="report-measurements-title"
        >
          <h2 id="report-measurements-title">Source-stated measurements</h2>
          <p className="desk-help">
            Values are preserved as written. Missing scope is marked “Not
            established”; charts appear only when all comparison fields match
            exactly.
          </p>
          {document.measurements.length === 0 ? (
            <p className="desk-help" role="status">
              No measurements passed the exact-passage and supported-claim
              checks.
            </p>
          ) : (
            <div
              className="report-measurement-table-wrap"
              role="region"
              aria-label="Verified source measurements"
              tabIndex={0}
            >
              <table className="report-measurement-table">
                <thead>
                  <tr>
                    <th>Subject</th>
                    <th>Metric</th>
                    <th>Reported value</th>
                    <th>Unit</th>
                    <th>Population</th>
                    <th>Period</th>
                    <th>Method / definition</th>
                    <th>Comparison</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {document.measurements.map((measurement) => {
                    const comparison = document.measurementComparisons.find(
                      (item) => item.measurementIds.includes(measurement.id),
                    );
                    const comparisonLabel =
                      comparison?.status === "comparable"
                        ? "Comparable within recorded scope"
                        : comparison
                          ? "Not established — scope is missing or incompatible"
                          : "Not compared — no second observation";
                    return (
                      <tr key={measurement.id}>
                        <th scope="row">{measurement.subject}</th>
                        <td>{measurement.metric}</td>
                        <td>{measurement.value}</td>
                        <td>{measurement.unit ?? "Not established"}</td>
                        <td>{measurement.population ?? "Not established"}</td>
                        <td>{measurement.period ?? "Not established"}</td>
                        <td>
                          {measurement.method ?? "Not established"}
                          {measurement.definition
                            ? ` · ${measurement.definition}`
                            : ""}
                        </td>
                        <td>{comparisonLabel}</td>
                        <td>
                          <button
                            type="button"
                            onClick={(event) =>
                              onOpenSource(
                                measurement.sourceId,
                                event.currentTarget,
                              )
                            }
                          >
                            Inspect passage
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {document.measurementComparisons.map((comparison) => (
            <p className="desk-help" key={comparison.id}>
              <strong>
                {comparison.metric} comparison:{" "}
                {comparison.status === "comparable"
                  ? "Comparable within recorded scope"
                  : "Not established"}
                .
              </strong>{" "}
              {comparison.status === "not_established"
                ? "At least one unit, population, period, method, definition, or subject match is missing or incompatible; values are shown separately and are not ranked."
                : "The recorded unit, population, period, method, and definition match exactly; this does not establish causality."}
            </p>
          ))}
          {document.measurementCharts.map((chart) => {
            const rows = chart.measurementIds
              .map((id) =>
                document.measurements.find((item) => item.id === id)!,
              )
              .filter(Boolean);
            const values = rows.map((row) => Number(row.plotValue));
            const maximum = Math.max(...values, 0);
            return (
              <figure className="source-measurement-chart" key={chart.id}>
                <figcaption>
                  <strong>{chart.title}</strong>
                  <span>
                    {chart.metric} · {chart.unit} · {chart.population} ·{" "}
                    {chart.period}
                  </span>
                </figcaption>
                <div
                  className="source-measurement-bars"
                  role="img"
                  aria-label={`${chart.title}. Source-reported values: ${rows.map((row) => `${row.subject}, ${row.value} ${row.unit}`).join("; ")}`}
                >
                  {rows.map((row) => (
                    <div className="source-measurement-bar-row" key={row.id}>
                      <span>{row.subject}</span>
                      <span className="source-measurement-track">
                        <span
                          style={{
                            width: `${maximum > 0 ? Math.max(1, (Number(row.plotValue) / maximum) * 100) : 0}%`,
                          }}
                        />
                      </span>
                      <strong>
                        {row.value} {row.unit}
                      </strong>
                    </div>
                  ))}
                </div>
                <p className="desk-help">
                  Bars use only source-stated values; comparison eligibility
                  requires exact matching scope and definition.
                </p>
              </figure>
            );
          })}
          {document.measurements.map((measurement) => (
            <details
              className="measurement-source-passage"
              key={`${measurement.id}-passage`}
            >
              <summary>
                {measurement.title} · exact cited passage
                {measurement.sourceLocation
                  ? ` · ${measurement.sourceLocation}`
                  : ""}
              </summary>
              <blockquote>{measurement.sourcePassage}</blockquote>
            </details>
          ))}
        </section>
      )}
    </section>
  );
}
