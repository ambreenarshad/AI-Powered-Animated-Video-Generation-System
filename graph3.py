# graph3.py
"""
Phase 3 LangGraph Workflow — Video Generation & Composition
────────────────────────────────────────────────────────────
Architecture (linear):

  visual_prompt_node
        │
  scene_visual_node     ← WAN Alibaba API: generates per-scene video clips
        │
  animator_node         ← Ken Burns zoom/pan via MoviePy
        │
  av_sync_node          ← Align audio tracks to visual clips
        │
  compositor_node       ← Transitions + subtitles → final MP4
        │
       END
"""

from langgraph.graph import StateGraph, END
from state3 import Phase3State

import agents3.visual_prompt_agent as vpa
import agents3.scene_visual_agent  as sva
import agents3.animator_agent      as aa
import agents3.av_sync_agent       as asa
import agents3.compositor_agent    as ca


def visual_prompt_node(state: Phase3State) -> Phase3State:
    return vpa.visual_prompt_agent(state)

def scene_visual_node(state: Phase3State) -> Phase3State:
    return sva.scene_visual_agent(state)

def animator_node(state: Phase3State) -> Phase3State:
    return aa.animator_agent(state)

def av_sync_node(state: Phase3State) -> Phase3State:
    return asa.av_sync_agent(state)

def compositor_node(state: Phase3State) -> Phase3State:
    return ca.compositor_agent(state)


def build_graph3():
    graph = StateGraph(Phase3State)

    graph.add_node("visual_prompt_node", visual_prompt_node)
    graph.add_node("scene_visual_node",  scene_visual_node)
    graph.add_node("animator_node",      animator_node)
    graph.add_node("av_sync_node",       av_sync_node)
    graph.add_node("compositor_node",    compositor_node)

    graph.set_entry_point("visual_prompt_node")
    graph.add_edge("visual_prompt_node", "scene_visual_node")
    graph.add_edge("scene_visual_node",  "animator_node")
    graph.add_edge("animator_node",      "av_sync_node")
    graph.add_edge("av_sync_node",       "compositor_node")
    graph.add_edge("compositor_node",    END)

    return graph.compile()