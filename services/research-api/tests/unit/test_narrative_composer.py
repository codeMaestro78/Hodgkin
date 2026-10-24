import json

import pytest

from research_api.narrative_composer import (
    NARRATIVE_BASIS,
    NARRATIVE_LIMITS,
    NarrativeFinding,
    NarrativeInputs,
    narrative_request,
    pack_proposal,
    parse_narrative,
    project_narrative,
)

QUOTE_A = "Workflow state is written to durable storage."
QUOTE_B = "Checkpoints are replayed after a worker crash."


def inputs(**overrides):
    values = {
        "question": "How is workflow state preserved?",
        "mode": "balanced",
        "findings": (
            NarrativeFinding("c0", "The service preserves workflow state.", ("d1",), (1,)),
            NarrativeFinding("c2", "Checkpoints survive worker crashes.", (), (2,)),
        ),
        "dimensions": (("d1", "dim-uuid-1", "Persistence"), ("d2", "dim-uuid-2", "Recovery")),
        "conflicts": (),
        "passages": (
            (1, "s1_p1", QUOTE_A),
            (2, "s2_p1", QUOTE_B),
            (2, "s2_p2", "short"),
            (21, "s21_p1", "Out of range source number passage."),
        ),
        "sources": (("Source A", "https://a.test"), ("Source B", "https://b.test")),
    }
    values.update(overrides)
    return NarrativeInputs(**values)


def sentence(finding, claim="", citations=()):
    return {
        "finding": finding,
        "claim": claim,
        "citations": [{"source_number": n, "passage_id": p} for n, p in citations],
    }


def block(role, dimension="none", *sentences):
    return {"role": role, "dimension": dimension, "sentences": list(sentences)}


def parse(blocks, data=None):
    data = data or inputs()
    _, registry = narrative_request(data)
    return parse_narrative(json.dumps({"blocks": blocks}), inputs=data, registry=registry)


def test_request_is_deterministic_strict_and_mode_named():
    first, registry = narrative_request(inputs())
    second, _ = narrative_request(inputs())
    assert first == second
    assert first["text"]["format"]["name"] == "balanced_evidence_narrative_v1"
    assert first["text"]["format"]["strict"] is True
    assert first["max_output_tokens"] == NARRATIVE_LIMITS["balanced"].output_tokens
    assert first["store"] is False
    # Out-of-range source numbers and unusable quote lengths are never offered.
    assert registry == {(1, "s1_p1"): QUOTE_A, (2, "s2_p1"): QUOTE_B}
    schema = first["text"]["format"]["schema"]
    item = schema["properties"]["blocks"]["items"]
    assert item["properties"]["role"]["enum"] == list(NARRATIVE_LIMITS["balanced"].roles)
    assert item["properties"]["dimension"]["enum"] == ["d1", "d2", "none"]
    finding = item["properties"]["sentences"]["items"]["properties"]["finding"]
    assert finding["enum"] == ["c0", "c2", "new"]
    payload = json.loads(first["input"])
    assert [row["key"] for row in payload["verified_findings"]] == ["c0", "c2"]
    assert "untrusted data" in first["instructions"]


def test_deeper_modes_allow_more_evidence_supported_explanation():
    focused = NARRATIVE_LIMITS["focused"]
    balanced = NARRATIVE_LIMITS["balanced"]
    deep = NARRATIVE_LIMITS["deep"]
    assert focused.output_tokens < balanced.output_tokens < deep.output_tokens
    assert focused.max_sentences < balanced.max_sentences < deep.max_sentences
    request, _ = narrative_request(inputs(mode="deep"))
    assert request["max_output_tokens"] == deep.output_tokens
    assert "Cover each evidence-supported research dimension" in request["instructions"]
    assert "Thin evidence should remain concise" in request["instructions"]


