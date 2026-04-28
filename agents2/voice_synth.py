# agents2/voice_synth.py
"""
Voice Synthesis Agent
─────────────────────
Role   : Generates emotion-aware speech for every scene's dialogue.
         Processes all scene tasks from the task graph in parallel-safe fashion.
Outputs: state["audio_results"] — [{scene_id, audio_path, duration}]
MCP    : voice_cloning_synthesizer, commit_memory
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from mcp.registry2 import registry2

OUTPUT_DIR = "outputs/audio"


def _process_single_scene(task: dict, synth_tool, commit_tool) -> dict:
    """Worker: synthesise audio for one scene task."""
    scene_id   = task["scene_id"]
    dialogue   = task["dialogue"]
    char_meta  = task.get("char_meta", [])

    try:
        result = synth_tool({
            "scene_id":   scene_id,
            "dialogue":   dialogue,
            "characters": char_meta,
            "output_dir": OUTPUT_DIR
        })

        commit_tool({
            "text": json.dumps({
                "scene_id":   scene_id,
                "audio_path": result["audio_path"],
                "duration":   result["duration"]
            }),
            "metadata": {"type": "audio", "scene_id": str(scene_id), "phase": "2"}
        })

        return {
            "scene_id":   scene_id,
            "audio_path": result["audio_path"],
            "duration":   result["duration"],
            "method":     result.get("method", "unknown"),
            "line_wavs":  result.get("line_wavs", []),   # ← ADD THIS
            "status":     "done"
        }

    except Exception as e:
        print(f"  ❌ Voice synth failed for scene {scene_id}: {e}")
        return {
            "scene_id": scene_id,
            "status":   "error",
            "error":    str(e)
        }


def voice_synth_agent(state: dict) -> dict:
    print("\n[Voice Synthesis] Starting parallel audio generation…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    synth_tool  = registry2.get_tool("voice_cloning_synthesizer")
    commit_tool = registry2.get_tool("commit_memory")
    task_graph  = state.get("task_graph", [])

    if not task_graph:
        print("  ⚠ No tasks in task graph — skipping voice synthesis")
        state["audio_results"] = []
        return state

    audio_results = []

    # Parallel execution — each scene is independent
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

    # Sort by scene_id for deterministic downstream ordering
    audio_results.sort(key=lambda r: r["scene_id"])

    # Update task graph status
    audio_map = {r["scene_id"]: r for r in audio_results}
    for task in state["task_graph"]:
        ar = audio_map.get(task["scene_id"], {})
        if ar.get("status") == "done":
            task["audio_path"] = ar["audio_path"]
            task["status"]     = "audio_done"
        else:
            task["status"] = "error"
            task["error"]  = ar.get("error", "unknown")

    state["audio_results"] = audio_results
    done = sum(1 for r in audio_results if r["status"] == "done")
    print(f"[Voice Synthesis] ✅ {done}/{len(task_graph)} scenes synthesised.\n")
    return {
    "audio_results": audio_results
    }