from research_api.providers.scholarly_identity import (
    ScholarlyIndexRecord,
    deduplicate,
    same_work,
)


def _record(provider: str, **kwargs: object) -> ScholarlyIndexRecord:
    return ScholarlyIndexRecord(
        provider=provider, provider_id=provider, title="A clinical trial", **kwargs
    )


def test_matching_doi_across_providers_is_one_candidate() -> None:
    records = [
        _record("crossref", doi="https://doi.org/10.1000/ABC"),
        _record("openalex", doi="doi:10.1000/abc"),
    ]
    assert deduplicate(records) == records[:1]


def test_distinct_dois_never_merge_on_same_title() -> None:
    assert not same_work(
        _record("a", doi="10.1000/one", publication_year=2025),
        _record("b", doi="10.1000/two", publication_year=2025),
    )


def test_title_fallback_requires_matching_year_and_no_identifiers() -> None:
    assert same_work(_record("a", publication_year=2025), _record("b", publication_year=2025))
    assert not same_work(_record("a", publication_year=2024), _record("b", publication_year=2025))
