import asyncio
from dataclasses import replace

import httpx
import pytest

from research_api.providers.crossref import (
    CrossrefAdapter,
    CrossrefCancelledAfterDispatch,
    CrossrefCancelledBeforeDispatch,
    CrossrefRequestError,
)
from research_api.providers.doi import normalize_doi


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1234/ABC.5", "10.1234/abc.5"),
        (" doi:10.1234/ABC.5 ", "10.1234/abc.5"),
        ("https://doi.org/10.1234/ABC.5", "10.1234/abc.5"),
        ("http://dx.doi.org/10.1234/ABC.5", "10.1234/abc.5"),
        ("https://doi.org/10.1234/a%23b", "10.1234/a#b"),
        ("10.1234/A.B.", "10.1234/a.b."),
    ],
)
def test_normalize_doi_equivalent_forms(value, expected):
    assert normalize_doi(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        "",
        "10.123/x",
        "10.1234/",
        "10.1234/a b",
        "10.1234/a\n",
        "10.1234/a/../b",
        "https://example.org/10.1234/x",
        "https://doi.org.evil.test/10.1234/x",
        "https://user@doi.org/10.1234/x",
        "https://doi.org:444/10.1234/x",
        "https://doi.org/10.1234/x?foo=bar",
        "https://doi.org/10.1234/x#frag",
        "10.1234/" + "x" * 2048,
    ],
)
def test_normalize_doi_rejects_invalid_or_unsafe_values(value):
    assert normalize_doi(value) is None


def work(**overrides):
    return {
        "DOI": "10.1234/ABC.5",
        "title": ["  A   bounded study  "],
        "author": [
            {
                "given": "Ada",
                "family": "Researcher",
                "affiliation": [{"name": "Example University"}],
            }
        ],
        "published": {"date-parts": [[2024, 3, 10]]},
        "type": "journal-article",
        "container-title": ["Example Journal"],
        "publisher": "Example Press",
        "is-referenced-by-count": 7,
        "abstract": "<jats:p>Untrusted <jats:italic>publisher</jats:italic> abstract.</jats:p>",
        "funder": [
            {"name": "Research Fund", "DOI": "https://doi.org/10.13039/ABC", "award": ["A-1"]}
        ],
        "license": [
            {
                "URL": "https://creativecommons.org/licenses/by/4.0/",
                "start": {"date-parts": [[2024, 3, 1]]},
                "content-version": "vor",
            }
        ],
        "link": [{"URL": "https://other.example/full-text"}],
        **overrides,
    }


def test_lookup_request_is_versioned_canonical_and_rejects_bad_dois():
    first = CrossrefAdapter.lookup_request(doi="https://doi.org/10.1234/ABC.5")
    second = CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
    assert first == second
    assert first.operation == "works.lookup"
    assert first.payload == {"doi": "10.1234/abc.5"}
    assert first.request_schema_version == "crossref-work-v1"
    with pytest.raises(ValueError):
        CrossrefAdapter.lookup_request(doi="not a doi")
    with pytest.raises(ValueError):
        CrossrefAdapter(max_attempts=4)
    with pytest.raises(ValueError):
        CrossrefAdapter(timeout=float("inf"))


async def test_lookup_returns_only_bounded_metadata_and_closes_only_owned_client():
    def handler(request):
        assert request.method == "GET"
        assert request.url.host == "api.crossref.org"
        assert request.url.path == "/works/10.1234/abc.5"
        assert request.headers["accept"] == "application/json"
        assert not request.url.params
        return httpx.Response(200, json={"message": work()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CrossrefAdapter(client=client)
        result = await adapter.lookup(adapter.lookup_request(doi="doi:10.1234/ABC.5"))
        await adapter.aclose()
        assert not client.is_closed

    assert result.attempt_count == 1
    assert result.response_schema_version == "crossref-work-v2"
    metadata = result.metadata
    assert metadata.evidence_status == "discovery_only"
    assert metadata.doi == "10.1234/abc.5"
    assert metadata.title == "A bounded study"
    assert metadata.authors == ("Ada Researcher",)
    assert metadata.author_affiliations == (("Example University",),)
    assert metadata.publication_date.isoformat() == "2024-03-10"
    assert metadata.venue == "Example Journal"
    assert metadata.publisher == "Example Press"
    assert metadata.citation_count == 7
    assert metadata.abstract == "Untrusted publisher abstract."
    assert len(metadata.funders) == 1
    assert metadata.funders[0].name == "Research Fund"
    assert metadata.funders[0].doi == "10.13039/abc"
    assert metadata.funders[0].award_numbers == ("A-1",)
    assert len(metadata.licenses) == 1
    assert metadata.licenses[0].url == "https://creativecommons.org/licenses/by/4.0/"
    assert metadata.licenses[0].start_date.isoformat() == "2024-03-01"
    assert metadata.licenses[0].content_version == "vor"
    assert metadata.landing_page_url == "https://doi.org/10.1234/abc.5"
    assert "content" not in metadata.model_dump()
    assert "evidence" not in metadata.model_dump()
    assert "full_text_url" not in metadata.model_dump()
    assert "https://other.example/full-text" not in str(metadata.model_dump())


async def test_malformed_and_oversized_optional_metadata_is_bounded_without_becoming_evidence():
    many_affiliations = [{"name": "Institute " + "X" * 400}] * 20
    many_funders = [{"name": "Fund " + "F" * 400, "award": ["A" * 200] * 20}] * 30
    many_licenses = [{"URL": "javascript:alert(1)"}] * 10 + [
        {"URL": "https://example.org/license", "start": {"date-parts": [[2024, 13, 1]]}}
    ]
    payload = work(
        author=[
            {"given": "Ada", "family": "Researcher", "affiliation": many_affiliations},
            {"given": "Lin", "family": "Researcher", "affiliation": "bad"},
            {"given": 12, "family": None, "affiliation": many_affiliations},
        ],
        abstract="<jats:p>Safe &amp; bounded</jats:p><script>not evidence</script>" + "X" * 100_000,
        funder=[None, {"name": None, "DOI": "invalid"}, *many_funders],
        license=many_licenses,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"message": payload}))
    ) as client:
        metadata = (
            await CrossrefAdapter(client=client).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
        ).metadata
    assert metadata.evidence_status == "discovery_only"
    assert metadata.authors == ("Ada Researcher", "Lin Researcher")
    assert len(metadata.author_affiliations) == len(metadata.authors)
    assert len(metadata.author_affiliations[0]) == 10
    assert len(metadata.author_affiliations[0][0]) == 300
    assert metadata.author_affiliations[1] == ()
    assert metadata.abstract.startswith("Safe & bounded ")
    assert "not evidence" not in metadata.abstract
    assert len(metadata.abstract) == 12_000
    assert len(metadata.funders) == 20
    assert len(metadata.funders[0].name) == 300
    assert len(metadata.funders[0].award_numbers) == 10
    assert len(metadata.funders[0].award_numbers[0]) == 100
    assert len(metadata.licenses) == 1
    assert metadata.licenses[0].start_date is None


