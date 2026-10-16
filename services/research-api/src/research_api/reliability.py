"""Deterministic evidence policy. Model judgements never bypass exact passage checks."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit


def report_assertion_span(markdown: str, assertion: str) -> str | None:
    """Locate only literal text, allowing inline emphasis/code and whitespace changes.

    Return the original report slice, never a paraphrase. This is a report-location
    check, NOT a source-quotation check; source passages still require exact bytes.
    """
    if not assertion.strip():
        return None
    if assertion in markdown:
        return assertion

    def projection(value: str) -> tuple[str, list[int], list[int]]:
        characters: list[str] = []
        starts: list[int] = []
        ends: list[int] = []
        start = 0
        for token in re.finditer(r"\*\*|__|`+|\s+|.", value, re.DOTALL):
            part = token.group()
            if part in {"**", "__"} or part.startswith("`"):
                if ends:
                    ends[-1] = token.end()
                continue
            characters.append(" " if part.isspace() else part)
            starts.append(start)
            ends.append(token.end())
            start = token.end()
        return "".join(characters), starts, ends

    text, starts, ends = projection(markdown)
    sought, _, _ = projection(assertion)
    if not sought.strip():
        return None
    index = text.find(sought)
    return markdown[starts[index] : ends[index + len(sought) - 1]] if index >= 0 else None


def claim_status(citations: list[dict[str, Any]]) -> str:
    checked = [item for item in citations if item.get("exactSpanVerified") is True]
    verdicts = [item.get("verdict") for item in checked]
    if "contradicts" in verdicts:
        return "contradicted"
    if not checked:
        return "insufficient_evidence" if citations else "not_checked"
    if "not_recorded" in verdicts:
        return "not_checked"
    if any(verdict not in {"supports", "partially_supports"} for verdict in verdicts):
        return "insufficient_evidence"
    if len(checked) != len(citations):
        return "insufficient_evidence"
    return "partially_supported" if "partially_supports" in verdicts else "supported"


def source_assessments(sources: list[Any], question: str) -> dict[str, dict[str, Any]]:
    """Explain observable metadata. Domain names do not establish authority."""
    counts = Counter(source.content_hash for source in sources)
    identities = {value: f"material-{index}" for index, value in enumerate(sorted(counts), 1)}
    groups = [[source] for source in sources]
    # Union correlated groups so a replica chain has one stable independence label.
    index = 0
    while index < len(groups):
        other = index + 1
        while other < len(groups):
            if any(
                left.content_hash == right.content_hash
                or signatures_match(
                    getattr(left, "content_signature", []), getattr(right, "content_signature", [])
                )
                for left in groups[index]
                for right in groups[other]
            ):
                groups[index].extend(groups.pop(other))
                other = index + 1
            else:
                other += 1
        index += 1
    correlated = {str(source.id): group for group in groups for source in group}
    terms = set(re.findall(r"\w{4,}", question.lower()))
    output = {}
    for source in sources:
        overlap = terms & set(re.findall(r"\w{4,}", source.title.lower()))
        output[str(source.id)] = {
            "publisher": source.publisher or urlsplit(source.canonical_url).hostname,
            "publishedAt": source.published_at.isoformat() if source.published_at else None,
            "retrievedAt": source.retrieved_at.isoformat(),
            "independenceGroup": identities[
                min(other.content_hash for other in correlated[str(source.id)])
            ],
            "sameMaterialCount": len(correlated[str(source.id)]),
            "reasons": [
                f"Title shares {len(overlap)} question terms; not a content relevance verdict.",
                "Publisher authority has not been independently assessed.",
                "Publication date not available."
                if not source.published_at
                else "Publication date supplied in metadata.",
                "Source category unknown."
                if source.source_class == "unknown"
                else f"Recorded category: {source.source_class}.",
                "Identical or near-identical retrieved material; not independent corroboration."
                if len(correlated[str(source.id)]) > 1
                else "No exact-content duplicate found in this run; independence not established.",
            ],
        }
    return output


def content_signature(content: str) -> list[str]:
    words = re.findall(r"\w+", content.casefold())
    if len(words) < 160:
        return []  # Short snippets are not enough to establish near duplication.
    hashes = {
        hashlib.sha256(" ".join(words[index : index + 5]).encode()).hexdigest()[:16]
        for index in range(len(words) - 4)
    }
    return sorted(hashes)[:64]


def signatures_match(left: list[str], right: list[str]) -> bool:
    if len(left) < 64 or len(right) < 64:
        return False
    return len(set(left) & set(right)) / len(set(left) | set(right)) >= 0.90


def passage_context(content: str, quote: str) -> tuple[int | None, int | None, str | None]:
    start = content.find(quote)
    if start < 0:
        return None, None, None
    end = start + len(quote)
    return start, end, content[max(0, start - 180) : min(len(content), end + 180)]


def section_for(markdown: str, claim: str) -> str | None:
    index = markdown.find(claim)
    if index < 0:
        return None
    headings = re.findall(r"^#{1,4}\s+(.+)$", markdown[:index], re.MULTILINE)
    return headings[-1] if headings else "Direct answer"


def uncovered_questions(questions: list[Any], claims: list[Any]) -> list[Any]:
    covered = {str(claim.sub_question_id) for claim in claims if claim.support == "supported"}
    return [item for item in questions if str(item.id) not in covered]
