"""
agents3/scene_merge_agent.py
─────────────────────────────
Merges all per-character synced clips for each scene into a single scene video.

Strategy per scene:
  • 1 character  → copy that clip directly (no composite needed)
  • 2+ characters → interleave clips in dialogue order with 0.25s cross-dissolves

The merged clip contains audio from all characters in their correct time slots.
Output: outputs/video/scenes/scene_XX_merged.mp4
"""

from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

SCENES_DIR = Path("outputs/video/scenes")
SCENES_DIR.mkdir(parents=True, exist_ok=True)

CROSSFADE_DUR = 0.25   # seconds of cross-dissolve between character shots


# ── FFprobe helper ────────────────────────────────────────────────────────────

def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True, timeout=20,
        )
        val = r.stdout.strip()
        return max(float(val), 0.1) if val else 5.0
    except Exception:
        return 5.0


# ── Clip ordering ─────────────────────────────────────────────────────────────

def _dialogue_ordered_clips(task: dict) -> list[str]:
    """
    Return synced clip paths ordered by each character's first dialogue
    start_ms so the video follows the actual conversation flow.
    """
    char_clips = task.get("character_clips", [])

    def _first_start(clip: dict) -> int:
        lines = clip.get("dialogue_lines", [])
        if lines:
            return min(l.get("start_ms", 999_999_999) for l in lines)
        return 999_999_999

    valid_clips = [
        c for c in char_clips
        if c.get("synced_path") and os.path.exists(c.get("synced_path", ""))
    ]
    ordered = sorted(valid_clips, key=_first_start)
    return [c["synced_path"] for c in ordered]


# ── Simple concat (no transitions) ───────────────────────────────────────────

def _simple_concat(clip_paths: list[str], out_path: Path) -> bool:
    list_file = out_path.parent / f"_concat_{out_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    try:
        list_file.unlink()
    except OSError:
        pass
    if r.returncode != 0:
        print(f"    ❌ Simple concat failed: {r.stderr.decode()[-200:]}")
        return False
    return True


# ── Xfade concat (with cross-dissolve) ───────────────────────────────────────

def _xfade_concat(clip_paths: list[str], out_path: Path) -> bool:
    """Concatenate clips with xfade cross-dissolve between each pair."""
    n = len(clip_paths)

    if n == 0:
        return False
    if n == 1:
        shutil.copy(clip_paths[0], out_path)
        return True

    durations = [_probe_duration(p) for p in clip_paths]
    td = CROSSFADE_DUR

    # Build FFmpeg input args
    inputs: list[str] = []
    for p in clip_paths:
        inputs += ["-i", p]

    # Build filter_complex chain
    fc_parts: list[str] = []
    prev_v = "[0:v]"
    prev_a = "[0:a]"

    for i in range(1, n):
        offset = max(sum(durations[:i]) - td * i, 0.01)
        out_v  = f"[xv{i}]"
        out_a  = f"[xa{i}]"
        fc_parts.append(
            f"{prev_v}[{i}:v]xfade=transition=fade:"
            f"duration={td:.3f}:offset={offset:.3f}{out_v}"
        )
        fc_parts.append(
            f"{prev_a}[{i}:a]acrossfade=d={td:.3f}{out_a}"
        )
        prev_v = out_v
        prev_a = out_a

    fc = ";".join(fc_parts)
    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", fc,
            "-map", prev_v,
            "-map", prev_a,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )

    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        print(f"    ⚠  xfade concat failed — trying simple concat")
        print(f"    stderr: {r.stderr.decode()[-200:]}")
        return _simple_concat(clip_paths, out_path)
    return True


# ── Agent ─────────────────────────────────────────────────────────────────────

def scene_merge_agent(state: "Phase3State") -> "Phase3State":
    print("\n[Phase3][SceneMerge] Merging character clips into scene videos…")

    task_graph = state["task_graph"]
    ok_count   = 0
    err_count  = 0

    for task in task_graph:
        sid      = task["scene_id"]
        out_path = SCENES_DIR / f"scene_{sid:02d}_merged.mp4"

        # Skip if already done
        if out_path.exists() and out_path.stat().st_size > 5_000:
            print(f"  ⏭  Scene {sid}: merged clip exists — skipping")
            task["merged_clip"] = str(out_path)
            if task["status"] != "error":
                task["status"] = "merged"
            ok_count += 1
            continue

        # Gather synced clips ordered by dialogue timing
        clip_paths = _dialogue_ordered_clips(task)

        if not clip_paths:
            print(f"  ⚠  Scene {sid}: no synced clips available")
            task["status"] = "error"
            task["error"]  = "No synced character clips found"
            err_count += 1
            continue

        char_names = [Path(p).stem.split("_synced")[0] for p in clip_paths]
        print(f"  [Scene {sid}] Merging {len(clip_paths)} clip(s): "
              + ", ".join(char_names))

        try:
            success = _xfade_concat(clip_paths, out_path)

            if success and out_path.exists() and out_path.stat().st_size > 1000:
                task["merged_clip"] = str(out_path)
                task["status"]      = "merged"
                dur = _probe_duration(str(out_path))
                sz  = out_path.stat().st_size // 1024
                print(f"  ✅ Scene {sid} → {out_path.name} [{dur:.1f}s, {sz} KB]")
                ok_count += 1
            else:
                raise RuntimeError("FFmpeg produced no valid output")

        except Exception as exc:
            print(f"  ❌ Scene {sid} merge failed: {exc}")
            # Last resort: copy the first available clip
            if clip_paths:
                shutil.copy(clip_paths[0], out_path)
                task["merged_clip"] = str(out_path)
                task["status"]      = "merged"
                task["error"]       = f"fallback single clip: {exc}"
                print(f"  ⚠  Scene {sid}: using first character clip as fallback")
                ok_count += 1
            else:
                task["status"] = "error"
                task["error"]  = str(exc)
                err_count += 1

    total = ok_count + err_count
    print(f"\n[Phase3][SceneMerge] ✅ {ok_count}/{total} scenes merged.\n")
    return {**state, "task_graph": task_graph}