def test_catalogue_is_bounded_and_prefers_cited_sources():
    limits = NARRATIVE_LIMITS["focused"]
    uncited = tuple((1, f"s1_p{i}", "x" * 600) for i in range(1, 40))
    data = inputs(
        mode="focused",
        findings=(NarrativeFinding("c0", "Claim.", (), (2,)),),
        passages=(*uncited, (2, "s2_p1", "y" * 600)),
    )
    request, registry = narrative_request(data)
    assert sum(len(quote) for quote in registry.values()) <= limits.catalogue_chars
    # The cited source keeps its passage even though uncited text alone exceeds the cap.
    assert (2, "s2_p1") in registry
    assert sum(number == 1 for number, _ in registry) == limits.catalogue_chars // 600 - 1
    numbers = [row["source_number"] for row in json.loads(request["input"])["literal_passages"]]
    assert numbers == [1, 2]


def test_new_claims_are_not_offered_without_registered_passages():
    request, registry = narrative_request(inputs(passages=()))
    assert registry == {}
    item = request["text"]["format"]["schema"]["properties"]["blocks"]["items"]
    finding = item["properties"]["sentences"]["items"]["properties"]["finding"]
    assert "new" not in finding["enum"]


def test_valid_proposal_orders_ledger_and_new_claims():
    proposal = parse(
        [
            block("answer", "none", sentence("c0")),
            block(
                "dimension",
                "d2",
                sentence("c2"),
                sentence("new", "Durable state is written before replay.", [(1, "s1_p1")]),
            ),
        ]
    )
    assert proposal.proposed_sentences == 3 and proposal.rejected_before_review == 0
    assert proposal.claims[0].section == "mechanisms"
    assert proposal.claims[0].citations == ((1, QUOTE_A),)
    assert pack_proposal(proposal) == [
        {
            "role": "answer",
            "dimension_id": None,
            "sentences": [{"origin": "ledger", "ref": "c0"}],
        },
        {
            "role": "dimension",
            "dimension_id": "dim-uuid-2",
            "sentences": [
                {"origin": "ledger", "ref": "c2"},
                {"origin": "narrative", "ref": 0},
            ],
        },
    ]


@pytest.mark.parametrize(
    "blocks",
    [
        [block("synthesis", "none", sentence("c0"))],  # role not allowed for balanced
        [block("dimension", "none", sentence("c0"))],  # dimension role without key
        [block("answer", "d1", sentence("c0"))],  # non-dimension role with key
        [block("tradeoffs", "none"), block("answer", "none", sentence("c0"))],  # late answer
        [block("dimension", "d9", sentence("c0"))],  # unknown dimension
    ],
)
def test_invalid_blocks_are_dropped(blocks):
    proposal = parse(blocks)
    assert proposal.blocks == () and proposal.claims == ()
    assert proposal.rejected_before_review == proposal.proposed_sentences == 1


def test_duplicate_role_dimension_block_is_dropped():
    proposal = parse(
        [
            block("dimension", "d1", sentence("c0")),
            block("dimension", "d1", sentence("c2")),
        ]
    )
    assert len(proposal.blocks) == 1 and proposal.rejected_before_review == 1


@pytest.mark.parametrize(
    "bad",
    [
        sentence("c9"),  # unknown finding
        sentence("c0"),  # reused finding
        sentence("c2", "Smuggled text.", ()),  # ledger reference with claim text
        sentence("c2", "", [(1, "s1_p1")]),  # ledger reference with citations
        sentence("new", "", [(1, "s1_p1")]),  # empty new claim
        sentence("new", "Uncited new claim."),  # no citations
        sentence("new", "Unregistered passage.", [(1, "s1_p9")]),
        sentence("new", "Duplicate citation.", [(1, "s1_p1"), (1, "s1_p1")]),
        sentence("new", "  the SERVICE preserves   workflow state. ", [(1, "s1_p1")]),
    ],
)
def test_invalid_sentences_are_rejected_before_review(bad):
    proposal = parse([block("answer", "none", sentence("c0"), bad)])
    assert proposal.proposed_sentences == 2 and proposal.rejected_before_review == 1
    assert proposal.claims == ()
    assert proposal.blocks[0].sentences == (("ledger", "c0"),)


