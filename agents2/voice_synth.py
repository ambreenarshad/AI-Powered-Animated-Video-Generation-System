# agents2/voice_synth.py
"""
Voice Synthesis Agent
─────────────────────
Role   : Generates emotion-aware speech for every scene's dialogue.
         Processes all scene tasks in parallel.
Outputs:
  state["audio_results"]   — [{scene_id, audio_path, duration, line_wavs, line_timing}]
  state["audio_tracks"]    — flat list of scene WAV paths
  state["timing_manifest"] — [{scene_id, audio_file, start_ms, end_ms}]  (per line)
MCP    : voice_cloning_synthesizer, commit_memory
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from mcp.registry2 import registry2

OUTPUT_DIR = "outputs/audio"


def _process_single_scene(task: dict, synth_tool, commit_tool) -> dict:
    """Worker: synthesise audio for one scene task."""
    scene_id  = task["scene_id"]
    dialogue  = task["dialogue"]
    char_meta = task.get("char_meta", [])

    try:
        result = synth_tool({
            "scene_id":   scene_id,
            "dialogue":   dialogue,
            "characters": char_meta,
            "output_dir": OUTPUT_DIR,
        })

        commit_tool({
            "text": json.dumps({
                "scene_id":   scene_id,
                "audio_path": result["audio_path"],
                "duration":   result["duration"],
            }),
            "metadata": {"type": "audio", "scene_id": str(scene_id), "phase": "2"},
        })

        return {
            "scene_id":    scene_id,
            "audio_path":  result["audio_path"],
            "duration":    result["duration"],
            "method":      result.get("method", "unknown"),
            "line_wavs":   result.get("line_wavs",   []),
            "line_timing": result.get("line_timing",  []),
            "status":      "done",
        }

    except Exception as e:
        print(f"  ❌ Voice synth failed for scene {scene_id}: {e}")
        return {"scene_id": scene_id, "status": "error", "error": str(e)}


def voice_synth_agent(state: dict) -> dict:
    print("\n[Voice Synthesis] Starting parallel audio generation…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    synth_tool  = registry2.get_tool("voice_cloning_synthesizer")
    commit_tool = registry2.get_tool("commit_memory")
    task_graph  = state.get("task_graph", [])

    if not task_graph:
        print("  ⚠ No tasks in task graph — skipping voice synthesis")
        state["audio_results"]   = []
        state["audio_tracks"]    = []
        state["timing_manifest"] = []
        return state

    audio_results = []

    with ThreadPoolExecutor(max_workers=min(4, len(task_graph))) as executor:
        futures = {
            executor.submit(_process_single_scene, task, synth_tool, commit_tool): task["scene_id"]
            for task in task_graph
        }
        for future in as_completed(futures):
            result = future.result()
            audio_results.append(result)
            sid = result["scene_id"]
            if result["status"] == "done":
                print(f"  ✅ Scene {sid} audio ready → {result['audio_path']}")
            else:
                print(f"  ❌ Scene {sid} audio FAILED: {result.get('error')}")

    audio_results.sort(key=lambda r: r["scene_id"])

    # ── Update task graph status ──────────────────────────────────────────────
    audio_map = {r["scene_id"]: r for r in audio_results}
    for task in state["task_graph"]:
        ar = audio_map.get(task["scene_id"], {})
        if ar.get("status") == "done":
            task["audio_path"] = ar["audio_path"]
            task["line_wavs"]  = ar["line_wavs"]
            task["status"]     = "audio_done"
        else:
            task["status"] = "error"
            task["error"]  = ar.get("error", "unknown")

    # ── Build flat timing manifest (all scenes, all lines) ───────────────────
    timing_manifest = []
    for ar in audio_results:
        if ar["status"] != "done":
            continue
        scene_id = ar["scene_id"]
        for entry in ar.get("line_timing", []):
            timing_manifest.append({
                "scene_id":   scene_id,
                "speaker":    entry["speaker"],
                "line":       entry["line"],
                "audio_file": entry["audio_file"],
                "start_ms":   entry["start_ms"],
                "end_ms":     entry["end_ms"],
            })

    audio_tracks = [r["audio_path"] for r in audio_results if r["status"] == "done"]

    state["audio_results"]   = audio_results
    state["audio_tracks"]    = audio_tracks
    state["timing_manifest"] = timing_manifest

    done = sum(1 for r in audio_results if r["status"] == "done")
    print(f"[Voice Synthesis] ✅ {done}/{len(task_graph)} scenes synthesised.\n")
    return {
        "audio_results":   audio_results,
        "audio_tracks":    audio_tracks,
        "timing_manifest": timing_manifest,
    }