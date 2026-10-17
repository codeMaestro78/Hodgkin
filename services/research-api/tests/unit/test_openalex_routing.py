import pytest

from research_api import jobs
from research_api.config import Settings
from research_api.graph import builder


@pytest.mark.parametrize(
    ("explicit_mode", "serper", "openalex", "expected"),
    [
        (False, False, False, jobs.GRAPH_VERSION),
        (False, True, False, jobs.SERPER_GRAPH_VERSION),
        (False, False, True, jobs.OPENALEX_GRAPH_VERSION),
        (False, True, True, jobs.OPENALEX_SERPER_GRAPH_VERSION),
        (True, False, False, jobs.SAFE_MODE_GRAPH_VERSION),
        (True, True, False, jobs.SAFE_MODE_SERPER_GRAPH_VERSION),
        (True, False, True, jobs.SAFE_MODE_OPENALEX_GRAPH_VERSION),
        (True, True, True, jobs.SAFE_MODE_OPENALEX_SERPER_GRAPH_VERSION),
    ],
)
def test_new_job_pins_each_discovery_capability_combination(
    explicit_mode, serper, openalex, expected
):
    settings = Settings(
        _env_file=None,
        SERPER_DISCOVERY_ENABLED=serper,
        OPENALEX_DISCOVERY_ENABLED=openalex,
        BOUNDED_GAP_REPAIR_ENABLED=False,
    )

    assert jobs.graph_version_for(settings, explicit_mode=explicit_mode) == expected


@pytest.mark.parametrize(
    ("serper", "openalex", "expected"),
    [
        (False, False, jobs.REPAIR_MODE_GRAPH_VERSION),
        (True, False, jobs.REPAIR_MODE_SERPER_GRAPH_VERSION),
        (False, True, jobs.REPAIR_MODE_OPENALEX_GRAPH_VERSION),
        (True, True, jobs.REPAIR_MODE_OPENALEX_SERPER_GRAPH_VERSION),
    ],
)
def test_explicit_repair_is_selected_only_when_opted_in(serper, openalex, expected):
    settings = Settings(
        _env_file=None,
        SERPER_DISCOVERY_ENABLED=serper,
        OPENALEX_DISCOVERY_ENABLED=openalex,
        BOUNDED_GAP_REPAIR_ENABLED=True,
    )

    assert jobs.graph_version_for(settings, explicit_mode=True) == expected


def test_openalex_explicit_mode_version_keeps_v10_repair_and_narrative_contract():
    assert jobs.MODE_OPENALEX_GRAPH_VERSION in builder.NARRATIVE_GRAPH_VERSIONS
    assert jobs.MODE_OPENALEX_GRAPH_VERSION in builder.REPAIR_GRAPH_VERSIONS
    assert jobs.MODE_OPENALEX_SERPER_GRAPH_VERSION in builder.SERPER_GRAPH_VERSIONS
    assert jobs.EXPANDED_MODE_OPENALEX_GRAPH_VERSION in builder.OPENALEX_GRAPH_VERSIONS
    assert jobs.EXPANDED_MODE_OPENALEX_GRAPH_VERSION in builder.REPAIR_GRAPH_VERSIONS
    assert jobs.EXPANDED_MODE_OPENALEX_SERPER_GRAPH_VERSION in builder.SERPER_GRAPH_VERSIONS


def test_openalex_legacy_version_does_not_enable_explicit_mode_features():
    assert jobs.OPENALEX_GRAPH_VERSION not in builder.NARRATIVE_GRAPH_VERSIONS
    assert jobs.OPENALEX_GRAPH_VERSION not in builder.REPAIR_GRAPH_VERSIONS


def test_criterion_output_budget_keeps_older_replay_contracts():
    assert jobs.MODE_GRAPH_VERSION not in builder.EXPANDED_CRITERION_GRAPH_VERSIONS
    assert jobs.MODE_OPENALEX_GRAPH_VERSION not in builder.EXPANDED_CRITERION_GRAPH_VERSIONS
    assert jobs.EXPANDED_MODE_GRAPH_VERSION in builder.EXPANDED_CRITERION_GRAPH_VERSIONS
    assert jobs.EXPANDED_MODE_OPENALEX_GRAPH_VERSION in builder.EXPANDED_CRITERION_GRAPH_VERSIONS
    assert jobs.SAFE_MODE_GRAPH_VERSION in builder.EXPANDED_CRITERION_GRAPH_VERSIONS
    assert jobs.SAFE_MODE_GRAPH_VERSION not in builder.REPAIR_GRAPH_VERSIONS
    assert jobs.REPAIR_MODE_GRAPH_VERSION in builder.REPAIR_GRAPH_VERSIONS


def test_new_explicit_graph_versions_pin_repair_capability_and_routing():
    safe = (
        jobs.SAFE_MODE_GRAPH_VERSION,
        jobs.SAFE_MODE_SERPER_GRAPH_VERSION,
        jobs.SAFE_MODE_OPENALEX_GRAPH_VERSION,
        jobs.SAFE_MODE_OPENALEX_SERPER_GRAPH_VERSION,
    )
    repair = (
        jobs.REPAIR_MODE_GRAPH_VERSION,
        jobs.REPAIR_MODE_SERPER_GRAPH_VERSION,
        jobs.REPAIR_MODE_OPENALEX_GRAPH_VERSION,
        jobs.REPAIR_MODE_OPENALEX_SERPER_GRAPH_VERSION,
    )
    assert all(version in builder.NARRATIVE_GRAPH_VERSIONS for version in (*safe, *repair))
    assert all(version not in builder.REPAIR_GRAPH_VERSIONS for version in safe)
    assert all(version in builder.REPAIR_GRAPH_VERSIONS for version in repair)
    assert all(version in builder.EXPANDED_CRITERION_GRAPH_VERSIONS for version in (*safe, *repair))
    assert all(
        version in builder.OPENALEX_GRAPH_VERSIONS
        for version in (safe[2], safe[3], repair[2], repair[3])
    )
    assert all(
        version in builder.SERPER_GRAPH_VERSIONS
        for version in (safe[1], safe[3], repair[1], repair[3])
    )
