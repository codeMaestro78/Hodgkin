"""Offline contracts for official subject-specific metadata discovery."""

import httpx
import pytest

from research_api.providers.arxiv import ArxivAdapter, ArxivRequestError
from research_api.providers.clinical_trials import (
    STUDY_FIELDS,
    ClinicalTrialsAdapter,
    ClinicalTrialsRequestError,
)
from research_api.providers.europe_pmc import EuropePMCAdapter, EuropePMCRequestError
from research_api.providers.pubmed import PubMedAdapter, PubMedRequestError


@pytest.mark.parametrize(
    "adapter",
    [PubMedAdapter, EuropePMCAdapter, ArxivAdapter, ClinicalTrialsAdapter],
)
def test_requests_are_bounded_and_fingerprinted(adapter):
    request = adapter.search_request(query="  asthma treatment  ", per_page=3)
    assert request == adapter.search_request(query="asthma treatment", per_page=3)
    assert request.operation == "search"
    assert request.fingerprint
    assert "asthma" in str(request.payload)
    for kwargs in (
        {"query": ""},
        {"query": "x" * 1001},
        {"query": "asthma", "per_page": 0},
        {"query": "asthma", "per_page": 11},
        {"query": "asthma", "per_page": True},
    ):
        with pytest.raises(ValueError):
            adapter.search_request(**kwargs)


async def test_pubmed_uses_bounded_esearch_then_esummary_and_drops_bad_records():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "eutils.ncbi.nlm.nih.gov"
        assert request.url.params["db"] == "pubmed"
        assert request.url.params["retmode"] == "json"
        if request.url.path.endswith("esearch.fcgi"):
            assert request.url.params["retmax"] == "2"
            return httpx.Response(
                200, json={"esearchresult": {"count": "50", "idlist": ["123", "456"]}}
            )
        assert request.url.path.endswith("esummary.fcgi")
        assert request.url.params["id"] == "123,456"
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["123", "456"],
                    "123": {
                        "uid": "123",
                        "title": "  A study  ",
                        "source": "Journal",
                        "pubdate": "2024 Jan",
                        "authors": [{"name": "Ada"}],
                        "articleids": [{"idtype": "doi", "value": "10.1234/EXAMPLE"}],
                        "abstract": "must not leave the adapter",
                    },
                    "456": {"uid": "456", "title": ""},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PubMedAdapter(client=client).search(
            PubMedAdapter.search_request(query="asthma", per_page=2)
        )
    assert len(calls) == 2
    assert result.attempt_count == 2
    assert result.total_count == 50
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.pmid == "123"
    assert candidate.doi == "10.1234/example"
    assert candidate.authors == ("Ada",)
    assert candidate.landing_page_url == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert "abstract" not in candidate.model_dump()


async def test_pubmed_empty_search_avoids_second_call():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PubMedAdapter(client=client).search(
            PubMedAdapter.search_request(query="none")
        )
    assert calls == 1
    assert result.candidates == ()


