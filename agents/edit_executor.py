"""
agents/edit_executor.py
────────────────────────
Edit Executor
Receives a classified intent and routes execution to the correct
pipeline sub-step, then snapshots the resulting state.

Supported targets:
  audio       → re-run voice synthesis for affected scene/character
  video_frame → re-run image generation with updated prompt
  video       → re-run compositor (recompose) with updated parameters
  script      → re-run Phase 1 scriptwriter from scratch
"""

import os
import re
import json
from typing import Callable

from utils.state_manager import get_state_manager


# ── Asset collection helpers ──────────────────────────────────────────────────

def _collect_audio_assets() -> list[str]:
    paths = []
    for root, _, files in os.walk("outputs/audio"):
        for f in files:
            if f.endswith(".wav"):
                paths.append(os.path.join(root, f))
    return paths


def _collect_video_assets() -> list[str]:
    paths = []
    for folder in ["outputs/video", "outputs/clips", "outputs/images"]:
        if not os.path.exists(folder):
            continue
        for root, _, files in os.walk(folder):
            for f in files:
                if f.endswith((".mp4", ".png", ".jpg", ".srt")):
                    paths.append(os.path.join(root, f))
    return paths


def _collect_all_assets() -> list[str]:
    return _collect_audio_assets() + _collect_video_assets()


# ── Target-specific executors ─────────────────────────────────────────────────

def _execute_audio_edit(intent: dict, state: dict) -> dict:
    """Re-synthesise audio for the targeted character/scene."""
    from mcp.init2 import register_tools_p2
    from agents2.voice_synth import voice_synth_agent

    params    = intent.get("parameters", {})
    scope     = intent.get("scope", "all")
    tone      = params.get("tone", "neutral")

    print(f"[EditExecutor] Audio edit — scope={scope}, tone={tone}")

    # If character-scoped, inject a tone override into char_voice_params
    if scope.startswith("character:"):
        char_name = scope.split(":", 1)[1].strip()
        # Inject tone hint into task graph dialogue metadata
        for task in state.get("task_graph", []):
            for dlg in task.get("dialogue", []):
                if dlg.get("speaker", "").lower() == char_name.lower():
                    dlg["_tone_override"] = tone

    # Re-run voice synthesis
    try:
        register_tools_p2()
        new_state = voice_synth_agent(state)
        state.update(new_state)
    except Exception as e:
        print(f"[EditExecutor] Audio re-synthesis error: {e}")
        state["_edit_error"] = str(e)

    return state


def _execute_video_frame_edit(intent: dict, state: dict) -> dict:
    """Re-generate images for targeted scenes/characters with updated prompts."""
    from agents3.image_gen import image_gen_agent

    params    = intent.get("parameters", {})
    scope     = intent.get("scope", "all")
    filters   = params.get("filters", [])
    filter_presets = params.get("filter_presets", {})

    print(f"[EditExecutor] Video-frame edit — scope={scope}, filters={filters}")

    # Inject aesthetic modifiers into task graph
    for task in state.get("task_graph", []):
        sid = task["scene_id"]

        if scope.startswith("scene:"):
            target_sid = int(scope.split(":")[1])
            if sid != target_sid:
                continue

        for clip in task.get("character_clips", []):
            char_name = clip.get("character_name", "")

            if scope.startswith("character:"):
                target_char = scope.split(":", 1)[1].strip().lower()
                if char_name.lower() != target_char:
                    continue

            # Force re-generation by clearing image path
            clip["image_path"] = None
            clip["status"]     = "pending"

            # Store filter instructions for image prompt augmentation
            if filters:
                clip["_aesthetic_modifiers"] = filters
            if filter_presets:
                clip["_filter_presets"] = filter_presets

    # Re-run image gen
    try:
        new_state = image_gen_agent(state)
        state.update(new_state)
    except Exception as e:
        print(f"[EditExecutor] Image re-gen error: {e}")
        state["_edit_error"] = str(e)

    return state


