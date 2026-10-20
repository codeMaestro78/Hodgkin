"""Bounded report composition from the admitted factual ledger, with no model I/O.

Headings and method/coverage notes are fixed presentation text or explicitly
labelled scope inputs. Factual paragraphs and cells are exact finding copies.
New explanatory assertions must pass the normal writer/evidence gate first.
"""

import re
from dataclasses import dataclass
from typing import Any

from research_api.report_document import validate_report_document

NARRATIVE_HEADINGS = {
    "synthesis": "Cross-source synthesis",
    "tradeoffs": "Trade-offs and caveats",
    "implications": "Implications",
}
PARAGRAPH_SENTENCES = 4
_NARRATIVE_REASONS = {
    "no_verified_findings": "no verified findings were available",
    "insufficient_time": "the remaining active time could not safely cover it",
    "writer_unavailable": "the writer model was unavailable",
    "composition_failed": "the narrative proposal could not be completed or validated",
    "no_supported_sentences": "no proposed sentence survived evidence checks",
}


def _narrative_note(narrative: dict[str, Any]) -> list[str]:
    if narrative["status"] != "composed":
        return [
            "Narrative composition was not applied because "
            + _NARRATIVE_REASONS[narrative["reason"]]
            + "; verified findings are grouped by report section.",
            "",
        ]
    return [
        f"Narrative composition published {narrative['publishedSentenceCount']} of "
        f"{narrative['proposedSentenceCount']} proposed sentences, including "
        f"{len(narrative['narrativeClaimIds'])} new explanatory findings that passed the "
        "same exact-passage and semantic-review gate. Headings are fixed presentation "
        "labels; no unverified connective prose was added.",
        "",
    ]


@dataclass(frozen=True)
class FactualBlock:
    text: str
    claim_ids: tuple[str, ...]


def validate_alignment(document: dict[str, Any], blocks: list[FactualBlock]) -> None:
    """Reject added prose or altered facts, even when a valid citation is attached."""
    claims = {f["id"]: f for f in document["findings"]}
    for block in blocks:
        if len(block.claim_ids) != 1 or block.claim_ids[0] not in claims:
            raise ValueError("Factual blocks require exactly one verified finding")
        finding = claims[block.claim_ids[0]]
        if block.text != finding["text"] or not finding["citationIds"]:
            raise ValueError("Factual prose must exactly match the admitted claim ledger")


