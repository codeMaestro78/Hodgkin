from uuid import UUID

import pytest

from research_api.source_identity import (
    RelationshipSource,
    SourceIdentity,
    doi_work_id,
    map_source_identity,
    observed_relationships,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://doi.org/10.1234/ABC",
        "http://dx.doi.org/10.1234/abc",
        "https://doi.org/10.1234%2Fabc?tracking=1#section",
    ],
)
def test_observed_doi_normalization(url):
    assert doi_work_id(url) == "doi:10.1234/abc"


@pytest.mark.parametrize(
    "url",
    [
        "10.1234/abc",
        "doi:10.1234/abc",
        "https://nature.com/10.1234/abc",
        "https://doi.org.evil.test/10.1234/abc",
        "https://doi.org@evil.test/10.1234/abc",
        "https://user@doi.org/10.1234/abc",
        "ftp://doi.org/10.1234/abc",
        "https://doi.org:443/10.1234/abc",
        "https://doi.org/10.123/abc",
        "https://doi.org/10.1234/a%0Ab",
        "https://doi.org/10.1234/",
        "https://[invalid/10.1234/abc",
    ],
)
def test_unobserved_or_invalid_doi_is_unknown(url):
    assert doi_work_id(url) is None


def test_conflicting_dois_and_no_host_classification():
    identity = map_source_identity(
        canonical_url="https://university.edu/paper",
        observed_urls=["https://doi.org/10.1234/a", "https://doi.org/10.1234/b"],
        publisher="University",
        publisher_basis={"basis": "hostname", "evidence_ref": "university.edu"},
    )
    assert identity.work_id is None
    assert identity.publisher is None
    assert identity.source_class == identity.independence == "unknown"


def test_verified_publisher_requires_actual_metadata_evidence():
    for basis in (None, {}, {"basis": "structured_metadata", "evidence_ref": " "}):
        assert (
            map_source_identity(
                canonical_url="https://a.test", publisher="Owner", publisher_basis=basis
            ).publisher
            is None
        )
    identity = map_source_identity(
        canonical_url="https://a.test",
        publisher="Owner",
        publisher_basis={"basis": "structured_metadata", "evidence_ref": "artifact:1#publisher"},
    )
    assert identity.publisher == "Owner"
    assert identity.metadata_basis["publisher"]["value"] == "Owner"


def test_three_observed_relationships_are_deterministic_and_not_independence():
    sources = [
        RelationshipSource(
            UUID(int=i),
            "a" * 64,
            map_source_identity(
                canonical_url=f"https://host{i}.test/paper",
                observed_urls=["https://doi.org/10.1234/abc"],
                publisher="Owner",
                publisher_basis={"basis": "adapter_metadata", "evidence_ref": f"artifact:{i}"},
            ),
        )
        for i in (2, 1)
    ]
    rows = observed_relationships(sources)
    assert rows == observed_relationships(list(reversed(sources)))
    assert {row.kind for row in rows} == {"same_content", "same_work", "same_publisher"}
    assert all(row.from_source_id < row.to_source_id for row in rows)
    assert all(row.basis["version"] == "source-identity-v1" for row in rows)
    assert all(source.identity.independence == "unknown" for source in sources)


def test_shared_hostname_title_or_missing_hash_is_not_a_relationship():
    identity = map_source_identity(canonical_url="https://same.test/paper")
    assert (
        observed_relationships(
            [
                RelationshipSource(UUID(int=1), "", identity),
                RelationshipSource(UUID(int=2), "", identity),
            ]
        )
        == []
    )


def test_bare_identity_fields_without_evidence_cannot_assert_relationships():
    identity = SourceIdentity("doi:10.1234/guessed", "Guessed owner", {})
    assert (
        observed_relationships(
            [
                RelationshipSource(UUID(int=1), "", identity),
                RelationshipSource(UUID(int=2), "", identity),
            ]
        )
        == []
    )


def test_pair_bound_and_duplicates():
    identity = map_source_identity(canonical_url="https://test.edu")
    sources = [RelationshipSource(UUID(int=i), "a" * 64, identity) for i in range(21)]
    assert len(observed_relationships(sources[:20])) == 190
    with pytest.raises(ValueError, match="20"):
        observed_relationships(sources)
    with pytest.raises(ValueError, match="distinct"):
        observed_relationships([sources[0], sources[0]])


def test_malformed_equal_hashes_do_not_establish_same_content():
    identity = map_source_identity(canonical_url="https://example.test")
    for invalid in ("unknown", " ", "x" * 64):
        assert (
            observed_relationships(
                [
                    RelationshipSource(UUID(int=1), invalid, identity),
                    RelationshipSource(UUID(int=2), invalid, identity),
                ]
            )
            == []
        )
