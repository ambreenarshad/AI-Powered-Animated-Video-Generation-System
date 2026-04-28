# utils/json_utils2.py
"""
Phase 2 output utilities
Saves task graph logs, timing manifest, and phase manifest.
"""
import json
import os
import time


def save_outputs_p2(state: dict):
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("outputs/logs", exist_ok=True)
    os.makedirs("outputs/audio", exist_ok=True)

    # ── timing_manifest.json ──────────────────────────────────────────────────
    timing_manifest = state.get("timing_manifest", [])
    timing_path = "outputs/timing_manifest.json"
    with open(timing_path, "w") as f:
        json.dump(timing_manifest, f, indent=2, default=str)
    print(f"[Output] Timing manifest saved → {timing_path}  "
          f"({len(timing_manifest)} lines)")

    # ── Task graph execution log ──────────────────────────────────────────────
    task_log = {
        "phase":         2,
        "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_scenes":  len(state.get("task_graph", [])),
        "task_graph":    state.get("task_graph", []),
        "audio_results": state.get("audio_results", []),
        "audio_tracks":  state.get("audio_tracks",  []),
    }
    log_path = "outputs/logs/phase2_task_log.json"
    with open(log_path, "w") as f:
        json.dump(task_log, f, indent=2, default=str)
    print(f"[Output] Task log saved → {log_path}")

    # ── Phase 2 manifest ──────────────────────────────────────────────────────
    manifest = {
        "phase":        2,
        "audio_tracks": state.get("audio_tracks", []),
        "scenes": [
            {
                "scene_id":   t["scene_id"],
                "location":   t["location"],
                "status":     t["status"],
                "audio_path": t.get("audio_path"),
            }
            for t in state.get("task_graph", [])
        ],
    }
    manifest_path = "outputs/phase2_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"[Output] Phase 2 manifest saved → {manifest_path}")