def compose_report(document: dict[str, Any], *, sources: list[tuple[str, str, str]]) -> str:
    doc = validate_report_document(document)
    if doc["version"] not in {2, 3, 4, 5}:
        raise ValueError("Explicit report composition requires report document V2-V5")
    claims = {f["id"]: f for f in doc["findings"]}
    source_numbers = {source_id: index + 1 for index, (source_id, _, _) in enumerate(sources)}
    if len(source_numbers) != len(sources):
        raise ValueError("Duplicate source identities")
    if any(not set(f["sourceIds"]) <= source_numbers.keys() for f in claims.values()):
        raise ValueError("A finding references an unavailable source")
    blocks: list[FactualBlock] = []

    def fact(key: str, *, table: bool = False) -> str:
        finding = claims[key]
        blocks.append(FactualBlock(finding["text"], (key,)))
        text = finding["text"]
        if table:
            # Escape Markdown structure, not the underlying factual-block text.
            text = text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
        refs = " ".join(f"[{source_numbers[s]}]" for s in finding["sourceIds"])
        return f"{text} {refs}"

    def scope(text: str) -> str:
        # Inputs are scope metadata, never factual findings. Keep headings one line.
        return text.replace("\r", " ").replace("\n", " ").replace("|", "\\|")

    lines = []
    mode = doc["mode"]
    if mode == "deep":
        lines += [
            "## Scope and research questions",
            "",
            "Research question (user input):",
            "",
            "> " + scope(doc["title"]),
            "",
        ]
        for requirement in doc["requirements"][1:]:
            lines += ["- Requested scope: " + scope(requirement["text"])]
        lines += [""]
    narrative = doc.get("narrative") if doc["version"] >= 4 else None
    published: set[str] = set()
    if narrative and narrative["status"] == "composed":
        dimension_labels = {d["id"]: d["label"] for d in doc["dimensions"]}
        for block in narrative["blocks"]:
            role = block["role"]
            if role == "answer":
                lines += ["## Direct answer" if mode == "focused" else "## Executive answer", ""]
            elif role == "dimension":
                lines += [
                    "## Research dimension",
                    "",
                    "Dimension (planned scope): " + scope(dimension_labels[block["dimensionId"]]),
                    "",
                ]
            else:
                lines += ["## " + NARRATIVE_HEADINGS[role], ""]
            keys = [sentence["claimId"] for sentence in block["sentences"]]
            # Group exact findings into short paragraphs; no connective prose is added.
            for start in range(0, len(keys), PARAGRAPH_SENTENCES):
                chunk = keys[start : start + PARAGRAPH_SENTENCES]
                lines += [" ".join(fact(key) for key in chunk), ""]
            published.update(keys)
        if set(claims) - published:
            lines += ["## Additional verified findings", ""]
            for section in doc["sections"]:
                for key in section["claimIds"]:
                    if key not in published:
                        lines += [fact(key), ""]
                        published.add(key)
    else:
        overview: list[str] = next(
            (s["claimIds"] for s in doc["sections"] if s["id"] == "overview"), []
        )
        if overview:
            lines += ["## Direct findings" if mode == "focused" else "## Executive findings", ""]
            for key in overview:
                lines += [fact(key), ""]
        elif not claims:
            lines += [
                "## Answer not established",
                "",
                "The collected evidence did not yield publishable verified findings.",
                "",
            ]
        published.update(overview)
        if mode in {"balanced", "deep"}:
            for dimension in doc["dimensions"]:
                keys = [key for key in dimension["claimIds"] if key not in published]
                if not keys:
                    continue
                lines += [
                    "## Findings for research dimension",
                    "",
                    "Dimension (planned scope): " + scope(dimension["label"]),
                    "",
                ]
                for key in keys:
                    lines += [fact(key), ""]
                    published.add(key)
        for section in doc["sections"]:
            keys = [key for key in section["claimIds"] if key not in published]
            if keys:
                lines += ["## " + section["title"], ""]
                for key in keys:
                    lines += [fact(key), ""]
                    published.add(key)
    if published != set(claims):
        raise ValueError("Every verified finding must appear in the report")
    if doc["version"] >= 5 and doc["technicalResults"]:
        lines += ["<!-- technical-results-v1:start -->", "## Source-stated technical results", ""]
        lines += [
            "Expressions below are literal excerpts checked against the cited passage; "
            "they are not independently proven or symbolically re-derived.",
            "",
        ]
        for result in doc["technicalResults"]:
            lines += [f"### {scope(result['title'])}", "", fact(result["claimId"]), ""]
            if result["sourceLocation"]:
                lines += ["Source location: " + scope(result["sourceLocation"]), ""]
            for assumption in result["assumptions"]:
                lines += ["- Source-stated condition: " + scope(assumption)]
            for notation in result["notation"]:
                lines += ["- Source notation: " + scope(notation)]
            if result["assumptions"] or result["notation"]:
                lines += [""]
            if expression := result["expression"]:
                source_text = expression["sourceText"]
                fence = "`" * max(
                    3, max((len(part) for part in re.findall(r"`+", source_text)), default=0) + 1
                )
                lines += ["Literal source expression:", "", fence, source_text, fence, ""]
        lines += ["<!-- technical-results-v1:end -->", ""]
    for comparison in doc["comparisons"]:
        dimension = next(d for d in doc["dimensions"] if d["id"] == comparison["dimensionId"])
        lines += [
            "## Evidence comparison",
            "",
            "Compared dimension (planned scope): " + scope(dimension["label"]),
            "",
            "| Alternative | Verified evidence |",
            "| --- | --- |",
        ]
        for cell in comparison["cells"]:
            value = "<br><br>".join(fact(key, table=True) for key in cell["claimIds"])
            lines += [f"| {scope(cell['alternative'])} | {value or 'Not established'} |"]
        lines += [""]
    if doc["version"] >= 3 and doc["conflicts"]:
        dimensions = {dimension["id"]: dimension for dimension in doc["dimensions"]}
        lines += [
            "## Potential evidence disagreements",
            "",
            "These are reviewer-nominated possibilities, not adjudicated contradictions. "
            "Both linked findings are retained for inspection.",
            "",
        ]
        for conflict in doc["conflicts"]:
            dimension = dimensions[conflict["dimensionId"]]
            lines += [f"### {scope(dimension['label'])}", ""]
            for claim_id in conflict["claimIds"]:
                lines += ["- Potentially inconsistent finding: " + fact(claim_id), ""]
    if doc["version"] >= 3 and doc["sourceRelationships"]:
        labels = {
            "same_content": "same observed content",
            "same_work": "same DOI-identified work",
            "same_publisher": "same verified publisher metadata",
        }
        lines += [
            "## Observed source relationships",
            "",
            "These identity observations describe overlap; they do not establish independence.",
            "",
        ]
        for relationship in doc["sourceRelationships"]:
            left = source_numbers[relationship["fromSourceId"]]
            right = source_numbers[relationship["toSourceId"]]
            identifier = relationship.get("identifier")
            detail = f" ({scope(identifier)})" if identifier else ""
            lines += [f"- Sources [{left}] and [{right}]: {labels[relationship['kind']]}{detail}."]
        lines += [""]
    lines += ["## Coverage and unresolved requirements", ""]
    labels = {
        "established": "Established by criterion review",
        "partially_established": "Partially established",
        "not_established": "Not established",
        "not_assessed": "Not assessed",
    }
    for outcome in doc["requirementOutcomes"]:
        requirement = next(r for r in doc["requirements"] if r["id"] == outcome["id"])
        lines += [
            f"- **{labels[outcome['outcome']]}** — requested scope: " + scope(requirement["text"])
        ]
    lines += [
        "",
        "## Method and limitations",
        "",
        f"Mode: {mode.capitalize()}. Published {len(claims)} verified findings from "
        f"{len(sources)} preserved source extracts. "
        f"{doc['quality']['excludedFindings']} draft assertions were excluded.",
        "",
        *(_narrative_note(narrative) if narrative else []),
        "Only exact passages with fully supportive semantic reviews enter the factual "
        "ledger. Criterion reviews assess that ledger, not all possible literature. "
        "Source independence remains unknown; content deduplication is not independent "
        "corroboration. This report is not certified as a complete answer.",
        "",
    ]
    if sources:
        lines += ["## Source links", ""]
        for index, (_, title, url) in enumerate(sources, 1):
            # No fabricated author/publication metadata. UI provides citation styles separately.
            lines += [f"{index}. {scope(title)} — {url}"]
        lines += [""]
    validate_alignment(doc, blocks)
    return "\n".join(lines).strip() + "\n"
