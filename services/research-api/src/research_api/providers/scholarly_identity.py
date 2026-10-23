"""Stable identities for merging scholarly discovery records.

These are index records. Neither a match nor an abstract supplies citation evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from research_api.providers.doi import normalize_doi

_PMID = re.compile(r"[0-9]{1,12}\Z")
_WORDS = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ScholarlyIndexRecord:
    provider: str
    provider_id: str
    title: str
    doi: str | None = None
    pmid: str | None = None
    publication_year: int | None = None


def _title_tokens(value: str) -> set[str]:
    return {part.casefold() for part in _WORDS.findall(value)}


def same_work(left: ScholarlyIndexRecord, right: ScholarlyIndexRecord) -> bool:
    """Conservative merge: identifiers win; title similarity needs a shared year."""
    left_doi, right_doi = normalize_doi(left.doi), normalize_doi(right.doi)
    if left_doi and right_doi:
        return left_doi == right_doi
    if left.pmid and right.pmid and _PMID.fullmatch(left.pmid) and _PMID.fullmatch(right.pmid):
        return left.pmid == right.pmid
    if left_doi or right_doi or left.pmid or right.pmid:
        return False
    if not left.publication_year or left.publication_year != right.publication_year:
        return False
    a, b = _title_tokens(left.title), _title_tokens(right.title)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.95


def deduplicate(records: list[ScholarlyIndexRecord]) -> list[ScholarlyIndexRecord]:
    """Retain first occurrences for candidate selection, not audit storage."""
    result: list[ScholarlyIndexRecord] = []
    for record in records:
        if not any(same_work(record, previous) for previous in result):
            result.append(record)
    return result
