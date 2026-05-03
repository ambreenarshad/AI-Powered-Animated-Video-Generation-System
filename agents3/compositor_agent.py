# agents3/compositor_agent.py
"""
Compositor Agent
─────────────────
Concatenates all synced scene clips with cross-dissolve transitions,
optionally overlays subtitles (.srt), and writes the final MP4.

Transition: cross-dissolve via MoviePy's CompositeVideoClip + fade masks.
Subtitles:  burned-in via FFmpeg (ImageMagick not required).
"""

import os
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

from moviepy.editor import (
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
)
from moviepy.video.fx.fadein  import fadein
from moviepy.video.fx.fadeout import fadeout

FINAL_DIR = Path("outputs/video")
FINAL_DIR.mkdir(parents=True, exist_ok=True)

FINAL_OUTPUT  = str(FINAL_DIR / "final_output.mp4")
SUBTITLE_FILE = str(FINAL_DIR / "subtitles.srt")
TRANSITION_DURATION = 0.5  # seconds of cross-dissolve overlap


# ---------------------------------------------------------------------------
# Subtitle helpers
# ---------------------------------------------------------------------------

def _ms_to_srt_time(ms: int) -> str:
    h   = ms // 3_600_000;  ms %= 3_600_000
    m   = ms // 60_000;     ms %= 60_000
    s   = ms // 1_000;      ms %= 1_000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(task_graph: List[Dict]) -> str:
    lines = []
    idx   = 1
    # Running timeline offset (because we concatenate clips)
    offset_ms = 0

    for task in task_graph:
        if task["status"] == "error":
            offset_ms += int(task["duration_sec"] * 1000)
            continue

        for dlg in task.get("dialogue", []):
            speaker = dlg.get("speaker", "")
            line    = dlg.get("line", "").strip()
            if not line:
                continue

            # Rough equal distribution of dialogue within the scene
            scene_dur_ms = int(task["duration_sec"] * 1000)
            n_lines      = max(len(task.get("dialogue", [])), 1)
            slot         = scene_dur_ms // n_lines
            di           = task["dialogue"].index(dlg)
            start_ms     = offset_ms + di * slot
            end_ms       = start_ms + max(slot - 200, 500)

            lines.append(str(idx))
            lines.append(f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}")
            lines.append(f"{speaker}: {line}")
            lines.append("")
            idx += 1

        offset_ms += int(task["duration_sec"] * 1000)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Transition helper
# ---------------------------------------------------------------------------

def _crossfade_concat(clips: List[VideoFileClip], td: float) -> VideoFileClip:
    """
    Concatenate clips with cross-dissolve transitions.
    Each clip (except last) fades out in its last `td` seconds,
    and the next clip fades in during its first `td` seconds.
    """
    if len(clips) == 1:
        return clips[0]

    result = clips[0]
    for next_clip in clips[1:]:
        result = concatenate_videoclips(
            [result.fx(fadeout, td), next_clip.fx(fadein, td)],
            method="compose",
            padding=-td,   # overlap by td seconds
        )
    return result


# ---------------------------------------------------------------------------
# FFmpeg subtitle burn-in
# ---------------------------------------------------------------------------

def _burn_subtitles(input_mp4: str, srt_path: str, output_mp4: str) -> str:
    """Use FFmpeg to burn .srt subtitles into the video."""
    # Escape path for FFmpeg filter
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_mp4,
        "-vf", f"subtitles='{srt_escaped}':force_style='FontSize=18,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2'",
        "-c:a", "copy",
        "-preset", "fast",
        output_mp4,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg subtitle burn failed:\n{result.stderr}")
    return output_mp4


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def compositor_agent(state: dict) -> dict:
    print("[Phase 3 · Compositor Agent] Compositing final video…")

    task_graph: List[Dict[str, Any]] = state["task_graph"]
    enable_subtitles: bool           = state.get("enable_subtitles", True)

    # ── Collect synced clips in order ─────────────────────────────────────
    clips: List[VideoFileClip] = []
    for task in sorted(task_graph, key=lambda t: t["scene_id"]):
        if task.get("synced_clip") and os.path.exists(task["synced_clip"]):
            clip = VideoFileClip(task["synced_clip"])
            clips.append(clip)
            print(f"  ← Scene {task['scene_id']}: {task['synced_clip']}")
        else:
            print(f"  ⚠️  Scene {task['scene_id']}: no synced clip, skipping.")

    if not clips:
        return {**state, "status": "error",
                "error": "No synced clips available for compositing."}

    # ── Concatenate with cross-dissolve ───────────────────────────────────
    print("  Applying cross-dissolve transitions…")
    final_clip = _crossfade_concat(clips, TRANSITION_DURATION)

    # Write intermediate (no subtitles yet)
    intermediate = str(FINAL_DIR / "_intermediate.mp4")
    final_clip.write_videofile(
        intermediate,
        codec="libx264",
        audio_codec="aac",
        fps=24,
        preset="fast",
        logger=None,
    )
    final_clip.close()
    for c in clips:
        c.close()

    # ── Subtitle burn-in ──────────────────────────────────────────────────
    output_path = FINAL_OUTPUT
    subtitle_path: Optional[str] = None

    if enable_subtitles:
        print("  Generating .srt subtitles…")
        srt_content = _build_srt(task_graph)
        with open(SUBTITLE_FILE, "w", encoding="utf-8") as f:
            f.write(srt_content)
        subtitle_path = SUBTITLE_FILE

        try:
            print("  Burning subtitles via FFmpeg…")
            output_path = _burn_subtitles(intermediate, SUBTITLE_FILE, FINAL_OUTPUT)
            os.remove(intermediate)
        except Exception as e:
            print(f"  ⚠️  Subtitle burn failed ({e}); using video without subtitles.")
            os.rename(intermediate, FINAL_OUTPUT)
    else:
        os.rename(intermediate, FINAL_OUTPUT)

    # ── Save task log ─────────────────────────────────────────────────────
    log_path = "outputs/logs/phase3_task_log.json"
    os.makedirs("outputs/logs", exist_ok=True)
    with open(log_path, "w") as f:
        json.dump([
            {
                "scene_id":      t["scene_id"],
                "status":        t["status"],
                "animated_clip": t.get("animated_clip"),
                "synced_clip":   t.get("synced_clip"),
                "error":         t.get("error"),
            }
            for t in task_graph
        ], f, indent=2)

    print(f"[Phase 3 · Compositor Agent] ✅ Final video: {output_path}")
    return {
        **state,
        "final_output":  output_path,
        "subtitle_file": subtitle_path,
        "status":        "complete",
        "task_log":      state.get("task_log", []) + [{"phase3_log": log_path}],
    }