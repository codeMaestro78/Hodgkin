"""Stable research graph topology, independent of node implementation details."""

from collections.abc import Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from research_api.graph.state import RunState


def compile_research_graph(*, nodes: Mapping[str, Any], checkpointer: Any = None) -> Any:
    """Wire persisted node IDs and routing rules, then compile with the saver.

    Keep edge conditions semantically aligned with historical checkpoints:
    approval is present only for durable jobs; repair and reflection routing
    remain conditional on the existing state fields.
    """
    graph = StateGraph(RunState)
    for name, node in nodes.items():
        graph.add_node(name, node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "planner")
    if checkpointer is not None:
        graph.add_edge("planner", "approval_gate")
        graph.add_edge("approval_gate", "research_worker")
    else:
        graph.add_edge("planner", "research_worker")
    graph.add_conditional_edges(
        "research_worker",
        lambda state: "assess_evidence" if state.get("mode") else "reflector",
        path_map={"assess_evidence": "assess_evidence", "reflector": "reflector"},
    )
    graph.add_edge("assess_evidence", "reflector")
    graph.add_conditional_edges(
        "reflector",
        lambda state: "planner_delta" if state.get("expand") else "verifier",
        path_map={"planner_delta": "planner_delta", "verifier": "verifier"},
    )
    graph.add_conditional_edges(
        "planner_delta",
        lambda state: (
            ("research_worker" if state.get("repair_admitted") else "verifier")
            if state.get("mode")
            else ("approval_gate" if checkpointer else "research_worker")
        ),
        path_map={
            "research_worker": "research_worker",
            "verifier": "verifier",
            **({"approval_gate": "approval_gate"} if checkpointer else {}),
        },
    )
    graph.add_edge("verifier", "synthesizer")
    graph.add_edge("synthesizer", END)
    return graph.compile(checkpointer=checkpointer)
