from uuid import UUID

from research_api import jobs
from research_api.coverage import Criterion, Dimension
from research_api.graph import builder


def dimension(label):
    return Dimension(
        id=UUID(int=1), label=label, criteria=(Criterion(id=UUID(int=2), label="Evidence"),)
    )


def test_repair_query_is_deterministic_bounded_and_deduplicated():
    query = builder._repair_query(
        dimension("  Retention   period "), ["Retention period", " Cost "]
    )
    assert query == "Retention period ; Cost"
    long = builder._repair_query(dimension("word " * 150), ["tail"])
    assert len(long) <= builder.REPAIR_QUERY_CHARS
    assert not long.endswith((" ", ";")) and long.split()[-1] == "word"


def test_only_v10_jobs_without_approval_are_repair_capable():
    assert builder._repair_capable(jobs.MODE_GRAPH_VERSION, False)
    assert builder._repair_capable(jobs.MODE_SERPER_GRAPH_VERSION, False)
    assert not builder._repair_capable(jobs.MODE_GRAPH_VERSION, True)
    assert not builder._repair_capable(jobs.NARRATIVE_MODE_GRAPH_VERSION, False)
    assert not builder._repair_capable(jobs.NARRATIVE_MODE_SERPER_GRAPH_VERSION, False)
    assert jobs.NARRATIVE_MODE_GRAPH_VERSION in builder.NARRATIVE_GRAPH_VERSIONS


def test_repair_writer_schema_caps_delta_claims():
    model = builder._repair_assertions_model(3, [])
    assert model.model_json_schema()["properties"]["claims"]["maxItems"] == 3
    assert builder._union_assertions_model(["x"]) is builder.DeepRequirementAssertions
