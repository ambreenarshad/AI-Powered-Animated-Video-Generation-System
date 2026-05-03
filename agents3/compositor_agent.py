# agents3/compositor_agent.py
"""
Compositor Agent
─────────────────
Concatenates all merged scene clips into the final MP4.

Audio preservation:
  Subtitles are already burned into each character's synced clip by
  av_sync_agent, so this stage does NOT add any subtitle processing.

  Scene clips are joined with FFmpeg's concat demuxer using "-c copy"
  (stream copy) so no re-encoding occurs and no audio sync is disturbed.

  MoviePy is NOT used here — it re-encodes every stream and would break
  the audio sync that av_sync_agent carefully constructed.
"""

import os
import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Any

FINAL_DIR = Path("outputs/video")
FINAL_DIR.mkdir(parents=True, exist_ok=True)

FINAL_OUTPUT = str(FINAL_DIR / "final_output.mp4")


# ── FFprobe helper ────────────────────────────────────────────────────────────

def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True, timeout=30,
        )
        val = r.stdout.strip()
        return float(val) if val else 0.0
    except Exception:
        return 0.0


# ── Stream-copy concat ────────────────────────────────────────────────────────

def _stream_copy_concat(clip_paths: list[str], out_path: str) -> bool:
    """
    Concatenate scene clips with no re-encoding.
    All audio sync already embedded; just mux into one container.
    """
    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], out_path)
        return True

    tmp_list = str(FINAL_DIR / "_scene_list.txt")
    with open(tmp_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f",    "concat",
        "-safe", "0",
        "-i",    tmp_list,
        "-c",    "copy",          # stream copy — no re-encode
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=600)

    try:
        os.remove(tmp_list)
    except OSError:
        pass

    if result.returncode != 0:
        print(f"  ❌ Stream-copy concat failed:\n{result.stderr.decode()[-400:]}")
        return False
    return True


# ── Agent ─────────────────────────────────────────────────────────────────────

def compositor_agent(state: dict) -> dict:
    print("[Phase 3 · Compositor Agent] Compositing final video (stream copy, no re-encode)…")

    task_graph: List[Dict[str, Any]] = state["task_graph"]

    # ── Collect merged scene clips in scene_id order ──────────────────────────
    clip_paths: list[str] = []
    for task in sorted(task_graph, key=lambda t: t["scene_id"]):
        # merged_clip is set by scene_merge_agent; synced_clip is a legacy fallback
        clip_path = task.get("merged_clip") or task.get("synced_clip")
        if clip_path and os.path.exists(clip_path):
            clip_paths.append(clip_path)
            dur = _probe_duration(clip_path)
            print(f"  ← Scene {task['scene_id']}: {os.path.basename(clip_path)}  [{dur:.1f}s]")
        else:
            print(f"  ⚠️  Scene {task['scene_id']}: no merged/synced clip found — skipping.")

    if not clip_paths:
        return {**state, "status": "error",
                "error": "No scene clips available for compositing."}

    # ── Concatenate with stream copy ──────────────────────────────────────────
    print(f"  Concatenating {len(clip_paths)} scene clip(s) → {FINAL_OUTPUT}")
    success = _stream_copy_concat(clip_paths, FINAL_OUTPUT)

    if not success or not os.path.exists(FINAL_OUTPUT):
        return {**state, "status": "error",
                "error": "Final concat failed — see log above."}

    final_sz  = os.path.getsize(FINAL_OUTPUT) // (1024 * 1024)
    final_dur = _probe_duration(FINAL_OUTPUT)
    print(f"  ✅ Final video: {FINAL_OUTPUT}  [{final_dur:.1f}s, {final_sz} MB]")

    # ── Save task log ─────────────────────────────────────────────────────────
    log_path = "outputs/logs/phase3_task_log.json"
    os.makedirs("outputs/logs", exist_ok=True)
    with open(log_path, "w") as f:
        json.dump([
            {
                "scene_id":    t["scene_id"],
                "status":      t["status"],
                "merged_clip": t.get("merged_clip"),
                "synced_clip": t.get("synced_clip"),
                "error":       t.get("error"),
                "character_subtitles": [
                    {
                        "character": c.get("character_name"),
                        "subtitle_path": c.get("subtitle_path"),
                    }
                    for c in t.get("character_clips", [])
                ],
            }
            for t in task_graph
        ], f, indent=2)

    print(f"[Phase 3 · Compositor Agent] ✅ Final video: {FINAL_OUTPUT}")
    return {
        **state,
        "final_output":  FINAL_OUTPUT,
        "subtitle_file": None,   # subtitles are burned per-character, not a separate file
        "status":        "complete",
        "task_log":      state.get("task_log", []) + [{"phase3_log": log_path}],
    }