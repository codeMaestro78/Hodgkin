"""Prepare blind candidate packets and score reviewed shared retrieval pools.

This offline module makes no provider, model, or database calls. The private
mapping is the only artifact that joins blind IDs back to methods and work
identities; never send it to reviewers or commit it to the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

_RELEVANCE = {"direct", "partial", "not_relevant", "unclear"}
_REQUIREMENT_MATCH = {"yes", "partial", "no", "unclear"}
_CONFIDENCE = {"low", "medium", "high"}
_MAX_CASES = 100
_MAX_CANDIDATES_PER_CASE = 250
_MAX_TEXT_CHARS = 6000


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object, label: str, *, maximum: int) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{label} must be non-empty text")
    assert isinstance(value, str)
    _require(len(value) <= maximum, f"{label} exceeds {maximum} characters")
    return value.strip()


def _pool_cases(pool: dict[str, Any]) -> list[dict[str, Any]]:
    _require(isinstance(pool, dict), "candidate pool must be an object")
    _require(pool.get("schemaVersion") == "retrieval-candidate-pool-v1", "unsupported pool schema")
    cases = pool.get("cases")
    _require(isinstance(cases, list) and 1 <= len(cases) <= _MAX_CASES, "invalid pool cases")
    seen_cases: set[str] = set()
    for case_value in cast(list[Any], cases):
        case = cast(dict[str, Any], case_value)
        _require(isinstance(case, dict), "pool case must be an object")
        case_id = _text(case.get("caseId"), "caseId", maximum=80)
        _require(case_id not in seen_cases, "duplicate caseId")
        seen_cases.add(case_id)
        candidates = case.get("candidates")
        _require(
            isinstance(candidates, list) and 1 <= len(candidates) <= _MAX_CANDIDATES_PER_CASE,
            "invalid candidate list",
        )
        candidate_ids: set[str] = set()
        for candidate_value in cast(list[Any], candidates):
            candidate = cast(dict[str, Any], candidate_value)
            _require(isinstance(candidate, dict), "candidate must be an object")
            candidate_id = _text(candidate.get("candidateId"), "candidateId", maximum=160)
            _require(candidate_id not in candidate_ids, "duplicate candidateId in case")
            candidate_ids.add(candidate_id)
            _text(candidate.get("title"), "candidate title", maximum=1000)
            abstract = candidate.get("abstract", "")
            _require(
                isinstance(abstract, str) and len(abstract) <= _MAX_TEXT_CHARS, "invalid abstract"
            )
        rankings = case.get("rankings")
        _require(isinstance(rankings, dict) and 1 <= len(rankings) <= 8, "invalid method rankings")
        for method, ranking in cast(dict[str, Any], rankings).items():
            _text(method, "method name", maximum=100)
            _require(isinstance(ranking, list), "ranking must be a list")
            _require(all(isinstance(item, str) for item in ranking), "ranking IDs must be strings")
            _require(
                len(ranking) <= len(candidate_ids)
                and len(ranking) == len(set(ranking))
                and all(candidate_id in candidate_ids for candidate_id in ranking),
                "ranking must contain unique candidate IDs from the shared pool",
            )
    return cast(list[dict[str, Any]], cases)


def _pool_hash(pool: dict[str, Any]) -> str:
    encoded = json.dumps(pool, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _packet_hash(packet: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in packet.items() if key != "packetSha256"}
    encoded = json.dumps(
        unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def prepare_blind_review(
    pool: dict[str, Any], cases_by_id: dict[str, dict[str, Any]], *, seed: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a reviewer packet and separate private method/identity mapping."""
    rng = random.Random(seed)  # noqa: S311 - deterministic reviewer blinding, not a secret.
    reviewer_cases, private_cases = [], []
    for pool_case in _pool_cases(pool):
        case_id = pool_case["caseId"]
        case = cases_by_id.get(case_id)
        _require(isinstance(case, dict), f"missing question and requirements for case {case_id}")
        case = cast(dict[str, Any], case)
        domain = _text(case.get("domain"), "case domain", maximum=100)
        requirements = case.get("requirements")
        _require(
            isinstance(requirements, list) and bool(requirements),
            f"case {case_id} has no requirements",
        )
        requirements = cast(list[Any], requirements)
        requirement_rows = [
            {
                "id": _text(item.get("id"), "requirement id", maximum=80),
                "text": _text(item.get("text"), "requirement text", maximum=1000),
            }
            for item in requirements
            if isinstance(item, dict)
        ]
        _require(len(requirement_rows) == len(requirements), "invalid requirement row")
        requirement_ids = [item["id"] for item in requirement_rows]
        _require(len(set(requirement_ids)) == len(requirement_ids), "duplicate requirement id")

        candidate_rows = []
        candidate_map = []
        id_map: dict[str, str] = {}
        for candidate in pool_case["candidates"]:
            candidate_id = candidate["candidateId"]
            id_digest = hashlib.sha256(f"{case_id}\0{candidate_id}".encode()).hexdigest()[:16]
            blind_id = f"{case_id}-C{id_digest}"
            _require(blind_id not in id_map.values(), "blind ID collision; increase hash length")
            id_map[candidate_id] = blind_id
            public_candidate: dict[str, Any] = {
                "blindId": blind_id,
                "title": _text(candidate["title"], "candidate title", maximum=1000),
                "abstract": candidate.get("abstract", ""),
            }
            year = candidate.get("year")
            if year is not None:
                _require(type(year) is int and 1000 <= year <= 2200, "candidate year is invalid")
                public_candidate["year"] = year
            doc_type = candidate.get("documentType")
            if doc_type is not None:
                public_candidate["documentType"] = _text(doc_type, "documentType", maximum=100)
            candidate_rows.append(public_candidate)
            candidate_map.append(
                {
                    "blindId": blind_id,
                    "candidateId": candidate_id,
                    "workIdentity": candidate.get("workIdentity"),
                    "versionGroup": candidate.get("versionGroup"),
                }
            )
        rng.shuffle(candidate_rows)
        question = _text(case.get("question"), "question", maximum=3000)
        reviewer_cases.append(
            {
                "caseId": case_id,
                "question": question,
                "requirements": requirement_rows,
                "candidates": candidate_rows,
            }
        )
        private_cases.append(
            {
                "caseId": case_id,
                "domain": domain,
                "question": question,
                "requirements": requirement_rows,
                "candidateMap": candidate_map,
                "rankings": {
                    method: [id_map[candidate_id] for candidate_id in ranking]
                    for method, ranking in pool_case["rankings"].items()
                },
            }
        )
    packet: dict[str, Any] = {
        "schemaVersion": "retrieval-blind-review-v1",
        "poolSha256": _pool_hash(pool),
        "cases": reviewer_cases,
    }
    packet["packetSha256"] = _packet_hash(packet)
    return (
        packet,
        {
            "schemaVersion": "retrieval-private-map-v1",
            "seed": seed,
            "poolSha256": _pool_hash(pool),
            "cases": private_cases,
        },
    )


