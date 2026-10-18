type Finding = { text: string; sourceIds: string[] };
type Source = { id: string; title: string; url: string };

export function VerifiedFindingsPreview({
  findings,
  total,
  sources,
  onOpenSource,
}: {
  findings: Finding[];
  total?: number;
  sources: Source[];
  onOpenSource: (sourceId: string) => void;
}) {
  const byId = new Map(sources.map((source) => [source.id, source]));
  return (
    <section className="verified-preview" aria-labelledby="verified-preview-title">
      <div className="verified-preview-heading">
        <div>
          <h2 id="verified-preview-title">Evidence-checked findings</h2>
          <p>The report and coverage review are still in progress.</p>
        </div>
        <span>{total ?? findings.length} checked</span>
      </div>
      <ol>
        {findings.map((finding, index) => (
          <li key={`${index}-${finding.text}`}>
            <p>{finding.text}</p>
            <div className="verified-preview-sources">
              {finding.sourceIds.map((sourceId) => {
                const source = byId.get(sourceId);
                return source ? (
                  <button
                    key={sourceId}
                    type="button"
                    onClick={() => onOpenSource(sourceId)}
                  >
                    Inspect {source.title || "source"}
                  </button>
                ) : null;
              })}
            </div>
          </li>
        ))}
      </ol>
      <p className="verified-preview-note">
        These claims passed the recorded passage and support checks. The final
        report may organize or omit them after coverage assessment.
      </p>
    </section>
  );
}
