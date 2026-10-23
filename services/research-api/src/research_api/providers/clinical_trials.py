"""ClinicalTrials.gov v2 studies search with a metadata-only field projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from research_api.providers.tavily import ProviderRequest, request_fingerprint

CLINICAL_TRIALS_API = "https://clinicaltrials.gov/api/v2/studies"
CLINICAL_TRIALS_SCHEMA_VERSION = "clinicaltrials-studies-v2-metadata-v1"
STUDY_FIELDS = (
    "NCTId,BriefTitle,OverallStatus,StudyType,StartDate,PrimaryCompletionDate,LeadSponsorName"
)
_NCT = re.compile(r"NCT[0-9]{8}\Z")


class ClinicalTrialsRequestError(RuntimeError):
    """The official API failed or returned a malformed discovery response."""


class ClinicalTrialCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nct_id: str = Field(pattern=r"^NCT[0-9]{8}$")
    title: str = Field(min_length=1, max_length=1000)
    overall_status: str | None = Field(default=None, max_length=100)
    study_type: str | None = Field(default=None, max_length=100)
    start_date: str | None = Field(default=None, max_length=20)
    primary_completion_date: str | None = Field(default=None, max_length=20)
    lead_sponsor: str | None = Field(default=None, max_length=500)
    landing_page_url: str = Field(pattern=r"^https://clinicaltrials\.gov/study/NCT[0-9]{8}$")


@dataclass(frozen=True, slots=True)
class ClinicalTrialsSearchResult:
    candidates: tuple[ClinicalTrialCandidate, ...]
    total_count: int | None
    attempt_count: int = 1
    response_schema_version: str = CLINICAL_TRIALS_SCHEMA_VERSION


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate(raw: object) -> ClinicalTrialCandidate | None:
    protocol = _mapping(_mapping(raw).get("protocolSection"))
    identification = _mapping(protocol.get("identificationModule"))
    nct_id = identification.get("nctId")
    title = _text(identification.get("briefTitle"), 1000)
    if not isinstance(nct_id, str) or _NCT.fullmatch(nct_id) is None or title is None:
        return None
    status = _mapping(protocol.get("statusModule"))
    design = _mapping(protocol.get("designModule"))
    sponsor = _mapping(_mapping(protocol.get("sponsorCollaboratorsModule")).get("leadSponsor"))
    try:
        return ClinicalTrialCandidate(
            nct_id=nct_id,
            title=title,
            overall_status=_text(status.get("overallStatus"), 100),
            study_type=_text(design.get("studyType"), 100),
            start_date=_text(_mapping(status.get("startDateStruct")).get("date"), 20),
            primary_completion_date=_text(
                _mapping(status.get("primaryCompletionDateStruct")).get("date"), 20
            ),
            lead_sponsor=_text(sponsor.get("name"), 500),
            landing_page_url=f"https://clinicaltrials.gov/study/{nct_id}",
        )
    except ValidationError:
        return None


class ClinicalTrialsAdapter:
    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 20) -> None:
        if not 0 < timeout <= 60:
            raise ValueError("ClinicalTrials.gov timeout must be between zero and 60 seconds")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()
        self._timeout = httpx.Timeout(timeout, connect=min(10, timeout))

    @staticmethod
    def search_request(*, query: str, per_page: int = 8) -> ProviderRequest:
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000:
            raise ValueError("ClinicalTrials.gov query must contain 1 to 1000 characters")
        if type(per_page) is not int or not 1 <= per_page <= 10:
            raise ValueError("ClinicalTrials.gov per_page must be between one and ten")
        payload = {
            "query.term": query.strip(),
            "pageSize": per_page,
            "format": "json",
            "countTotal": "true",
            "fields": STUDY_FIELDS,
        }
        return ProviderRequest(
            "search",
            payload,
            request_fingerprint("clinicaltrials:studies:v2", payload),
            request_schema_version=CLINICAL_TRIALS_SCHEMA_VERSION,
        )

    async def search(self, request: ProviderRequest) -> ClinicalTrialsSearchResult:
        payload = request.payload
        try:
            expected = self.search_request(
                query=payload["query.term"], per_page=payload["pageSize"]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid ClinicalTrials.gov search request") from exc
        if request != expected:
            raise ValueError("Invalid ClinicalTrials.gov search request")
        try:
            response = await self._client.get(
                CLINICAL_TRIALS_API, params=payload, timeout=self._timeout, follow_redirects=False
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise ClinicalTrialsRequestError(
                    "ClinicalTrials.gov response exceeds metadata limit"
                )
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinicalTrialsRequestError(
                "ClinicalTrials.gov request failed or returned invalid JSON"
            ) from exc
        if not isinstance(body, dict) or not isinstance(body.get("studies"), list):
            raise ClinicalTrialsRequestError("ClinicalTrials.gov response is invalid")
        count = body.get("totalCount")
        total = count if type(count) is int and count >= 0 else None
        candidates = tuple(
            candidate
            for raw in body["studies"][: payload["pageSize"]]
            if (candidate := _candidate(raw)) is not None
        )
        return ClinicalTrialsSearchResult(candidates, total)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