def _case_labels(
    reviewer: dict[str, Any], case_id: str, blind_ids: set[str], requirement_ids: set[str]
) -> dict[str, dict[str, Any]]:
    reviewer_cases = reviewer.get("cases")
    _require(isinstance(reviewer_cases, list), "reviewer cases must be a list")
    reviewer_cases = cast(list[Any], reviewer_cases)
    rows = [row for row in reviewer_cases if isinstance(row, dict) and row.get("caseId") == case_id]
    _require(len(rows) == 1, f"reviewer must provide exactly one case row for {case_id}")
    labels = rows[0].get("labels")
    _require(isinstance(labels, list), f"reviewer labels missing for {case_id}")
    labels = cast(list[Any], labels)
    output: dict[str, dict[str, Any]] = {}
    for label_value in labels:
        label = cast(dict[str, Any], label_value)
        _require(isinstance(label, dict), "review label must be an object")
        blind_id = label.get("blindId")
        _require(
            isinstance(blind_id, str) and blind_id in blind_ids and blind_id not in output,
            "unknown or duplicate blindId",
        )
        blind_id = cast(str, blind_id)
        _require(label.get("relevance") in _RELEVANCE, "invalid relevance label")
        _text(label.get("reason"), "review rationale", maximum=1000)
        matches = label.get("requirementMatches")
        _require(
            isinstance(matches, dict) and set(matches) == requirement_ids,
            "requirement labels must cover every case requirement exactly once",
        )
        matches = cast(dict[str, Any], matches)
        reasons = label.get("requirementReasons")
        _require(
            isinstance(reasons, dict) and set(reasons) == requirement_ids,
            "each requirement needs one rationale",
        )
        reasons = cast(dict[str, Any], reasons)
        for reason in reasons.values():
            _text(reason, "requirement rationale", maximum=1000)
        _require(
            all(value in _REQUIREMENT_MATCH for value in matches.values()),
            "invalid requirement label",
        )
        _require(label.get("confidence") in _CONFIDENCE, "invalid confidence label")
        output[blind_id] = label
    _require(set(output) == blind_ids, "each reviewer must label every candidate")
    return output


