# utils/json_utils2.py
"""
Phase 2 output utilities
Saves task graph logs and final manifests.
"""
import json
import os
import time


def save_outputs_p2(state: dict):
    os.makedirs("outputs", exist_ok=True)
    os.makedirs("outputs/logs", exist_ok=True)
    os.makedirs("outputs/raw_scenes", exist_ok=True)

    # ── Task graph execution log ──────────────────────────────────────────────
    task_log = {
        "phase":         2,
        "timestamp":     time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_scenes":  len(state.get("task_graph", [])),
        "task_graph":    state.get("task_graph", []),
        "audio_results": state.get("audio_results", []),
        "video_results": state.get("video_results", []),
        "swapped_results": state.get("swapped_results", []),
        "synced_results":  state.get("synced_results", []),
        "final_videos":  state.get("final_videos", []),
        "audio_tracks":  state.get("audio_tracks", []),
    }
    log_path = "outputs/logs/phase2_task_log.json"
    with open(log_path, "w") as f:
        json.dump(task_log, f, indent=2, default=str)
    print(f"[Output] Task log saved → {log_path}")

    # ── Phase 2 manifest ──────────────────────────────────────────────────────
    manifest = {
        "phase":        2,
        "final_videos": state.get("final_videos", []),
        "audio_tracks": state.get("audio_tracks", []),
        "scenes": [
            {
                "scene_id":    t["scene_id"],
                "location":    t["location"],
                "status":      t["status"],
                "audio_path":  t.get("audio_path"),
                "video_path":  t.get("video_path"),
                "swapped_video_path": t.get("swapped_video_path"),
                "synced_video_path":  t.get("synced_video_path"),
            }
            for t in state.get("task_graph", [])
        ]
    }
    manifest_path = "outputs/phase2_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"[Output] Phase 2 manifest saved → {manifest_path}")