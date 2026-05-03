# agents3/animator_agent.py
"""
Animator Agent  —  Ken Burns Zoom/Pan via MoviePy
───────────────────────────────────────────────────
Applies subtle zoom and pan motion to each WAN-generated video clip
to add cinematic life (Ken Burns effect).

Uses MoviePy's fx pipeline — no external process spawning needed.
"""

import os
import random
from pathlib import Path
from typing import List, Dict, Any

from moviepy.editor import VideoFileClip
from moviepy.video.fx.resize import resize as mpy_resize

ANIMATED_DIR = Path("outputs/video/animated")
ANIMATED_DIR.mkdir(parents=True, exist_ok=True)

# Ken Burns config
ZOOM_RANGE  = (1.0, 1.12)   # start / end zoom (12 % max zoom-in)
PAN_RANGE   = 0.04           # max fractional pan (4 % of frame)


# ---------------------------------------------------------------------------
# Ken Burns effect
# ---------------------------------------------------------------------------

def _make_zoom_filter(clip_duration: float):
    """
    Returns a function clip.fl_image(fn) can use.
    Applies a time-varying scale + translate to simulate Ken Burns.
    """
    zoom_start, zoom_end = random.choice([
        (1.0,   1.10),   # slow zoom-in
        (1.10,  1.0),    # slow zoom-out
        (1.05,  1.05),   # static zoom (just pan)
    ])

    # Random pan direction
    pan_x = random.uniform(-PAN_RANGE, PAN_RANGE)
    pan_y = random.uniform(-PAN_RANGE, PAN_RANGE)

    def make_frame_filter(get_frame, t):
        import numpy as np
        frame = get_frame(t)
        h, w  = frame.shape[:2]
        frac  = t / max(clip_duration, 0.001)

        # Current zoom
        zoom = zoom_start + (zoom_end - zoom_start) * frac
        new_w = int(w * zoom)
        new_h = int(h * zoom)

        # Resize frame
        from PIL import Image
        img    = Image.fromarray(frame)
        img    = img.resize((new_w, new_h), Image.LANCZOS)
        arr    = __import__("numpy").array(img)

        # Crop back to original size with pan offset
        ox = int((new_w - w) / 2 + pan_x * w * frac)
        oy = int((new_h - h) / 2 + pan_y * h * frac)
        ox = max(0, min(ox, new_w - w))
        oy = max(0, min(oy, new_h - h))

        return arr[oy:oy+h, ox:ox+w]

    return make_frame_filter


def _apply_ken_burns(input_path: str, output_path: str, duration: float) -> str:
    clip = VideoFileClip(input_path)

    # Trim/extend to match desired duration (WAN clips are close but may differ)
    if clip.duration > duration + 0.5:
        clip = clip.subclip(0, duration)

    animated = clip.fl(_make_zoom_filter(clip.duration), apply_to=["video"])

    animated.write_videofile(
        output_path,
        codec="libx264",
        audio=False,            # audio added in av_sync step
        fps=24,
        preset="fast",
        logger=None,
    )
    clip.close()
    animated.close()
    return output_path


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

def animator_agent(state: dict) -> dict:
    print("[Phase 3 · Animator Agent] Applying Ken Burns effects…")

    task_graph: List[Dict[str, Any]] = state["task_graph"]
    animated_results = []

    for task in task_graph:
        sid = task["scene_id"]
        if task["status"] == "error":
            animated_results.append({"scene_id": sid, "status": "skipped"})
            continue

        raw_clips = task.get("raw_frames", [])
        if not raw_clips:
            task["status"] = "error"
            task["error"]  = "No raw video from visual agent"
            animated_results.append({"scene_id": sid, "status": "error",
                                     "error": task["error"]})
            continue

        raw_path = raw_clips[0]
        out_path = str(ANIMATED_DIR / f"scene_{sid:02d}_animated.mp4")

        try:
            result = _apply_ken_burns(raw_path, out_path, task["duration_sec"])
            task["animated_clip"] = result
            task["status"]        = "animated"
            print(f"  ✅ Scene {sid}: Ken Burns applied → {out_path}")
            animated_results.append({"scene_id": sid, "clip_path": result,
                                     "status": "done"})
        except Exception as e:
            print(f"  ❌ Scene {sid}: animation failed: {e}")
            # Fallback: use raw clip without Ken Burns
            task["animated_clip"] = raw_path
            task["status"]        = "animated"
            animated_results.append({"scene_id": sid, "clip_path": raw_path,
                                     "status": "fallback", "error": str(e)})

    print(f"[Phase 3 · Animator Agent] ✅ Animation pass complete.")
    return {**state, "task_graph": task_graph, "animated_results": animated_results}