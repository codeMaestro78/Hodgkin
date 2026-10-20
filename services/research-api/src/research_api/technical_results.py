"""Fail-closed, replayable projection of typed results from the verified claim ledger.

This checks literal fidelity, not general symbolic equivalence or theorem truth.
The normal exact-passage and independent semantic claim review must run first.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TechnicalResultProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "definition",
        "theorem",
        "bound",
        "algorithm",
        "comparison",
        "open_problem",
        "method",
        "measurement",
    ]
    title: str = Field(min_length=1, max_length=160)
    claim_index: int = Field(ge=0, le=39)
    citation_index: int = Field(ge=0, le=7)
    assumptions: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(max_length=8)
    notation: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(max_length=8)
    source_expression: Annotated[str, Field(min_length=1, max_length=500)] | None
    representation: Literal["plain_text", "latex"] | None
    source_location: Annotated[str, Field(min_length=1, max_length=120)] | None

    @model_validator(mode="after")
    def expression_representation(self) -> "TechnicalResultProposal":
        if (self.source_expression is None) != (self.representation is None):
            raise ValueError("Expression and representation must be supplied together")
        return self


def review_technical_results(
    proposals: list[TechnicalResultProposal], audited: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Persist all proposals/checks, but expose a card only for an exact reviewed citation.

    `audited` is a narrow projection of the persisted claim audit. The caller must
    provide only citation IDs that were persisted for that same reviewed claim.
    """
    receipts: list[dict[str, Any]] = []
    for proposal in proposals:
        reasons: list[str] = []
        checks: dict[str, str] = {}
        claim = audited[proposal.claim_index] if proposal.claim_index < len(audited) else None
        citation = (
            claim["citations"][proposal.citation_index]
            if claim is not None and proposal.citation_index < len(claim["citations"])
            else None
        )
        if claim is None or claim["status"] != "supported":
            reasons.append("claim_not_supported")
        if citation is None:
            reasons.append("citation_not_verified")
        quote = citation["quote"] if citation else ""
        claim_text = claim["claim"] if claim else ""
        title_valid = proposal.title in quote or proposal.title in claim_text
        checks["title"] = "exact" if title_valid else "not_assessed"
        if not title_valid:
            reasons.append("title_not_in_claim_or_quote")
        for index, assumption in enumerate(proposal.assumptions):
            valid = assumption in quote and assumption.casefold() in claim_text.casefold()
            checks[f"assumption_{index}"] = "exact" if valid else "not_assessed"
            if not valid:
                reasons.append(f"assumption_{index}_missing_from_claim_or_quote")
        for index, term in enumerate(proposal.notation):
            valid = term in quote
            checks[f"notation_{index}"] = "exact" if valid else "not_assessed"
            if not valid:
                reasons.append(f"notation_{index}_not_in_quote")
        if proposal.source_expression is not None:
            valid = proposal.source_expression in quote
            checks["expression"] = "exact" if valid else "not_assessed"
            if not valid:
                reasons.append("expression_not_in_quote")
        if proposal.source_location is not None:
            valid = proposal.source_location in quote
            checks["location"] = "exact" if valid else "not_assessed"
            if not valid:
                reasons.append("location_not_in_quote")
        result: dict[str, Any] | None = None
        if not reasons and claim and citation:
            result = {
                "kind": proposal.kind,
                "title": proposal.title,
                "claimId": claim["claim_id"],
                "citationIds": [citation["citation_id"]],
                "sourceIds": [citation["source_id"]],
                "sourceArtifactHash": citation["source_hash"],
                "assumptions": proposal.assumptions,
                "notation": proposal.notation,
                "sourceLocation": proposal.source_location,
                "expression": (
                    {
                        "sourceText": proposal.source_expression,
                        "representation": proposal.representation,
                        "transformation": "none",
                    }
                    if proposal.source_expression is not None
                    else None
                ),
                "verification": "exact_passage_and_scoped_semantic_claim_review_v2",
            }
        receipts.append(
            {
                "proposal": proposal.model_dump(mode="json"),
                "fieldChecks": checks,
                "status": "supported" if result else "not_assessed",
                "reasons": reasons,
                "result": result,
            }
        )
    return receipts