def _adjudication_labels(
    adjudication: dict[str, Any] | None,
    case_id: str,
    disputed: set[str],
    blind_ids: set[str],
    requirement_ids: set[str],
    reviewer_ids: set[str],
) -> dict[str, dict[str, Any]]:
    if not disputed:
        return {}
    _require(
        isinstance(adjudication, dict),
        f"review disagreement for {case_id} requires adjudication",
    )
    adjudication = cast(dict[str, Any], adjudication)
    adjudicator_id = _text(adjudication.get("adjudicatorId"), "adjudicatorId", maximum=120)
    _require(adjudicator_id not in reviewer_ids, "adjudicator must be independent")
    adjudication_cases = adjudication.get("cases")
    _require(isinstance(adjudication_cases, list), "adjudication cases must be a list")
    adjudication_cases = cast(list[Any], adjudication_cases)
    rows = [
        row for row in adjudication_cases if isinstance(row, dict) and row.get("caseId") == case_id
    ]
    _require(len(rows) == 1, f"adjudication must include disputed case {case_id}")
    labels = rows[0].get("labels")
    _require(isinstance(labels, list), "adjudication labels missing")
    labels = cast(list[Any], labels)
    output: dict[str, dict[str, Any]] = {}
    for label_value in labels:
        label = cast(dict[str, Any], label_value)
        _require(isinstance(label, dict), "adjudication label must be an object")
        blind_id = label.get("blindId")
        _require(
            isinstance(blind_id, str) and blind_id in disputed and blind_id not in output,
            "adjudication may only label disputed candidates",
        )
        blind_id = cast(str, blind_id)
        _require(label.get("relevance") in _RELEVANCE, "invalid adjudicated relevance")
        _text(label.get("reason"), "adjudication reason", maximum=1000)
        matches = label.get("requirementMatches")
        _require(
            isinstance(matches, dict) and set(matches) == requirement_ids,
            "adjudication must label every requirement exactly once",
        )
        matches = cast(dict[str, Any], matches)
        reasons = label.get("requirementReasons")
        _require(
            isinstance(reasons, dict) and set(reasons) == requirement_ids,
            "each adjudicated requirement needs one rationale",
        )
        reasons = cast(dict[str, Any], reasons)
        for reason in reasons.values():
            _text(reason, "requirement rationale", maximum=1000)
        _require(
            all(value in _REQUIREMENT_MATCH for value in matches.values()),
            "invalid adjudicated requirement label",
        )
        output[blind_id] = label
    _require(set(output) == disputed, "every disputed candidate requires adjudication")
    return output


def _fraction(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: list[float | None]) -> float | None:
    measured = [value for value in values if value is not None]
    return round(sum(measured) / len(measured), 6) if measured else None


