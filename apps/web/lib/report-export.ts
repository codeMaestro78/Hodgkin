type ExportRun = {
  originalQuestion: string;
  report: {
    version: number;
    markdown: string;
    publishedAt: string;
    document?: {
      quality: { status: string; reason: string };
      requirements: {
        id: string;
        text: string;
        status: string;
        claimIds: string[];
      }[];
    } | null;
  } | null;
  sources: { id: string; title: string; url: string }[];
  claimChecks?: {
    claim: string;
    status?: string;
    citations: {
      sourceId: string;
      quote: string;
      exactSpanVerified: boolean;
      verdict: string;
    }[];
  }[];
  insights?: { gaps: { description: string; why: string; status: string }[] };
};
const escape = (value: string) =>
  value.replace(/[\\`*_{}[\]<>|]/g, "\\$&").replaceAll("\n", " ");

export function reportExport(run: ExportRun): string {
  if (!run.report) return "";
  const output = [
    `# ${escape(run.originalQuestion)}`,
    `Report version ${run.report.version} · ${run.report.publishedAt}`,
    run.report.markdown.trim(),
    "## Verification summary",
    "Exact passage checks and model support reviews are not factual certification. Unchecked legacy prose is not implied to be verified.",
  ];
  output.push(
    "## Answer quality and requirement coverage",
    run.report.document
      ? `${escape(run.report.document.quality.status)}: ${escape(run.report.document.quality.reason)}`
      : "Not assessed: this historical report has no structured coverage assessment.",
  );
  for (const requirement of run.report.document?.requirements ?? [])
    output.push(
      `- ${escape(requirement.text)} — ${requirement.status === "addressed" ? "Evidence linked; completeness not established" : "Unresolved"}.`,
    );
  for (const claim of run.claimChecks ?? []) {
    output.push(
      `### ${escape(claim.claim)}`,
      `Assessment: ${(claim.status ?? "not_checked").replaceAll("_", " ")}`,
    );
    for (const citation of claim.citations) {
      const source = run.sources.find((item) => item.id === citation.sourceId);
      output.push(
        `> ${citation.quote.replaceAll("\n", "\n> ")}`,
        `Exact passage: ${citation.exactSpanVerified ? "matched" : "not established"}; model review: ${citation.verdict.replaceAll("_", " ")}.`,
      );
      if (source && /^https?:\/\//i.test(source.url))
        output.push(
          `[${escape(source.title)}](${source.url.replaceAll("(", "%28").replaceAll(")", "%29")})`,
        );
    }
  }
  if (!run.claimChecks?.length)
    output.push("No claim checks were recorded for this report.");
  output.push("## Research gaps and limitations");
  if (run.insights?.gaps.length)
    for (const gap of run.insights.gaps)
      output.push(
        `- ${escape(gap.description)} (${gap.status}). ${escape(gap.why)}`,
      );
  else
    output.push(
      "No gaps were recorded; this does not establish exhaustive coverage.",
    );
  output.push(
    "## Methodology",
    "The research plan collected preserved evidence within the selected provider/source ceiling. Published checked findings require exact passages and supportive model review. Follow-ups collect fresh evidence and preserve the parent report.",
  );
  return output.join("\n\n") + "\n";
}
