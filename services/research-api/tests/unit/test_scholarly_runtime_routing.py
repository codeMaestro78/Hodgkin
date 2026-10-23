import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.artifacts.store import InMemoryArtifactStore
from research_api.config import Settings
from research_api.graph.collection import scholarly_route_from_version
from research_api.ingestion import TavilyEvidenceIngestor
from research_api.jobs import graph_version_for
from research_api.providers.candidate_screening import screen_scholarly_candidates
from research_api.providers.pubmed import PubMedAdapter
from research_api.providers.semantic_scholar import SemanticScholarRequestError
from research_api.providers.tavily import SearchResponse


@pytest.mark.parametrize("provider,id_field,identifier", [
    ("semantic_scholar", "paper_id", "a" * 40),
    ("pubmed", "pmid", "1234"),
    ("europe_pmc", "record_id", "PMC1234"),
    ("arxiv", "arxiv_id", "2401.01234"),
    ("clinical_trials", "nct_id", "NCT12345678"),
])
def test_scholarly_receipt_contains_index_record_but_source_has_no_index_text(
    provider, id_field, identifier
):
    candidate = SimpleNamespace(**{
        id_field: identifier,
        "title": "Heart failure study",
        "doi": None,
        "landing_page_url": "https://example.org/study",
        "abstract": "Index abstract must not become evidence",
        "publication_date": date(2024, 1, 1),
    })
    response = screen_scholarly_candidates(
        (candidate,), provider=provider, query="heart failure", max_results=1,
        index_total_count=9999,
    )
    payload = response.model_dump(mode="json")
    assert payload["discovery_provider"] == provider
    assert payload["discovery_candidates"][0][id_field] == identifier
    assert payload["discovery_candidates"][0]["index_record_only"] is True
    assert "abstract" not in payload["discovery_candidates"][0]
    assert payload["results"][0]["content"] == ""
    assert payload["results"][0]["provider"] == provider
    assert payload["usage"]["index_total_count"] == 9999
    assert payload["usage"]["candidate_records_returned"] == 1


@pytest.mark.parametrize("provider", [
    "semantic_scholar", "pubmed", "europe_pmc", "arxiv", "clinical_trials",
])
def test_scholarly_route_requires_opt_in_and_pins_provider_budget_and_fallback(
    monkeypatch, provider
):
    settings = Settings(_env_file=None, TAVILY_API_KEY="test", OPENALEX_DISCOVERY_ENABLED=True)
    default_version = graph_version_for(Settings(_env_file=None), explicit_mode=False)
    assert scholarly_route_from_version(default_version) == (None, 0, False)
    monkeypatch.setenv("SCHOLARLY_DISCOVERY_PROVIDER", provider)
    monkeypatch.setenv("SCHOLARLY_DISCOVERY_FALLBACK", "openalex")
    monkeypatch.setenv("SCHOLARLY_DISCOVERY_SEARCH_BUDGET_MILLI_USD", "2")
    version = graph_version_for(settings, explicit_mode=False)
    assert len(version) <= 64
    assert scholarly_route_from_version(version) == (provider, 2, True)
    with pytest.raises(ValueError, match="standard run"):
        graph_version_for(settings, explicit_mode=True)
    monkeypatch.setenv("SCHOLARLY_DISCOVERY_SEARCH_BUDGET_MILLI_USD", "1")
    with pytest.raises(ValueError, match="budget"):
        graph_version_for(settings, explicit_mode=False)


@pytest.mark.asyncio
async def test_released_semantic_scholar_search_uses_pinned_fallback(monkeypatch):
    adapter = SimpleNamespace(search_request=lambda **kwargs: SimpleNamespace(
        operation="search", request_schema_version="semantic-scholar-graph-v1",
    ))
    openalex = SimpleNamespace(search_request=lambda **kwargs: SimpleNamespace(
        operation="search", request_schema_version="openalex-works-v1",
    ))
    ingestor = TavilyEvidenceIngestor(
        adapter=SimpleNamespace(), artifact_store=InMemoryArtifactStore(),
        scholarly_adapter=adapter, scholarly_provider="semantic_scholar",
        scholarly_search_budget_milli_usd=2, scholarly_fallback_openalex=True,
        academic_adapter=openalex,
    )
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    monkeypatch.setattr(ingestor, "_released_scholarly_attempt", AsyncMock(return_value=False))
    monkeypatch.setattr(ingestor, "_replay_response", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ingestor, "_search_fresh",
        AsyncMock(side_effect=SemanticScholarRequestError("rate limited", outcome="released")),
    )
    fallback = SearchResponse(results=[])
    monkeypatch.setattr(ingestor, "_fallback_openalex", AsyncMock(return_value=fallback))
    assert await ingestor.ingest(
        tenant_id=uuid.uuid4(), run_id=uuid.uuid4(), sub_question_id=None,
        query="heart failure", source_classes=["academic"],
    ) == []
    ingestor._fallback_openalex.assert_awaited_once()


