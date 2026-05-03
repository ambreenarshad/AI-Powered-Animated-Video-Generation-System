"""
graph3.py
──────────
Phase 3 LangGraph Workflow — Per-Character Video Generation & Composition

Pipeline (6 stages, linear):

  manifest_loader_node
        │
  image_gen_node         ← Qwen-Image-2.0-Pro: per-character per-scene images
        │
  ken_burns_node         ← Wan2.6-I2V: per-character lip-sync video generation
        │
  av_sync_node           ← FFmpeg: attach dialogue audio to each character video
        │
  scene_merge_node       ← FFmpeg: composite character clips → scene video
        │
  compositor_node        ← FFmpeg: concat scenes + burn subtitles → final MP4
        │
       END
"""

from langgraph.graph import StateGraph, END
from state3 import Phase3State

import agents3.manifest_loader   as ml
import agents3.image_gen         as ig
import agents3.ken_burns         as kb
import agents3.av_sync_agent     as ava
import agents3.scene_merge_agent as sma
import agents3.compositor_agent  as ca


def manifest_loader_node(state: Phase3State) -> Phase3State:
    return ml.manifest_loader_agent(state)

def image_gen_node(state: Phase3State) -> Phase3State:
    return ig.image_gen_agent(state)

def ken_burns_node(state: Phase3State) -> Phase3State:
    return kb.ken_burns_agent(state)

def av_sync_node(state: Phase3State) -> Phase3State:
    return ava.av_sync_agent(state)

def scene_merge_node(state: Phase3State) -> Phase3State:
    return sma.scene_merge_agent(state)

def compositor_node(state: Phase3State) -> Phase3State:
    return ca.compositor_agent(state)


def build_graph3():
    graph = StateGraph(Phase3State)

    graph.add_node("manifest_loader_node", manifest_loader_node)
    graph.add_node("image_gen_node",       image_gen_node)
    graph.add_node("ken_burns_node",       ken_burns_node)
    graph.add_node("av_sync_node",         av_sync_node)
    graph.add_node("scene_merge_node",     scene_merge_node)
    graph.add_node("compositor_node",      compositor_node)

    graph.set_entry_point("manifest_loader_node")
    graph.add_edge("manifest_loader_node", "image_gen_node")
    graph.add_edge("image_gen_node",       "ken_burns_node")
    graph.add_edge("ken_burns_node",       "av_sync_node")
    graph.add_edge("av_sync_node",         "scene_merge_node")
    graph.add_edge("scene_merge_node",     "compositor_node")
    graph.add_edge("compositor_node",      END)

    return graph.compile()