"""
agents3/scene_merge_agent.py
─────────────────────────────
Merges all per-character synced clips for each scene into a single scene video.

Strategy per scene:
  • 1 character  → copy that clip directly (no re-encode needed)
  • 2+ characters → concatenate clips in dialogue order

IMPORTANT — Audio preservation:
  All clips arriving here already have their audio correctly synced by
  av_sync_agent. This stage does NOT touch or re-encode audio in any way.
  It uses FFmpeg's concat demuxer with "-c copy" so every stream is passed
  through bit-for-bit. No xfade/acrossfade filters are applied because those
  require re-encoding and can break the existing sync.

Clip resolution priority per character:
  1. clip["synced_path"]    — audio-attached clip in outputs/video/synced/
  2. clip["raw_video_path"] — original clip from outputs/clips/

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


# ── Best clip path for a character clip dict ──────────────────────────────────

def _best_clip_path(clip: dict) -> str | None:
    """
    Return the best available video path for this character clip.
    Preference: synced_path > raw_video_path.
    Returns None if neither exists on disk.
    """
    for key in ("synced_path", "raw_video_path"):
        p = clip.get(key, "")
        if p and os.path.exists(p):
            return p
    return None


# ── Clip ordering + deduplication ─────────────────────────────────────────────

def _dialogue_ordered_clips(task: dict) -> list[str]:
    """
    Return one clip path per *unique* character, ordered by each character's
    first dialogue start_ms so the video follows the actual conversation flow.
    """
    char_clips = task.get("character_clips", [])

    def _first_start(clip: dict) -> int:
        lines = clip.get("dialogue_lines", [])
        if lines:
            return min(l.get("start_ms", 999_999_999) for l in lines)
        return 999_999_999

    seen_names: set[str] = set()
    unique_valid: list[dict] = []
    for clip in char_clips:
        name = clip.get("character_name", "")
        if name in seen_names:
            continue
        path = _best_clip_path(clip)
        if path:
            seen_names.add(name)
            unique_valid.append(clip)

    ordered = sorted(unique_valid, key=_first_start)
    paths = [_best_clip_path(c) for c in ordered]
    return [p for p in paths if p]


# ── Stream-copy concat (no re-encode, audio preserved exactly) ───────────────

def _stream_copy_concat(clip_paths: list[str], out_path: Path) -> bool:
    """
    Concatenate clips using FFmpeg's concat demuxer with stream copy.
    This is a pure mux operation — no audio or video re-encoding occurs,
    so the sync already baked in by av_sync_agent is preserved perfectly.

    Requirement: all clips must have the same codec, resolution, and frame rate.
    av_sync_agent outputs libx264/aac at 1280x720 so this is always satisfied.
    """
    if len(clip_paths) == 1:
        shutil.copy(clip_paths[0], out_path)
        return True

    list_file = out_path.parent / f"_concat_{out_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in clip_paths:
            # Use absolute paths to be safe with FFmpeg's safe=0
            f.write(f"file '{os.path.abspath(p)}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f",    "concat",
        "-safe", "0",
        "-i",    str(list_file),
        # Stream copy — do NOT re-encode anything
        "-c",    "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)

    try:
        list_file.unlink()
    except OSError:
        pass

    if r.returncode != 0:
        print(f"    ❌ Stream-copy concat failed:\n{r.stderr.decode()[-300:]}")
        return False
    return True


# ── Agent ─────────────────────────────────────────────────────────────────────

def scene_merge_agent(state: "Phase3State") -> "Phase3State":
    print("\n[Phase3][SceneMerge] Merging character clips into scene videos (stream copy)…")

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

        # Gather deduplicated, dialogue-ordered clip paths
        clip_paths = _dialogue_ordered_clips(task)

        if not clip_paths:
            print(f"  ⚠  Scene {sid}: no valid clips available")
            task["status"] = "error"
            task["error"]  = "No valid character clips found"
            err_count += 1
            continue

        # Log which clips are being merged and their audio source
        char_labels = []
        seen_for_log: set[str] = set()
        for clip in task.get("character_clips", []):
            name = clip.get("character_name", "")
            if name in seen_for_log:
                continue
            p = _best_clip_path(clip)
            if p:
                src = "synced" if (
                    clip.get("synced_path") and os.path.exists(clip["synced_path"])
                ) else "raw"
                char_labels.append(f"{name}({src})")
                seen_for_log.add(name)

        print(f"  [Scene {sid}] Stream-copy concat of {len(clip_paths)} clip(s): "
              + ", ".join(char_labels))

        try:
            success = _stream_copy_concat(clip_paths, out_path)

            if success and out_path.exists() and out_path.stat().st_size > 1_000:
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
            # Last resort: copy the first available clip unchanged
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