import type { ReportDocumentV5 } from "@research/contracts";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export function TechnicalResults({
  document,
  sourceTitles,
  onOpenSource,
}: {
  document: ReportDocumentV5;
  sourceTitles: Map<string, string>;
  onOpenSource: (sourceId: string, origin: HTMLButtonElement) => void;
}) {
  const findings = new Map(document.findings.map((finding) => [finding.id, finding]));
  return (
    <section className="technical-results" aria-labelledby="technical-results-title">
      <h2 id="technical-results-title">Source-stated technical results</h2>
      <p className="desk-help">
        Literal expressions match extracted passages. The original PDF equation, theorem proof,
        and source-reported measurements have not been independently checked.
      </p>
      {document.technicalResults.length === 0 ? (
        <p className="desk-help" role="status">
          No source-located technical results passed this report’s evidence checks. This does not
          establish that the collected sources contain no equations or theorems.
        </p>
      ) : (
      <div className="technical-results-list">
        {document.technicalResults.map((result, index) => {
          const finding = findings.get(result.claimId);
          return (
            <article className="technical-result-card" key={`${result.claimId}-${index}`}>
              <p className="technical-result-kind">
                Record type · {result.kind.replaceAll("_", " ")}
              </p>
              <h3>{result.title}</h3>
              {finding && <p>{finding.text}</p>}
              {result.assumptions.length > 0 && (
                <div>
                  <h4>Source-stated conditions</h4>
                  <ul>{result.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              )}
              {result.notation.length > 0 && (
                <div>
                  <h4>Notation from source</h4>
                  <ul>{result.notation.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              )}
              {result.expression && (
                <div className="technical-result-expression">
                  <h4>Literal source expression</h4>
                  {result.expression.representation === "latex" &&
                  !result.expression.sourceText.includes("$$") ? (
                    <ReactMarkdown
                      remarkPlugins={[[remarkMath, { singleDollarTextMath: false }]]}
                      rehypePlugins={[[rehypeKatex, {
                        throwOnError: false, trust: false, maxExpand: 200, maxSize: 20,
                      }]]}
                    >
                      {`$$\n${result.expression.sourceText}\n$$`}
                    </ReactMarkdown>
                  ) : (
                    <pre><code>{result.expression.sourceText}</code></pre>
                  )}
                </div>
              )}
              <p className="desk-help">
                {result.sourceLocation ? `Recorded location: ${result.sourceLocation}. ` :
                  "Precise section or page not recorded. "}
                {result.expression ? "Expression checked literally; no symbolic transformation. " :
                  "No source-verified expression recorded. "}
                Source integrity: {result.sourceArtifactHash.slice(0, 12)}…
              </p>
              <div className="technical-result-sources">
                {result.sourceIds.map((sourceId) => (
                  <button
                    key={sourceId}
                    type="button"
                    onClick={(event) => onOpenSource(sourceId, event.currentTarget)}
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
    </section>
  );
}
