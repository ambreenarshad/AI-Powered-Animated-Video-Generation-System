# agents3/visual_prompt_agent.py
"""
Visual Prompt Agent
───────────────────
Reads scene_manifest + timing_manifest, builds an engineered visual
prompt for each scene (sent later to WAN), and constructs the task graph.
"""

import json
import os
from typing import List, Dict, Any

from llm import get_llm_response


# ---------------------------------------------------------------------------
# Prompt engineering helpers
# ---------------------------------------------------------------------------

STYLE_SUFFIX = (
    "cinematic lighting, film grain, shallow depth of field, "
    "photorealistic, 4K, dramatic composition"
)


def _engineer_prompt(scene: Dict[str, Any], characters: List[str]) -> str:
    location  = scene.get("location", "unknown location")
    char_list = ", ".join(characters) if characters else "characters"
    dialogues = scene.get("dialogue", [])
    cues      = [d.get("visual_cue", "") for d in dialogues if d.get("visual_cue")]
    cue_text  = ". ".join(cues) if cues else ""

    base = f"{location}. {char_list} in scene."
    if cue_text:
        base += f" {cue_text}."

    # Ask LLM to enrich into a vivid visual description
    llm_prompt = (
        f"You are a cinematographer. Given this scene brief, write a single vivid "
        f"visual description (max 80 words) suitable for an AI video generator. "
        f"Do NOT include any dialogue. Focus on visual composition, lighting, mood.\n\n"
        f"Scene brief: {base}\n\nVisual description:"
    )
    try:
        enriched = get_llm_response(llm_prompt).strip()
    except Exception:
        enriched = base  # fallback

    return f"{enriched}, {STYLE_SUFFIX}"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def visual_prompt_agent(state: dict) -> dict:
    print("[Phase 3 · Visual Prompt Agent] Building visual prompts…")

    # ── Load scene manifest ────────────────────────────────────────────────
    manifest_path = state["scene_manifest_path"]
    if not os.path.exists(manifest_path):
        return {**state, "status": "error",
                "error": f"scene_manifest not found: {manifest_path}"}

    with open(manifest_path) as f:
        manifest = json.load(f)

    scenes: List[Dict] = manifest.get("scenes", [])

    # ── Load timing manifest ───────────────────────────────────────────────
    timing_path = state["timing_manifest_path"]
    if not os.path.exists(timing_path):
        return {**state, "status": "error",
                "error": f"timing_manifest not found: {timing_path}"}

    with open(timing_path) as f:
        timing_data = json.load(f)

    # Build lookup: scene_id → timing entry
    timing_lookup: Dict[int, Dict] = {}
    for entry in timing_data:
        sid = entry.get("scene_id")
        if sid is not None:
            timing_lookup[sid] = entry

    # ── Build task graph ───────────────────────────────────────────────────
    task_graph = []
    audio_dir  = state.get("audio_dir", "outputs/audio")

    for scene in scenes:
        sid        = scene["scene_id"]
        characters = scene.get("characters", [])
        timing     = timing_lookup.get(sid, {})
        start_ms   = timing.get("start_ms", 0)
        end_ms     = timing.get("end_ms",   5000)
        duration   = (end_ms - start_ms) / 1000.0

        # Ensure minimum duration for a watchable clip
        duration = max(duration, 3.0)

        # Audio path: prefer timing manifest, fall back to convention
        audio_path = timing.get("audio_file") or os.path.join(
            audio_dir, f"scene_{sid:02d}.wav"
        )
        if not os.path.isabs(audio_path):
            audio_path = audio_path  # keep relative; resolved at sync step

        visual_prompt = _engineer_prompt(scene, characters)

        task: Dict[str, Any] = {
            "scene_id":      sid,
            "location":      scene.get("location", ""),
            "visual_prompt": visual_prompt,
            "characters":    characters,
            "dialogue":      scene.get("dialogue", []),
            "audio_path":    audio_path,
            "start_ms":      start_ms,
            "end_ms":        end_ms,
            "duration_sec":  duration,
            "raw_frames":    [],
            "animated_clip": None,
            "synced_clip":   None,
            "status":        "pending",
            "error":         None,
        }
        task_graph.append(task)
        print(f"  → Scene {sid}: prompt engineered ({duration:.1f}s)")

    print(f"[Phase 3 · Visual Prompt Agent] ✅ {len(task_graph)} tasks ready.")

    return {
        **state,
        "scenes":          scenes,
        "timing_manifest": timing_data,
        "task_graph":      task_graph,
        "visual_results":  [],
        "animated_results":[],
        "synced_results":  [],
        "task_log":        [],
    }