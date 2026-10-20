from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END


def _node(_state: dict[str, Any]) -> dict[str, Any]:
    return {}


def test_research_graph_topology_preserves_persisted_node_ids_and_approval_edges():
    from research_api.graph.topology import compile_research_graph

    graph = compile_research_graph(
        nodes={
            name: _node
            for name in (
                "intake",
                "planner",
                "approval_gate",
                "research_worker",
                "assess_evidence",
                "reflector",
                "planner_delta",
                "verifier",
                "synthesizer",
            )
        },
        checkpointer=InMemorySaver(),
    )

    snapshot = graph.get_graph()
    assert set(snapshot.nodes) == {
        "__start__",
        "__end__",
        "intake",
        "planner",
        "approval_gate",
        "research_worker",
        "assess_evidence",
        "reflector",
        "planner_delta",
        "verifier",
        "synthesizer",
    }
    edges = {(edge.source, edge.target) for edge in snapshot.edges}
    assert ("planner", "approval_gate") in edges
    assert ("approval_gate", "research_worker") in edges
    assert ("synthesizer", END) in edges


def test_research_graph_without_checkpointer_keeps_approval_node_out():
    from research_api.graph.topology import compile_research_graph

    graph = compile_research_graph(
        nodes={
            name: _node
            for name in (
                "intake",
                "planner",
                "research_worker",
                "assess_evidence",
                "reflector",
                "planner_delta",
                "verifier",
                "synthesizer",
            )
        },
        checkpointer=None,
    )
    snapshot = graph.get_graph()
    assert "approval_gate" not in snapshot.nodes
    assert ("planner", "research_worker") in {
        (edge.source, edge.target) for edge in snapshot.edges
    }
