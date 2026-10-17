import type {
  ReportDocument,
  ReportDocumentV2,
  ReportDocumentV3,
  ReportDocumentV4,
} from "@research/contracts";

type AssessedReport = ReportDocumentV2 | ReportDocumentV3 | ReportDocumentV4;

const outcomeLabels = {
  established: "Established",
  partially_established: "Partially established",
  not_established: "Not established",
  not_assessed: "Not assessed",
} as const;
const dimensionLabels = {
  not_started: "Not started",
  searching: "Searching",
  evidence_found: "Evidence found",
  verified_covered: "Verified coverage",
  unresolved: "Unresolved",
  blocked: "Blocked",
} as const;
const narrativeReasons = {
  no_verified_findings: "No verified findings were available to organize.",
  insufficient_time: "Not enough active time remained to verify a narrative.",
  writer_unavailable: "The narrative writer was not configured.",
  composition_failed:
    "Narrative composition did not complete; verified findings are shown in section order.",
  no_supported_sentences:
    "No proposed narrative sentence passed exact-span and semantic review.",
} as const;
const narrativeRoles = {
  answer: "Direct answer",
  dimension: "Research dimension",
  synthesis: "Cross-source synthesis",
  tradeoffs: "Trade-offs and caveats",
  implications: "Implications",
} as const;
const criterionLabels = {
  met: "Met",
  partial: "Partially met",
  not_met: "Not met",
  unknown: "Unknown",
} as const;

function SupportingFindings({
  ids,
  findings,
  sourceTitles,
}: {
  ids: string[];
  findings: ReportDocument["findings"];
  sourceTitles: Map<string, string>;
}) {
  if (!ids.length) return null;
  const selected = new Set(ids);
  return (
    <details>
      <summary>Supporting verified findings ({ids.length})</summary>
      <ul>
        {findings
          .filter((finding) => selected.has(finding.id))
          .map((finding) => {
            const titles = finding.sourceIds.map(
              (id) => sourceTitles.get(id) ?? "Source",
            );
            return (
              <li key={finding.id}>
                {finding.text}
                {titles.length > 0 && (
                  <p className="desk-help">
                    Evidence sources: {titles.join("; ")}
                  </p>
                )}
              </li>
            );
          })}
      </ul>
    </details>
  );
}

