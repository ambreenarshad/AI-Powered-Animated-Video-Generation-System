# graph2.py
"""
Phase 2 LangGraph Workflow  —  Audio Generation
────────────────────────────────────────────────
Architecture (linear):

  scene_parser_node
        │
  voice_synth_node   (parallel per-scene internally)
        │
       END
"""

from langgraph.graph import StateGraph, END
from state2 import Phase2State

import agents2.scene_parser as sp
import agents2.voice_synth  as vs


def scene_parser_node(state: Phase2State) -> Phase2State:
    return sp.scene_parser_agent(state)


def voice_synth_node(state: Phase2State) -> Phase2State:
    return vs.voice_synth_agent(state)


def build_graph2():
    graph = StateGraph(Phase2State)

    graph.add_node("scene_parser_node", scene_parser_node)
    graph.add_node("voice_synth_node",  voice_synth_node)

    graph.set_entry_point("scene_parser_node")
    graph.add_edge("scene_parser_node", "voice_synth_node")
    graph.add_edge("voice_synth_node",  END)

    return graph.compile()