"""Publication-time snapshot of source retrieval and evidence-use accounting."""

from collections.abc import Mapping, Sequence
from typing import Any

from research_api.retrieval_accounting import build_retrieval_accounting


def build_report_retrieval_snapshot(
    *,
    calls: Sequence[Mapping[str, object]],
    sources: Sequence[Mapping[str, object]],
    claim_checks: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Freeze only recorded counts; unmeasured relevance stays explicitly unassessed."""
    return build_retrieval_accounting(calls=calls, sources=sources, claim_checks=claim_checks)


def retrieval_accounting_markdown(snapshot: Mapping[str, Any]) -> str:
    """Render compact, deterministic count-only methodology for report artifacts."""

    def display(value: object) -> str:
        return (
            str(value) if isinstance(value, int) and not isinstance(value, bool) else "not recorded"
        )

    lines = [
        "## Retrieval accounting (recorded at publication)",
        "",
        "Counts describe persisted activity, not relevance, completeness, or source independence.",
        "",
    ]
    providers = snapshot.get("providers")
    for row in providers if isinstance(providers, list) else []:
        if not isinstance(row, Mapping):
            continue
        provider = row.get("provider")
        label = provider.title() if isinstance(provider, str) else "Unknown provider"
        lines.append(
            f"- **{label}:** {display(row.get('discovered'))} discovered; "
            f"{display(row.get('shortlisted'))} shortlisted; "
            f"{display(row.get('excluded'))} excluded; "
            f"{display(row.get('duplicateUrl'))} duplicate URL results; "
            f"{display(row.get('extractedSources'))} extracted; "
            f"{display(row.get('citedInVerifiedFinding'))} cited in verified findings."
        )
    outcomes = snapshot.get("extractionOutcomes")
    if isinstance(outcomes, Mapping):
        lines += [
            "",
            "Extraction outcomes: "
            + ", ".join(
                f"{display(outcomes.get(key))} {key}"
                for key in ("succeeded", "failed", "uncertain", "pending", "other")
            )
            + ".",
        ]
    lines += [
        "",
        f"Citation checks: {display(snapshot.get('citationChecks'))}; "
        f"exact spans verified: {display(snapshot.get('exactSpanVerifiedCitations'))}; "
        f"published claims: {display(snapshot.get('publishedClaims'))}.",
        "Exact-content duplicate source records: "
        f"{display(snapshot.get('exactDuplicateSources'))}.",
        "Source-type counts (metadata labels, not a quality assessment): "
        + (
            ", ".join(
                f"{key} {display(value)}"
                for key, value in sorted(snapshot.get("sourceClasses", {}).items())
            )
            if isinstance(snapshot.get("sourceClasses"), Mapping) and snapshot.get("sourceClasses")
            else "not recorded"
        )
        + ".",
        "Answer usefulness, dimension relevance, and source independence were not assessed.",
    ]
    return "\n".join(lines)
