# graph.py  (Phase 1 — updated with lambda-wrapper fix)
from langgraph.graph import StateGraph, END
from state import GraphState

import agents.scriptwriter as sw
import agents.validator    as vl
import agents.character    as ch
import agents.image        as im
import agents.hitl         as hl


def route_after_hitl(state: dict) -> str:
    if state.get("status") == "rejected":
        return "scriptwriter"
    return "character"


def build_graph():
    graph = StateGraph(GraphState)

    # Lambda wrappers ensure _patch_agents() in main.py is always respected —
    # the graph calls through the module reference at runtime, not a stale copy.
    graph.add_node("scriptwriter", lambda s: sw.scriptwriter_agent(s))
    graph.add_node("validator",    lambda s: vl.validator_agent(s))
    graph.add_node("hitl",         lambda s: hl.hitl_agent(s))
    graph.add_node("character",    lambda s: ch.character_agent(s))
    graph.add_node("image",        lambda s: im.image_agent(s))

    graph.set_entry_point("scriptwriter")

    graph.add_edge("scriptwriter", "validator")
    graph.add_edge("validator",    "hitl")

    graph.add_conditional_edges("hitl", route_after_hitl, {
        "scriptwriter": "scriptwriter",
        "character":    "character",
    })

    graph.add_edge("character", "image")
    graph.add_edge("image",     END)

    return graph.compile()