async def test_license_url_validation_and_missing_optional_metadata():
    payload = work(
        abstract=None,
        funder={"name": "not a list"},
        license=[
            None,
            {"URL": "https://user:pass@example.org/license"},
            {"URL": "file:///local"},
            {"URL": "https://example.org/license", "start": {"date-parts": [[2024]]}},
        ],
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"message": payload}))
    ) as client:
        metadata = (
            await CrossrefAdapter(client=client).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
        ).metadata
    assert metadata.abstract is None
    assert metadata.funders == ()
    assert len(metadata.licenses) == 1
    assert metadata.licenses[0].start_date.isoformat() == "2024-01-01"


async def test_special_doi_suffix_is_encoded_without_changing_identity():
    def handler(request):
        assert request.url.raw_path == b"/works/10.1234/a%23b"
        return httpx.Response(200, json={"message": work(DOI="10.1234/a#b")})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await CrossrefAdapter(client=client).lookup(
            CrossrefAdapter.lookup_request(doi="https://doi.org/10.1234/a%23b")
        )
    assert result.metadata.landing_page_url == "https://doi.org/10.1234/a%23b"


@pytest.mark.parametrize("body", [{}, {"message": []}, {"message": work(DOI="10.5555/other")}])
async def test_invalid_envelope_or_mismatched_doi_is_consumed(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(CrossrefRequestError) as error:
            await CrossrefAdapter(client=client).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
    assert error.value.outcome == "consumed"
    assert error.value.attempt_count == 1


async def test_invalid_json_is_consumed():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="{"))
    ) as client:
        with pytest.raises(CrossrefRequestError) as error:
            await CrossrefAdapter(client=client).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
    assert error.value.outcome == "consumed"


async def test_invalid_request_is_rejected_before_dispatch():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"message": work()})

    valid = CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CrossrefAdapter(client=client)
        for invalid in (
            replace(valid, payload={"doi": "10.1234/other"}),
            replace(valid, payload={"doi": "10.1234/abc.5", "extra": 1}),
            replace(valid, fingerprint="wrong"),
            replace(valid, operation="search"),
        ):
            with pytest.raises(ValueError, match="Invalid Crossref lookup request"):
                await adapter.lookup(invalid)
    assert calls == 0


@pytest.mark.parametrize(
    ("status", "outcome"), [(404, "released"), (429, "uncertain"), (500, "uncertain")]
)
async def test_http_failure_outcomes_are_bounded(status, outcome):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CrossrefRequestError) as error:
            await CrossrefAdapter(client=client, max_attempts=3).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
    assert calls == 1
    assert error.value.outcome == outcome


async def test_pre_dispatch_failure_retries_but_read_timeout_does_not(monkeypatch):
    calls = 0

    async def no_delay(_):
        return None

    monkeypatch.setattr("research_api.providers.crossref.retry_delay", no_delay)

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("private transport detail", request=request)
        return httpx.Response(200, json={"message": work()})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await CrossrefAdapter(client=client).lookup(
            CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
        )
    assert calls == 2 and result.attempt_count == 2

    calls = 0

    def timeout_handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("private detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as client:
        with pytest.raises(CrossrefRequestError) as error:
            await CrossrefAdapter(client=client, max_attempts=3).lookup(
                CrossrefAdapter.lookup_request(doi="10.1234/abc.5")
            )
    assert calls == 1 and error.value.outcome == "uncertain"


async def test_cancellation_before_and_after_dispatch():
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError

    async def cancel():
        raise asyncio.CancelledError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = CrossrefAdapter(client=client)
        request = adapter.lookup_request(doi="10.1234/abc.5")
        with pytest.raises(CrossrefCancelledBeforeDispatch) as before:
            await adapter.lookup(request, before_attempt=cancel)
        assert before.value.attempt_count == 0
        assert calls == 0
        with pytest.raises(CrossrefCancelledAfterDispatch) as after:
            await adapter.lookup(request)
        assert after.value.attempt_count == 1
    assert calls == 1
