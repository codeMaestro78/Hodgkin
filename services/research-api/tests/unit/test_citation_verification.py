from research_api.graph.builder import (
    CitationDraft,
    ClaimDraft,
    SemanticReview,
    SourceMaterial,
    SynthesisOutput,
    _exact_span,
    _verified_claims,
)


def test_exact_span_returns_artifact_offsets_for_a_verbatim_quote() -> None:
    assert _exact_span("One reliable source sentence.", "reliable source") == (4, 19)


def test_exact_span_rejects_normalized_or_missing_quotes() -> None:
    content = "Evidence contains two spaces."
    assert _exact_span(content, "Evidence contains  two spaces.") is None
    assert _exact_span(content, "invented evidence") is None


def test_verified_claims_rejects_paraphrased_quotes_but_keeps_exact_claims() -> None:
    source = SourceMaterial(
        source=object(),  # type: ignore[arg-type]
        content="The service supports live extraction.",
    )
    answer = SynthesisOutput(
        answer_markdown="Answer",
        claims=[
            ClaimDraft(
                claim="The service supports live extraction.",
                citations=[
                    CitationDraft(
                        source_number=1, quote="The service supports live extraction."
                    )
                ],
                caveats=[],
            ),
            ClaimDraft(
                claim="The service extracts live data.",
                citations=[
                    CitationDraft(source_number=1, quote="The service extracts live data.")
                ],
                caveats=[],
            ),
        ],
    )
    reviews = [
        SemanticReview(claim_index=0, citation_index=0, verdict="supports", confidence=0.99),
        SemanticReview(claim_index=1, citation_index=0, verdict="supports", confidence=0.99),
    ]

    verified = _verified_claims(answer, [source], reviews)

    assert [claim.claim for claim, _ in verified] == [
        "The service supports live extraction."
    ]