def _execute_video_edit(intent: dict, state: dict) -> dict:
    """Recompose video with updated parameters (subtitles, speed, etc.)."""
    from agents3.compositor_agent import compositor_agent
    from agents3.av_sync_agent import av_sync_agent

    params = intent.get("parameters", {})
    edit_intent = intent.get("intent", "")

    print(f"[EditExecutor] Video recompose — intent={edit_intent}")

    # Apply subtitle toggle
    if "enable_subtitles" in params:
        state["enable_subtitles"] = params["enable_subtitles"]
        print(f"  Subtitles: {params['enable_subtitles']}")

    # Apply speed factor to task graph
    if "speed_factor" in params:
        factor = params["speed_factor"]
        scope  = intent.get("scope", "all")
        for task in state.get("task_graph", []):
            if scope == "all" or scope == "all_scenes":
                task["_speed_factor"] = factor
            elif scope.startswith("scene:"):
                target_sid = int(scope.split(":")[1])
                if task["scene_id"] == target_sid:
                    task["_speed_factor"] = factor

    # Re-run compositor
    try:
        new_state = compositor_agent(state)
        state.update(new_state)
    except Exception as e:
        print(f"[EditExecutor] Compositor error: {e}")
        state["_edit_error"] = str(e)

    return state


def _execute_script_edit(intent: dict, state: dict) -> dict:
    """Re-run Phase 1 with modified prompt and cascade all phases."""
    params = intent.get("parameters", {})
    scope  = intent.get("scope", "all")
    edit_intent = intent.get("intent", "")

    print(f"[EditExecutor] Script edit — intent={edit_intent}")

    if edit_intent == "change_dialogue" and scope.startswith("character:"):
        # Targeted dialogue change — modify the script directly
        char_name = scope.split(":", 1)[1].strip()
        new_text  = params.get("new_text", "")
        if new_text:
            script = state.get("script", {})
            for scene in script.get("scenes", []):
                for dlg in scene.get("dialogue", []):
                    if dlg.get("speaker", "").lower() == char_name.lower():
                        dlg["line"] = new_text
            state["script"] = script
    else:
        # Full script regeneration
        seed = params.get("seed_changes", state.get("user_input", ""))
        if seed:
            state["user_input"]    = seed
            state["hitl_feedback"] = params.get("feedback", "")
            state["status"]        = "processing"
            state["script"]        = {}

            try:
                from agents.scriptwriter import scriptwriter_agent
                from agents.validator    import validator_agent
                from agents.character    import character_agent

                state["input_mode"] = "auto"
                state = scriptwriter_agent(state)
                state = validator_agent(state)
                state = character_agent(state)
            except Exception as e:
                print(f"[EditExecutor] Script re-gen error: {e}")
                state["_edit_error"] = str(e)

    return state


# ── Main dispatcher ───────────────────────────────────────────────────────────

_TARGET_HANDLERS: dict[str, Callable] = {
    "audio":       _execute_audio_edit,
    "video_frame": _execute_video_frame_edit,
    "video":       _execute_video_edit,
    "script":      _execute_script_edit,
}


def execute_edit(intent: dict, state: dict) -> dict:
    """
    Route a classified intent to the correct executor,
    then save a versioned snapshot of the result.

    Returns the updated state dict (with snapshot_id injected).
    """
    target   = intent.get("target", "video")
    handler  = _TARGET_HANDLERS.get(target, _execute_video_edit)
    query    = intent.get("raw_query", "")
    label    = f"Edit: {intent.get('intent', 'unknown')} — {query[:50]}"

    print(f"\n[EditExecutor] ▶ Executing {intent.get('intent')} → {target}")
    print(f"  Scope:  {intent.get('scope')}")
    print(f"  Params: {intent.get('parameters')}\n")

    # Execute the edit
    updated_state = handler(intent, dict(state))

    # Snapshot after edit
    assets      = _collect_all_assets()
    manager     = get_state_manager()
    snapshot_id = manager.snapshot(
        state      = updated_state,
        label      = label,
        asset_paths= assets,
        edit_query = query,
        intent     = intent.get("intent", ""),
        target     = target,
    )
    updated_state["_last_snapshot_id"] = snapshot_id

    print(f"[EditExecutor] ✅ Edit complete — snapshot v{snapshot_id}")
    return updated_state