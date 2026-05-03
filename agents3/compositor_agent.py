"""
agents3/compositor_agent.py
────────────────────────────
Final stage: concatenates all scene clips with cross-dissolve transitions,
generates a frame-accurate SRT subtitle file, burns subtitles into the MP4.

Subtitle timing is derived directly from the timing_manifest (per-line
start_ms / end_ms) and offset to match each scene's position in the
final concatenated video timeline.

Output:
  outputs/video/final_output.mp4   — final video with burned-in subtitles
  outputs/video/subtitles.srt      — standalone SRT (for external players)
  outputs/logs/phase3_task_log.json
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

FINAL_DIR       = Path("outputs/video")
FINAL_OUTPUT    = str(FINAL_DIR / "final_output.mp4")
SUBTITLE_FILE   = str(FINAL_DIR / "subtitles.srt")
TRANSITION_DUR  = 0.5   # seconds of cross-dissolve between scenes

FINAL_DIR.mkdir(parents=True, exist_ok=True)


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


# ── SRT subtitle builder ──────────────────────────────────────────────────────

def _ms_to_srt_time(ms: int) -> str:
    """Convert milliseconds to SRT timestamp HH:MM:SS,mmm."""
    ms = max(int(ms), 0)
    h,  ms = divmod(ms, 3_600_000)
    m,  ms = divmod(ms, 60_000)
    s,  ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(timing_manifest: list[dict], task_graph: list[dict]) -> str:
    """
    Build SRT content mapping each dialogue line to its absolute position
    in the final concatenated video.

    Algorithm:
    1. Compute each scene clip's actual duration from its merged_clip file
    2. Compute each scene's start offset in the final video timeline
       (accounting for cross-dissolve overlap)
    3. For each timing entry, map its scene-relative ms position to the
       absolute video timeline
    """
    if not timing_manifest:
        return ""

    # Collect merged clip durations per scene
    sorted_tasks = sorted(task_graph, key=lambda t: t["scene_id"])
    scene_dur_map: dict[int, float] = {}
    for task in sorted_tasks:
        sid  = task["scene_id"]
        clip = task.get("merged_clip")
        if clip and os.path.exists(clip):
            scene_dur_map[sid] = _probe_duration(clip)
        else:
            scene_dur_map[sid] = task.get("duration_sec", 5.0)

    # Compute video timeline offset for each scene
    # Each scene overlaps with the next by TRANSITION_DUR (cross-dissolve)
    td = TRANSITION_DUR
    sorted_sids = sorted(scene_dur_map.keys())
    video_offset_ms: dict[int, int] = {}
    acc_ms = 0
    for i, sid in enumerate(sorted_sids):
        video_offset_ms[sid] = acc_ms
        dur = scene_dur_map[sid]
        # Next scene starts at end of this scene minus the transition overlap
        acc_ms += int((dur - (td if i < len(sorted_sids) - 1 else 0)) * 1000)

    # Compute each scene's internal start time in the timing manifest
    # (the first entry's start_ms for that scene is treated as t=0 within the scene)
    scene_base_ms: dict[int, int] = {}
    for entry in timing_manifest:
        sid = entry.get("scene_id")
        if sid is None:
            continue
        s_ms = entry.get("start_ms", 0)
        if sid not in scene_base_ms or s_ms < scene_base_ms[sid]:
            scene_base_ms[sid] = s_ms

    # Build SRT entries
    srt_lines: list[str] = []
    idx = 1

    # Sort by scene then by start time within scene
    sorted_entries = sorted(
        timing_manifest,
        key=lambda e: (e.get("scene_id", 0), e.get("start_ms", 0)),
    )

    for entry in sorted_entries:
        text = entry.get("line", "").strip()
        if not text:
            continue

        sid      = entry.get("scene_id", 0)
        speaker  = entry.get("speaker", "").strip()
        start_ms = entry.get("start_ms", 0)
        end_ms   = entry.get("end_ms", start_ms + 2000)

        # Position within scene (relative to scene's first line)
        base = scene_base_ms.get(sid, 0)
        within_start = start_ms - base
        within_end   = end_ms   - base

        # Absolute position in final video
        vo           = video_offset_ms.get(sid, 0)
        abs_start_ms = vo + max(within_start, 0)
        abs_end_ms   = vo + max(within_end,   0)

        # Ensure minimum 500ms display time
        if abs_end_ms - abs_start_ms < 500:
            abs_end_ms = abs_start_ms + 500

        label = f"{speaker}: " if speaker else ""

        srt_lines.append(str(idx))
        srt_lines.append(
            f"{_ms_to_srt_time(abs_start_ms)} --> {_ms_to_srt_time(abs_end_ms)}"
        )
        srt_lines.append(f"{label}{text}")
        srt_lines.append("")
        idx += 1

    return "\n".join(srt_lines)


# ── Scene concatenation ───────────────────────────────────────────────────────

def _concat_with_xfade(scene_clips: list[str], out_path: str) -> bool:
    """
    Concatenate N clips with FFmpeg xfade cross-dissolve transitions.
    Falls back to simple concat if xfade fails.
    """
    n = len(scene_clips)
    if n == 0:
        return False
    if n == 1:
        shutil.copy(scene_clips[0], out_path)
        return True

    durations = [_probe_duration(p) for p in scene_clips]
    td = TRANSITION_DUR

    # Build input list
    inputs: list[str] = []
    for p in scene_clips:
        inputs += ["-i", p]

    # Chain xfade filters
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

    fc  = ";".join(fc_parts)
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
            out_path,
        ]
    )

    r = subprocess.run(cmd, capture_output=True, timeout=1800)
    if r.returncode != 0:
        print(f"  ⚠  xfade concat failed — falling back to simple concat")
        print(f"  FFmpeg stderr: {r.stderr.decode()[-300:]}")
        return _simple_concat(scene_clips, out_path)
    return True


def _simple_concat(clips: list[str], out_path: str) -> bool:
    """Simple FFmpeg concat demuxer (no transitions, fast)."""
    tmp = Path(out_path).parent / "_concat_list.txt"
    with open(tmp, "w") as f:
        for p in clips:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(tmp),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=1800)
    try:
        tmp.unlink()
    except OSError:
        pass
    if r.returncode != 0:
        print(f"  ❌ Simple concat also failed: {r.stderr.decode()[-300:]}")
        return False
    return True


# ── Subtitle burn-in ──────────────────────────────────────────────────────────

def _burn_subtitles(input_mp4: str, srt_path: str, output_mp4: str) -> str:
    """Burn SRT subtitles into video using FFmpeg subtitles filter."""
    # Escape path for FFmpeg filter syntax
    srt_escaped = os.path.abspath(srt_path).replace("\\", "/")
    # On Windows, also escape colons in drive letters
    if ":" in srt_escaped and not srt_escaped.startswith("/"):
        parts = srt_escaped.split(":", 1)
        srt_escaped = parts[0] + "\\:" + parts[1]

    cmd = [
        "ffmpeg", "-y",
        "-i", input_mp4,
        "-vf", (
            f"subtitles='{srt_escaped}':force_style='"
            "FontName=Arial,"
            "FontSize=22,"
            "Bold=1,"
            "PrimaryColour=&H00F0E6CC,"   # Cream white
            "OutlineColour=&H00000000,"   # Black outline
            "BackColour=&H80000000,"      # Semi-transparent black shadow
            "Outline=2,"
            "Shadow=2,"
            "Alignment=2,"               # Center bottom
            "MarginV=25'"
        ),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-preset", "fast",
        "-movflags", "+faststart",
        output_mp4,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(
            f"Subtitle burn-in failed:\n{r.stderr.decode()[-500:]}"
        )
    return output_mp4


# ── Agent ─────────────────────────────────────────────────────────────────────

def compositor_agent(state: "Phase3State") -> "Phase3State":
    print("[Phase3][Compositor] Compositing final video…")

    task_graph       = state["task_graph"]
    enable_subtitles = state.get("enable_subtitles", True)
    timing_manifest  = state.get("timing_manifest", [])

    # ── Collect merged scene clips in scene order ──────────────────────────────
    scene_clips: list[str] = []
    for task in sorted(task_graph, key=lambda t: t["scene_id"]):
        clip = task.get("merged_clip")
        if clip and os.path.exists(clip):
            dur = _probe_duration(clip)
            sz  = os.path.getsize(clip) // 1024
            scene_clips.append(clip)
            print(f"  ← Scene {task['scene_id']}: {Path(clip).name} [{dur:.1f}s, {sz} KB]")
        else:
            print(f"  ⚠  Scene {task['scene_id']}: no merged clip — skipping")

    if not scene_clips:
        return {
            **state,
            "status": "error",
            "error":  "No scene clips available for compositing.",
        }

    # ── Concatenate scenes ─────────────────────────────────────────────────────
    intermediate = str(FINAL_DIR / "_intermediate.mp4")
    print(f"\n  Concatenating {len(scene_clips)} scene(s) with {TRANSITION_DUR}s cross-dissolve…")

    ok = _concat_with_xfade(scene_clips, intermediate)
    if not ok or not os.path.exists(intermediate):
        return {
            **state,
            "status": "error",
            "error":  "Scene concatenation failed.",
        }

    inter_dur = _probe_duration(intermediate)
    inter_sz  = os.path.getsize(intermediate) // 1024
    print(f"  ✅ Concatenated: {inter_dur:.1f}s, {inter_sz} KB")

    # ── Build and burn subtitles ───────────────────────────────────────────────
    output_path    = FINAL_OUTPUT
    subtitle_path: str | None = None

    if enable_subtitles and timing_manifest:
        print("\n  Building SRT subtitles from timing manifest…")
        srt_content = _build_srt(timing_manifest, task_graph)

        if srt_content.strip():
            with open(SUBTITLE_FILE, "w", encoding="utf-8") as f:
                f.write(srt_content)
            subtitle_path = SUBTITLE_FILE
            # Count subtitle entries
            entry_count = srt_content.count("\n\n")
            print(f"  SRT written: {SUBTITLE_FILE} ({entry_count} entries)")

            try:
                print("  Burning subtitles via FFmpeg…")
                _burn_subtitles(intermediate, SUBTITLE_FILE, FINAL_OUTPUT)
                os.remove(intermediate)
                print("  ✅ Subtitles burned in successfully.")
            except Exception as e:
                print(f"  ⚠  Subtitle burn failed ({e})")
                print("     Using video without burned subtitles (SRT file still saved).")
                if os.path.exists(intermediate):
                    os.rename(intermediate, FINAL_OUTPUT)
                else:
                    return {**state, "status": "error", "error": f"Both subtitle burn and intermediate failed: {e}"}
        else:
            print("  ⚠  SRT content empty — skipping subtitle burn")
            os.rename(intermediate, FINAL_OUTPUT)
    else:
        if os.path.exists(intermediate):
            os.rename(intermediate, FINAL_OUTPUT)

    # ── Write task execution log ───────────────────────────────────────────────
    log_path = "outputs/logs/phase3_task_log.json"
    os.makedirs("outputs/logs", exist_ok=True)

    log_data = []
    for task in task_graph:
        entry = {
            "scene_id":    task["scene_id"],
            "location":    task.get("location", ""),
            "status":      task["status"],
            "merged_clip": task.get("merged_clip"),
            "duration_sec": task.get("duration_sec"),
            "error":       task.get("error"),
            "characters":  [],
        }
        for clip in task.get("character_clips", []):
            entry["characters"].append({
                "name":        clip["character_name"],
                "image_path":  clip.get("image_path"),
                "video_path":  clip.get("raw_video_path"),
                "audio_path":  clip.get("audio_path"),
                "synced_path": clip.get("synced_path"),
                "duration_sec": clip.get("duration_sec"),
                "status":      clip["status"],
                "error":       clip.get("error"),
            })
        log_data.append(entry)

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)

    # ── Final report ──────────────────────────────────────────────────────────
    if os.path.exists(FINAL_OUTPUT):
        final_dur = _probe_duration(FINAL_OUTPUT)
        final_sz  = os.path.getsize(FINAL_OUTPUT) / 1_048_576
        print(f"\n[Phase3][Compositor] ✅ Final video: {FINAL_OUTPUT}")
        print(f"    Duration: {final_dur:.1f}s  |  Size: {final_sz:.1f} MB")
        if subtitle_path:
            print(f"    Subtitles: {subtitle_path}")
    else:
        print(f"\n[Phase3][Compositor] ❌ Final output not found: {FINAL_OUTPUT}")

    return {
        **state,
        "final_output":  FINAL_OUTPUT if os.path.exists(FINAL_OUTPUT) else None,
        "subtitle_file": subtitle_path,
        "status":        "complete",
        "task_log":      state.get("task_log", []) + [{"phase3_log": log_path}],
    }