async def test_europe_pmc_lite_projection_and_result_cap():
    def handler(request):
        assert request.url.host == "www.ebi.ac.uk"
        assert request.url.params["resultType"] == "lite"
        assert request.url.params["pageSize"] == "1"
        return httpx.Response(
            200,
            json={
                "hitCount": 25,
                "resultList": {
                    "result": [
                        {
                            "source": "MED",
                            "id": "123",
                            "pmid": "123",
                            "title": " A paper ",
                            "authorString": "Ada, Lin",
                            "journalTitle": "Journal",
                            "pubYear": "2024",
                            "firstPublicationDate": "2024-03-10",
                            "doi": "10.1234/ABC",
                            "abstractText": "must not leave the adapter",
                        },
                        {"source": "MED", "id": "456", "title": "Not returned"},
                    ]
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await EuropePMCAdapter(client=client).search(
            EuropePMCAdapter.search_request(query="asthma", per_page=1)
        )
    assert result.total_count == 25
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.doi == "10.1234/abc"
    assert candidate.publication_date.isoformat() == "2024-03-10"
    assert candidate.landing_page_url == "https://europepmc.org/article/MED/123"
    assert "abstractText" not in candidate.model_dump()


ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:os="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <os:totalResults>42</os:totalResults>
  <entry><id>http://arxiv.org/abs/2401.01234v2</id><title> A theorem </title>
    <author><name>Ada</name></author><published>2024-01-03T12:00:00Z</published>
    <arxiv:doi>10.1234/EXAMPLE</arxiv:doi>
    <summary>must not leave the adapter</summary></entry>
  <entry><id>https://evil.example/abs/2401.12345</id><title>Bad</title></entry>
</feed>"""


async def test_arxiv_atom_metadata_and_safe_official_url():
    def handler(request):
        assert request.url.host == "export.arxiv.org"
        assert request.url.params["search_query"] == "all:quantum AND all:gravity"
        assert request.url.params["max_results"] == "2"
        return httpx.Response(200, content=ATOM)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ArxivAdapter(client=client).search(
            ArxivAdapter.search_request(query="quantum gravity", per_page=2)
        )
    assert result.total_count == 42
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.arxiv_id == "2401.01234v2"
    assert candidate.doi == "10.1234/example"
    assert candidate.landing_page_url == "https://arxiv.org/abs/2401.01234v2"
    assert "summary" not in candidate.model_dump()


async def test_clinical_trials_uses_field_projection_and_preserves_status():
    def handler(request):
        assert request.url.host == "clinicaltrials.gov"
        assert request.url.params["fields"] == STUDY_FIELDS
        assert request.url.params["countTotal"] == "true"
        assert request.url.params["pageSize"] == "1"
        return httpx.Response(
            200,
            json={
                "totalCount": 7,
                "studies": [
                    {
                        "protocolSection": {
                            "identificationModule": {
                                "nctId": "NCT01234567",
                                "briefTitle": " Trial A ",
                            },
                            "statusModule": {
                                "overallStatus": "RECRUITING",
                                "startDateStruct": {"date": "2024-01"},
                            },
                            "designModule": {"studyType": "INTERVENTIONAL"},
                            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Institute"}},
                            "descriptionModule": {"briefSummary": "must not leave the adapter"},
                        }
                    },
                    {
                        "protocolSection": {
                            "identificationModule": {
                                "nctId": "NCT99999999",
                                "briefTitle": "Not returned",
                            }
                        }
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await ClinicalTrialsAdapter(client=client).search(
            ClinicalTrialsAdapter.search_request(query="asthma", per_page=1)
        )
    assert result.total_count == 7
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.nct_id == "NCT01234567"
    assert candidate.overall_status == "RECRUITING"
    assert candidate.start_date == "2024-01"
    assert candidate.landing_page_url == "https://clinicaltrials.gov/study/NCT01234567"
    assert "briefSummary" not in candidate.model_dump()


@pytest.mark.parametrize(
    ("adapter", "body", "error"),
    [
        (PubMedAdapter, {"esearchresult": {"idlist": "123"}}, PubMedRequestError),
        (EuropePMCAdapter, {"resultList": {"result": {}}}, EuropePMCRequestError),
        (ClinicalTrialsAdapter, {"studies": {}}, ClinicalTrialsRequestError),
    ],
)
async def test_malformed_json_shape_is_failure_not_empty_results(adapter, body, error):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        with pytest.raises(error):
            await adapter(client=client).search(adapter.search_request(query="asthma"))


@pytest.mark.parametrize(
    ("adapter", "error"),
    [
        (PubMedAdapter, PubMedRequestError),
        (EuropePMCAdapter, EuropePMCRequestError),
        (ArxivAdapter, ArxivRequestError),
        (ClinicalTrialsAdapter, ClinicalTrialsRequestError),
    ],
)
async def test_http_failure_is_not_empty_discovery(adapter, error):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as client:
        with pytest.raises(error):
            await adapter(client=client).search(adapter.search_request(query="asthma"))


@pytest.mark.parametrize(
    ("adapter", "error"),
    [
        (PubMedAdapter, PubMedRequestError),
        (EuropePMCAdapter, EuropePMCRequestError),
        (ArxivAdapter, ArxivRequestError),
        (ClinicalTrialsAdapter, ClinicalTrialsRequestError),
    ],
)
async def test_oversized_provider_response_is_rejected(adapter, error):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1_000_001))
    ) as client:
        with pytest.raises(error, match="metadata limit"):
            await adapter(client=client).search(adapter.search_request(query="asthma"))


async def test_arxiv_rejects_xml_entities():
    malicious = (
        b'<!DOCTYPE feed [<!ENTITY x "content">]><feed xmlns="http://www.w3.org/2005/Atom"/>'
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=malicious))
    ) as client:
        with pytest.raises(ArxivRequestError, match="unsupported XML"):
            await ArxivAdapter(client=client).search(ArxivAdapter.search_request(query="asthma"))


@pytest.mark.parametrize(
    "adapter", [PubMedAdapter, EuropePMCAdapter, ArxivAdapter, ClinicalTrialsAdapter]
)
async def test_tampered_requests_are_rejected_before_dispatch(adapter):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    request = adapter.search_request(query="asthma")
    request.payload["unexpected"] = "x"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            await adapter(client=client).search(request)
    assert calls == 0