@pytest.mark.asyncio
async def test_pubmed_search_finalizes_bounded_provider_receipt(monkeypatch):
    candidate = SimpleNamespace(
        pmid="1234", title="Heart failure study", doi=None,
        landing_page_url="https://pubmed.ncbi.nlm.nih.gov/1234/",
        publication_date="2024-01-01",
    )
    adapter = SimpleNamespace(
        search=AsyncMock(return_value=SimpleNamespace(
            candidates=(candidate,), total_count=500, attempt_count=2,
        )),
    )
    ingestor = TavilyEvidenceIngestor(
        adapter=SimpleNamespace(), artifact_store=InMemoryArtifactStore(),
        scholarly_adapter=adapter, scholarly_provider="pubmed",
        scholarly_search_budget_milli_usd=1,
    )
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    reserve = AsyncMock(return_value=uuid.uuid4())
    finalize = AsyncMock()
    monkeypatch.setattr(ingestor, "_reserve", reserve)
    monkeypatch.setattr(ingestor, "_finalize", finalize)
    monkeypatch.setattr(ingestor, "_replay_response", AsyncMock(
        return_value=screen_scholarly_candidates(
            (candidate,), provider="pubmed", query="heart failure", max_results=1,
        )
    ))
    request = PubMedAdapter.search_request(query="heart failure", per_page=1)
    response = await ingestor._search_fresh(
        tenant_id=uuid.uuid4(), run_id=uuid.uuid4(), request=request,
    )
    assert len(response.results) == 1
    assert str(reserve.await_args.kwargs["estimated_cost"]) == "0.001"
    saved = finalize.await_args.kwargs
    assert saved["state"] == "consumed"
    assert saved["response_schema_version"] == request.request_schema_version
    assert saved["provider_usage"]["candidate_records_returned"] == 1
    assert saved["provider_usage"]["index_total_count"] == 500
    assert saved["response_body"]["results"][0]["content"] == ""
    assert saved["response_body"]["discovery_candidates"][0]["index_record_only"] is True


@pytest.mark.asyncio
async def test_uncertain_semantic_scholar_failure_does_not_fallback(monkeypatch):
    adapter = SimpleNamespace(search_request=lambda **kwargs: SimpleNamespace(
        operation="search", request_schema_version="semantic-scholar-graph-v1",
    ))
    ingestor = TavilyEvidenceIngestor(
        adapter=SimpleNamespace(), artifact_store=InMemoryArtifactStore(),
        scholarly_adapter=adapter, scholarly_provider="semantic_scholar",
        scholarly_search_budget_milli_usd=2, scholarly_fallback_openalex=True,
    )
    monkeypatch.setattr(ingestor, "_check_cancelled", AsyncMock())
    monkeypatch.setattr(ingestor, "_released_scholarly_attempt", AsyncMock(return_value=False))
    monkeypatch.setattr(ingestor, "_replay_response", AsyncMock(return_value=None))
    monkeypatch.setattr(
        ingestor, "_search_fresh",
        AsyncMock(side_effect=SemanticScholarRequestError("timeout", outcome="uncertain")),
    )
    fallback = AsyncMock()
    monkeypatch.setattr(ingestor, "_fallback_openalex", fallback)
    with pytest.raises(SemanticScholarRequestError):
        await ingestor.ingest(
            tenant_id=uuid.uuid4(), run_id=uuid.uuid4(), sub_question_id=None,
            query="heart failure", source_classes=["academic"],
        )
    fallback.assert_not_awaited()