def score_retrieval_pool(
    pool: dict[str, Any],
    private_maps: list[dict[str, Any]],
    reviewers: list[dict[str, Any]],
    packets: list[dict[str, Any]],
    *,
    cutoff: int,
    adjudication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one shared pool after validating the two independently shuffled packets."""
    _require(type(cutoff) is int and 1 <= cutoff <= 100, "cutoff must be between 1 and 100")
    _require(isinstance(reviewers, list), "reviewers must be a list")
    _require(len(reviewers) == 2, "exactly two independent reviewers are required")
    reviewer_rows: list[dict[str, Any]] = []
    for row in reviewers:
        _require(isinstance(row, dict), "reviewer record must be an object")
        reviewer_rows.append(row)
    reviewers = reviewer_rows
    _require(
        isinstance(packets, list) and len(packets) == 2, "exactly two review packets are required"
    )
    packet_rows: list[dict[str, Any]] = []
    for packet in packets:
        _require(isinstance(packet, dict), "review packet must be an object")
        packet_rows.append(packet)
    packets = packet_rows
    reviewer_ids = [_text(row.get("reviewerId"), "reviewerId", maximum=120) for row in reviewers]
    _require(len(set(reviewer_ids)) == 2, "reviewer IDs must be distinct")
    cases = _pool_cases(pool)
    expected_case_ids = {case["caseId"] for case in cases}
    for reviewer in reviewers:
        review_cases = reviewer.get("cases")
        _require(isinstance(review_cases, list), "reviewer cases must be a list")
        review_cases = cast(list[Any], review_cases)
        review_case_ids: list[str] = []
        for row in review_cases:
            _require(isinstance(row, dict), "review case must be an object")
            review_case_ids.append(_text(row.get("caseId"), "review caseId", maximum=80))
        _require(
            len(review_case_ids) == len(set(review_case_ids))
            and set(review_case_ids) == expected_case_ids,
            "reviewer must submit exactly one row for every pool case",
        )
    expected_pool_hash = _pool_hash(pool)
    map_by_case: dict[str, dict[str, Any]] = {}
    _require(isinstance(private_maps, list), "private maps must be a list")
    for mapping in private_maps:
        _require(isinstance(mapping, dict), "private map must be an object")
        _require(
            mapping.get("schemaVersion") == "retrieval-private-map-v1", "unsupported private map"
        )
        _require(
            mapping.get("poolSha256") == expected_pool_hash,
            "private map does not match frozen candidate pool",
        )
        mapping_cases = mapping.get("cases")
        _require(isinstance(mapping_cases, list), "private map cases must be a list")
        for case_value in cast(list[Any], mapping_cases):
            _require(isinstance(case_value, dict), "private map case must be an object")
            case = cast(dict[str, Any], case_value)
            case_id = _text(case.get("caseId"), "private caseId", maximum=80)
            _require(case_id not in map_by_case, "duplicate private map case")
            map_by_case[case_id] = case
    _require(
        set(map_by_case) == {case["caseId"] for case in cases},
        "private map must cover the pool cases",
    )

    packet_hashes: set[str] = set()
    packet_order_by_case: dict[str, list[list[str]]] = defaultdict(list)
    expected_cases = {case["caseId"]: case for case in cases}
    for packet in packets:
        _require(
            packet.get("schemaVersion") == "retrieval-blind-review-v1",
            "unsupported reviewer packet",
        )
        _require(
            set(packet).issubset({"schemaVersion", "poolSha256", "packetSha256", "cases"}),
            "review packet contains a prohibited field",
        )
        _require(packet.get("poolSha256") == expected_pool_hash, "review packet pool hash mismatch")
        packet_hash = _packet_hash(packet)
        _require(packet.get("packetSha256") == packet_hash, "review packet hash mismatch")
        _require(
            packet_hash not in packet_hashes, "reviewers must receive separately shuffled packets"
        )
        packet_hashes.add(packet_hash)
        packet_cases = packet.get("cases")
        _require(isinstance(packet_cases, list), "review packet cases must be a list")
        packet_case_map: dict[str, dict[str, Any]] = {}
        for packet_case_value in cast(list[Any], packet_cases):
            _require(isinstance(packet_case_value, dict), "review packet case must be an object")
            packet_case = cast(dict[str, Any], packet_case_value)
            packet_case_id = _text(packet_case.get("caseId"), "packet caseId", maximum=80)
            _require(packet_case_id not in packet_case_map, "duplicate reviewer packet case")
            packet_case_map[packet_case_id] = packet_case
        _require(set(packet_case_map) == set(expected_cases), "review packet case set mismatch")
        for case_id, packet_case in packet_case_map.items():
            mapping = map_by_case[case_id]
            _require(
                set(packet_case) == {"caseId", "question", "requirements", "candidates"},
                "review packet case contains a prohibited field",
            )
            _require(
                packet_case.get("question") == mapping.get("question")
                and packet_case.get("requirements") == mapping.get("requirements"),
                "review packet question/requirements do not match the private map",
            )
            pool_case = expected_cases[case_id]
            candidate_by_id = {
                candidate["candidateId"]: candidate for candidate in pool_case["candidates"]
            }
            candidate_map_rows = mapping.get("candidateMap")
            _require(isinstance(candidate_map_rows, list), "private candidate map missing")
            map_by_blind: dict[str, dict[str, Any]] = {}
            for row_value in cast(list[Any], candidate_map_rows):
                _require(isinstance(row_value, dict), "private map row must be an object")
                row = cast(dict[str, Any], row_value)
                blind_id = _text(row.get("blindId"), "private blindId", maximum=100)
                candidate_id = _text(row.get("candidateId"), "private candidateId", maximum=160)
                _require(blind_id not in map_by_blind, "duplicate private blind ID")
                _require(candidate_id in candidate_by_id, "private mapping candidate not in pool")
                map_by_blind[blind_id] = row
            candidate_rows = packet_case.get("candidates")
            _require(isinstance(candidate_rows, list), "review packet candidates must be a list")
            blind_order: list[str] = []
            for candidate_value in cast(list[Any], candidate_rows):
                _require(
                    isinstance(candidate_value, dict), "review packet candidate must be an object"
                )
                candidate = cast(dict[str, Any], candidate_value)
                blind_id = _text(candidate.get("blindId"), "blindId", maximum=100)
                _require(
                    set(candidate).issubset(
                        {"blindId", "title", "abstract", "year", "documentType"}
                    ),
                    "review packet contains a prohibited field",
                )
                _require(blind_id in map_by_blind, "review packet contains an unknown blind ID")
                blind_order.append(blind_id)
                pool_candidate = candidate_by_id[map_by_blind[blind_id]["candidateId"]]
                _require(
                    candidate.get("title") == pool_candidate.get("title")
                    and candidate.get("abstract", "") == pool_candidate.get("abstract", "")
                    and candidate.get("year") == pool_candidate.get("year")
                    and candidate.get("documentType") == pool_candidate.get("documentType"),
                    "review packet candidate does not match the frozen pool mapping",
                )
            _require(
                len(blind_order) == len(map_by_blind) and set(blind_order) == set(map_by_blind),
                "review packet candidate set mismatch",
            )
            packet_order_by_case[case_id].append(blind_order)
    for packet_orders in packet_order_by_case.values():
        if len(packet_orders[0]) > 1:
            _require(packet_orders[0] != packet_orders[1], "reviewer candidate orders must differ")
    reviewed_packet_hashes = {
        _text(row.get("packetSha256"), "reviewed packet SHA-256", maximum=64) for row in reviewers
    }
    _require(
        reviewed_packet_hashes == packet_hashes,
        "each reviewer must identify the exact packet they reviewed",
    )

    method_case_metrics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    method_case_domains: dict[str, list[str]] = defaultdict(list)
    overall_agreements = requirement_agreements = adjudicated_count = 0
    overall_comparisons = requirement_comparisons = 0

    for pool_case in cases:
        case_id = pool_case["caseId"]
        mapping = map_by_case[case_id]
        candidate_ids = {candidate["candidateId"] for candidate in pool_case["candidates"]}
        map_rows = mapping.get("candidateMap")
        _require(isinstance(map_rows, list), "private candidate map missing")
        map_rows = cast(list[Any], map_rows)
        candidate_map: dict[str, dict[str, Any]] = {}
        blind_to_candidate: dict[str, str] = {}
        for row_value in map_rows:
            _require(isinstance(row_value, dict), "private map row must be an object")
            row = cast(dict[str, Any], row_value)
            candidate_id = _text(row.get("candidateId"), "candidateId", maximum=160)
            blind_id = _text(row.get("blindId"), "blindId", maximum=100)
            _require(candidate_id not in candidate_map, "duplicate private candidate ID")
            _require(blind_id not in blind_to_candidate, "duplicate private blind ID")
            candidate_map[candidate_id] = row
            blind_to_candidate[blind_id] = candidate_id
        _require(
            set(candidate_map) == candidate_ids and len(blind_to_candidate) == len(map_rows),
            "private candidate map does not match pool",
        )
        blind_ids = set(blind_to_candidate)
        # Requirements are part of the sealed case fixture; the pool stores only its case ID.
        # The case fixture is copied into the private map during preparation by the CLI.
        requirements = mapping.get("requirements")
        _require(
            isinstance(requirements, list) and bool(requirements),
            "private map must include case requirements",
        )
        requirements = cast(list[Any], requirements)
        _require(
            all(isinstance(row, dict) and isinstance(row.get("id"), str) for row in requirements),
            "invalid private requirements",
        )
        requirements = cast(list[dict[str, Any]], requirements)
        requirement_ids = {row["id"] for row in requirements}
        _require(len(requirement_ids) == len(requirements), "duplicate private requirement IDs")
        left = _case_labels(reviewers[0], case_id, blind_ids, requirement_ids)
        right = _case_labels(reviewers[1], case_id, blind_ids, requirement_ids)
        disputed: set[str] = set()
        adjudicated_labels: dict[str, dict[str, Any]] = {}
        for blind_id in blind_ids:
            same_overall = left[blind_id]["relevance"] == right[blind_id]["relevance"]
            same_requirements = (
                left[blind_id]["requirementMatches"] == right[blind_id]["requirementMatches"]
            )
            overall_comparisons += 1
            overall_agreements += int(same_overall)
            requirement_comparisons += len(requirement_ids)
            requirement_agreements += sum(
                left[blind_id]["requirementMatches"][key]
                == right[blind_id]["requirementMatches"][key]
                for key in requirement_ids
            )
            if same_overall and same_requirements:
                adjudicated_labels[blind_id] = left[blind_id]
            else:
                disputed.add(blind_id)
        if disputed:
            case_adjudication = _adjudication_labels(
                adjudication,
                case_id,
                disputed,
                blind_ids,
                requirement_ids,
                set(reviewer_ids),
            )
            adjudicated_labels.update(case_adjudication)
            adjudicated_count += len(disputed)

        relevance_by_candidate = {
            blind_to_candidate[blind_id]: label["relevance"]
            for blind_id, label in adjudicated_labels.items()
        }
        requirements_by_candidate = {
            blind_to_candidate[blind_id]: label["requirementMatches"]
            for blind_id, label in adjudicated_labels.items()
        }
        all_direct = sum(value == "direct" for value in relevance_by_candidate.values())
        for method, ranked_blind_ids in mapping.get("rankings", {}).items():
            ranked_ids = [blind_to_candidate[blind_id] for blind_id in ranked_blind_ids]
            selected = ranked_ids[:cutoff]
            direct = [
                candidate_id
                for candidate_id in selected
                if relevance_by_candidate[candidate_id] == "direct"
            ]
            covered_requirements = {
                requirement_id
                for candidate_id in direct
                for requirement_id, match in requirements_by_candidate[candidate_id].items()
                if match == "yes"
            }
            work_values = [
                candidate_map[candidate_id].get("workIdentity") for candidate_id in selected
            ]
            version_values = [
                candidate_map[candidate_id].get("versionGroup") for candidate_id in selected
            ]
            known_work = [value for value in work_values if isinstance(value, str) and value]
            known_versions = [value for value in version_values if isinstance(value, str) and value]
            seen_work: set[str] = set()
            duplicate_works = 0
            for value in known_work:
                duplicate_works += value in seen_work
                seen_work.add(value)
            seen_versions: set[str] = set()
            duplicate_versions = 0
            for value in known_versions:
                duplicate_versions += value in seen_versions
                seen_versions.add(value)
            metric = {
                "caseId": case_id,
                "directPrecisionAtK": _fraction(len(direct), len(selected)),
                "partialAtK": sum(relevance_by_candidate[item] == "partial" for item in selected),
                "candidatePoolRecallAtK": _fraction(len(direct), all_direct),
                "requirementCoverageAtK": _fraction(
                    len(covered_requirements), len(requirement_ids)
                ),
                "duplicateWorkRateAtK": _fraction(duplicate_works, len(known_work)),
                "versionRepeatRateAtK": _fraction(duplicate_versions, len(known_versions)),
                "retrievedCountAtK": len(selected),
                "knownWorkIdentityCountAtK": len(known_work),
                "knownVersionGroupCountAtK": len(known_versions),
            }
            method_case_metrics[method].append(metric)
            method_case_domains[method].append(str(mapping.get("domain", "unknown")))

    methods: dict[str, Any] = {}
    for method, rows in method_case_metrics.items():
        by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row, domain in zip(rows, method_case_domains[method], strict=True):
            by_domain[domain].append(row)
        domains = {
            domain: {
                key: _mean([row[key] for row in domain_rows])
                for key in (
                    "directPrecisionAtK",
                    "candidatePoolRecallAtK",
                    "requirementCoverageAtK",
                    "duplicateWorkRateAtK",
                    "versionRepeatRateAtK",
                )
            }
            for domain, domain_rows in sorted(by_domain.items())
        }
        methods[method] = {
            "cases": rows,
            "macro": {
                key: _mean([row[key] for row in rows])
                for key in (
                    "directPrecisionAtK",
                    "candidatePoolRecallAtK",
                    "requirementCoverageAtK",
                    "duplicateWorkRateAtK",
                    "versionRepeatRateAtK",
                )
            },
            "domains": domains,
        }
    return {
        "schemaVersion": "retrieval-score-v1",
        "cutoff": cutoff,
        "candidatePoolCases": len(cases),
        "candidatePoolSha256": expected_pool_hash,
        "methods": methods,
        "reviewAgreement": {
            "overallLabelAgreement": _fraction(overall_agreements, overall_comparisons),
            "overallLabelsCompared": overall_comparisons,
            "requirementLabelAgreement": _fraction(requirement_agreements, requirement_comparisons),
            "requirementLabelsCompared": requirement_comparisons,
            "disputedCandidatesAdjudicated": adjudicated_count,
        },
        "scopeNote": "candidate-pool recall is not corpus recall",
        "endToEndEvidenceUsefulness": "not_measured_by_metadata_review",
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_cases(path: Path) -> dict[str, dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        _require(isinstance(row, dict), "case fixture rows must be objects")
        case_id = _text(row.get("id"), "case fixture id", maximum=80)
        _require(case_id not in output, "duplicate case fixture ID")
        output[case_id] = row
    return output


def _write_json(path: Path, value: Any, *, private: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="write blind review packet and private mapping")
    prepare.add_argument("--pool", type=Path, required=True)
    prepare.add_argument("--cases", type=Path, required=True)
    prepare.add_argument("--packet", type=Path, required=True)
    prepare.add_argument("--private-map", type=Path, required=True)
    prepare.add_argument("--seed", type=int, required=True)
    score = subparsers.add_parser(
        "score", help="score adjudicated labels on the shared candidate pool"
    )
    score.add_argument("--pool", type=Path, required=True)
    score.add_argument("--private-map", type=Path, required=True)
    score.add_argument("--packets", type=Path, nargs=2, required=True)
    score.add_argument(
        "--reviewers", type=Path, required=True, help="JSON array with exactly two review records"
    )
    score.add_argument("--adjudication", type=Path)
    score.add_argument("--cutoff", type=int, default=10)
    score.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        cases = _read_cases(args.cases)
        packet, private_map = prepare_blind_review(_read_json(args.pool), cases, seed=args.seed)
        _write_json(args.packet, packet, private=True)
        _write_json(args.private_map, private_map, private=True)
        return
    result = score_retrieval_pool(
        _read_json(args.pool),
        [_read_json(args.private_map)],
        _read_json(args.reviewers),
        [_read_json(path) for path in args.packets],
        cutoff=args.cutoff,
        adjudication=_read_json(args.adjudication) if args.adjudication else None,
    )
    _write_json(args.output, result, private=True)


if __name__ == "__main__":
    main()