def test_new_claim_capacity_is_bounded_by_mode():
    limit = NARRATIVE_LIMITS["focused"].max_new_claims
    data = inputs(mode="focused")
    sentences = [
        sentence("new", f"Distinct explanatory claim number {index}.", [(1, "s1_p1")])
        for index in range(limit + 1)
    ]
    proposal = parse(
        [block("answer", "none", *sentences[:3]), block("tradeoffs", "none", *sentences[3:])], data
    )
    assert len(proposal.claims) == limit
    assert proposal.rejected_before_review == 1


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps({"blocks": [{"role": "answer"}]}),
        json.dumps({"blocks": [], "extra": True}),
        json.dumps({"blocks": [block("answer", "none", *[sentence("c0")] * 9)]}),
        json.dumps({"blocks": [block("answer", "none")] * 4}),
    ],
)
def test_malformed_or_oversized_proposals_raise(payload):
    data = inputs(mode="focused")
    _, registry = narrative_request(data)
    with pytest.raises(ValueError):
        parse_narrative(payload, inputs=data, registry=registry)


def test_projection_publishes_only_supported_sentences():
    blocks = [
        {"role": "answer", "dimension_id": None, "sentences": [{"origin": "ledger", "ref": "c0"}]},
        {
            "role": "tradeoffs",
            "dimension_id": None,
            "sentences": [{"origin": "narrative", "ref": 0}, {"origin": "narrative", "ref": 1}],
        },
    ]
    projected = project_narrative(
        mode="focused",
        status="composed",
        reason=None,
        blocks=blocks,
        ledger_claim_ids={"c0": "id-0"},
        narrative_claim_ids={1: "id-n1"},
        citation_ids={"id-0": ["cit-0"], "id-n1": ["cit-n1"]},
        proposed_sentences=4,
    )
    assert projected == {
        "basis": NARRATIVE_BASIS,
        "status": "composed",
        "reason": None,
        "blocks": [
            {
                "id": "narrative-1",
                "role": "answer",
                "dimensionId": None,
                "sentences": [{"claimId": "id-0", "citationIds": ["cit-0"], "origin": "ledger"}],
            },
            {
                "id": "narrative-2",
                "role": "tradeoffs",
                "dimensionId": None,
                "sentences": [
                    {"claimId": "id-n1", "citationIds": ["cit-n1"], "origin": "narrative"}
                ],
            },
        ],
        "narrativeClaimIds": ["id-n1"],
        "proposedSentenceCount": 4,
        "publishedSentenceCount": 2,
        "rejectedSentenceCount": 2,
    }


def test_projection_without_published_sentences_is_not_composed():
    projected = project_narrative(
        mode="deep",
        status="composed",
        reason=None,
        blocks=[
            {
                "role": "answer",
                "dimension_id": None,
                "sentences": [{"origin": "narrative", "ref": 0}],
            }
        ],
        ledger_claim_ids={},
        narrative_claim_ids={},
        citation_ids={},
        proposed_sentences=1,
    )
    assert projected["status"] == "not_composed"
    assert projected["reason"] == "no_supported_sentences"
    assert projected["blocks"] == [] and projected["rejectedSentenceCount"] == 1


def test_projection_preserves_not_composed_reason_and_rejects_unknown_mode():
    projected = project_narrative(
        mode="balanced",
        status="not_composed",
        reason="insufficient_time",
        blocks=[],
        ledger_claim_ids={"c0": "id-0"},
        narrative_claim_ids={},
        citation_ids={},
        proposed_sentences=0,
    )
    assert projected["reason"] == "insufficient_time" and projected["blocks"] == []
    with pytest.raises(ValueError):
        project_narrative(
            mode="quick",
            status="not_composed",
            reason="insufficient_time",
            blocks=[],
            ledger_claim_ids={},
            narrative_claim_ids={},
            citation_ids={},
            proposed_sentences=0,
        )
