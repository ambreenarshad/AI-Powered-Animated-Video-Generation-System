# graph2.py
"""
Phase 2 LangGraph Workflow
──────────────────────────
Architecture:
  scene_parser_node
        │
        ├─── Send() ──→ voice_synth_node  (audio branch — parallel per scene)
        │                      │
        └─── Send() ──→ video_gen_node    (video branch — parallel per scene)
                               │
                         face_swap_node
                               │
                         lip_sync_node   ← fusion layer (audio + video converge)
                               │
                             END

Both branches fire simultaneously via LangGraph's Send() API.
The lip_sync_node is the rendezvous point that waits for both.
"""

from langgraph.graph import StateGraph, END
from langgraph.types import Send
from state2 import Phase2State

import agents2.scene_parser as sp
import agents2.voice_synth  as vs
import agents2.video_gen    as vg
import agents2.face_swap    as fs
import agents2.lip_sync     as ls


# ── Node wrappers (lambda ensures patches via module refs take effect) ─────────

def scene_parser_node(state: Phase2State) -> Phase2State:
    return sp.scene_parser_agent(state)


def voice_synth_node(state: Phase2State) -> Phase2State:
    return vs.voice_synth_agent(state)


def video_gen_node(state: Phase2State) -> Phase2State:
    return vg.video_gen_agent(state)


def face_swap_node(state: Phase2State) -> Phase2State:
    return fs.face_swap_agent(state)


def lip_sync_node(state: Phase2State) -> Phase2State:
    return ls.lip_sync_agent(state)


# ── Parallel fan-out: after scene_parser, fire BOTH branches simultaneously ────

def fan_out_to_parallel_branches(state: Phase2State):
    voice_input = {
        "task_graph": state["task_graph"],
        "characters": state["characters"],
    }

    video_input = {
        "task_graph": state["task_graph"],
        "images_dir": state["images_dir"],
    }

    return [
        Send("voice_synth_node", voice_input),
        Send("video_gen_node",   video_input),
    ]


def build_graph2():
    graph = StateGraph(Phase2State)

    # ── Register nodes ────────────────────────────────────────────────────────
    graph.add_node("scene_parser_node", scene_parser_node)
    graph.add_node("voice_synth_node",  voice_synth_node)
    graph.add_node("video_gen_node",    video_gen_node)
    graph.add_node("face_swap_node",    face_swap_node)
    graph.add_node("lip_sync_node",     lip_sync_node)

    # ── Entry point ───────────────────────────────────────────────────────────
    graph.set_entry_point("scene_parser_node")

    # ── Parallel fan-out via Send() ───────────────────────────────────────────
    graph.add_conditional_edges(
        "scene_parser_node",
        fan_out_to_parallel_branches,
        ["voice_synth_node", "video_gen_node"]   # valid target nodes
    )

    # ── Both parallel branches converge at face_swap_node ────────────────────
    graph.add_edge("voice_synth_node", "face_swap_node")
    graph.add_edge("video_gen_node",   "face_swap_node")

    # ── Sequential tail ───────────────────────────────────────────────────────
    graph.add_edge("face_swap_node", "lip_sync_node")
    graph.add_edge("lip_sync_node",  END)

    return graph.compile()