function AssessedCoverage({
  document,
  sources,
}: {
  document: AssessedReport;
  sources: { id: string; title: string }[];
}) {
  const requirements = new Map(
    document.requirements.map((row) => [row.id, row.text]),
  );
  const dimensions = new Map(
    document.dimensions.map((row) => [row.id, row.label]),
  );
  const sourceTitles = new Map(
    sources.map((source) => [source.id, source.title]),
  );
  return (
    <>
      <details>
        <summary>
          Requirement coverage ({document.requirementOutcomes.length})
        </summary>
        <p className="desk-help">
          Outcomes reflect recorded criterion reviews. Evidence links alone do
          not establish a requirement or certify the whole answer.
        </p>
        <ul>
          {document.requirementOutcomes.map((row) => (
            <li key={row.id}>
              <strong>{requirements.get(row.id)}</strong>
              {" — "}
              {outcomeLabels[row.outcome]}
              <p>{row.reason}</p>
              {row.dimensionIds.length > 0 && (
                <p className="desk-help">
                  Linked dimensions:{" "}
                  {row.dimensionIds.map((id) => dimensions.get(id)).join("; ")}
                </p>
              )}
              <SupportingFindings
                ids={row.claimIds}
                findings={document.findings}
                sourceTitles={sourceTitles}
              />
            </li>
          ))}
        </ul>
      </details>
      <details>
        <summary>Research dimensions ({document.dimensions.length})</summary>
        {document.dimensions.length === 0 ? (
          <p>No assessed dimensions were recorded.</p>
        ) : (
          <ul>
            {document.dimensions.map((row) => (
              <li key={row.id}>
                <strong>{row.label}</strong>
                {" — "}
                {dimensionLabels[row.status]}
                <p>{row.reason}</p>
                <p className="desk-help">
                  Assessment basis:{" "}
                  {row.basis === "criterion-review-v1"
                    ? "Criterion review"
                    : "Not assessed"}
                  .
                </p>
                <details>
                  <summary>Planned criteria ({row.criteria.length})</summary>
                  <ol>
                    {row.criteria.map((criterion) => (
                      <li key={criterion.id}>
                        <strong>{criterionLabels[criterion.outcome]}</strong>
                        {" — "}
                        {criterion.reason}
                        <p className="desk-help">
                          Assessment basis:{" "}
                          {criterion.basis === "criterion-review-v1"
                            ? "Criterion review"
                            : "Not assessed"}
                          .
                        </p>
                        <SupportingFindings
                          ids={criterion.claimIds}
                          findings={document.findings}
                          sourceTitles={sourceTitles}
                        />
                      </li>
                    ))}
                  </ol>
                </details>
                <SupportingFindings
                  ids={row.claimIds}
                  findings={document.findings}
                  sourceTitles={sourceTitles}
                />
              </li>
            ))}
          </ul>
        )}
      </details>
      {document.version === 4 && (
        <NarrativeComposition document={document} dimensions={dimensions} />
      )}
      {document.version >= 3 && "sourceRelationships" in document && (
        <>
          <details>
            <summary>
              Observed source relationships (
              {document.sourceRelationships.length})
            </summary>
            <p className="desk-help">
              Related records can overlap; this does not establish independent
              corroboration. Content hashes are intentionally not shown.
            </p>
            {document.sourceRelationships.length === 0 ? (
              <p>No source relationships were observed.</p>
            ) : (
              <ul>
                {document.sourceRelationships.map((row) => (
                  <li key={`${row.fromSourceId}:${row.toSourceId}:${row.kind}`}>
                    <strong>
                      {row.kind === "same_content"
                        ? "Same extracted content"
                        : row.kind === "same_work"
                          ? "Same DOI-identified work"
                          : "Same verified publisher metadata"}
                    </strong>
                    {": "}
                    {sourceTitles.get(row.fromSourceId) ?? "Source"}
                    {" ↔ "}
                    {sourceTitles.get(row.toSourceId) ?? "Source"}
                    {row.identifier ? ` (${row.identifier})` : ""}
                    {" — "}
                    {row.confidence}
                  </li>
                ))}
              </ul>
            )}
          </details>
          <details>
            <summary>
              Potential disagreements ({document.conflicts.length})
            </summary>
            <p className="desk-help">
              These are reviewer-nominated possibilities, not confirmed or
              adjudicated contradictions. Review both findings and their
              citations.
            </p>
            {document.conflicts.length === 0 ? (
              <p>No potential disagreements were recorded.</p>
            ) : (
              <ul>
                {document.conflicts.map((conflict) => (
                  <li key={conflict.id}>
                    <strong>
                      {dimensions.get(conflict.dimensionId) ??
                        "Research dimension"}
                    </strong>
                    <p>Potential disagreement · unresolved</p>
                    <p>{conflict.reason}</p>
                    <SupportingFindings
                      ids={conflict.claimIds}
                      findings={document.findings}
                      sourceTitles={sourceTitles}
                    />
                  </li>
                ))}
              </ul>
            )}
          </details>
        </>
      )}
      <p className="desk-help">
        Source independence: unknown. {document.sourceIndependence.reason}
      </p>
    </>
  );
}

function NarrativeComposition({
  document,
  dimensions,
}: {
  document: ReportDocumentV4;
  dimensions: Map<string, string>;
}) {
  const narrative = document.narrative;
  return (
    <details>
      <summary>
        Narrative composition (
        {narrative.status === "composed"
          ? `${narrative.publishedSentenceCount} verified sentences`
          : "not composed"}
        )
      </summary>
      <p className="desk-help">
        Every narrative sentence is a verified finding with its own citations.
        Newly proposed explanations are published only after exact-span and
        semantic review; there is no unverified connecting prose.
      </p>
      {narrative.status === "composed" ? (
        <>
          <p>
            {narrative.proposedSentenceCount} proposed ·{" "}
            {narrative.publishedSentenceCount} published ·{" "}
            {narrative.rejectedSentenceCount} withheld ·{" "}
            {narrative.narrativeClaimIds.length} newly verified
          </p>
          <ol>
            {narrative.blocks.map((block) => (
              <li key={block.id}>
                <strong>{narrativeRoles[block.role]}</strong>
                {block.dimensionId
                  ? ` — ${dimensions.get(block.dimensionId) ?? "Planned dimension"}`
                  : ""}
                {` (${block.sentences.length})`}
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p>
          {narrative.reason
            ? narrativeReasons[narrative.reason]
            : narrativeReasons.composition_failed}
        </p>
      )}
    </details>
  );
}

/** Keep historical association labels separate from V2 assessed outcomes. */
export function ReportCoverage({
  document,
  sources = [],
}: {
  document: ReportDocument;
  sources?: { id: string; title: string }[];
}) {
  if (document.version >= 2 && "requirementOutcomes" in document)
    return <AssessedCoverage document={document} sources={sources} />;
  return (
    <details>
      <summary>Question and report requirements</summary>
      <p className="desk-help">
        Evidence links are not proof that a requirement is fully satisfied.
      </p>
      <ul>
        {document.requirements.map((requirement) => (
          <li key={requirement.id}>
            <strong>{requirement.text}</strong>
            {" — "}
            {requirement.status === "addressed"
              ? "Evidence linked; completeness not established"
              : "Unresolved"}
          </li>
        ))}
      </ul>
    </details>
  );
}
