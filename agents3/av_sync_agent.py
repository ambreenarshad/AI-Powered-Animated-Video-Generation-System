# agents3/av_sync_agent.py
"""
A/V Sync Agent
───────────────
Merges Phase 2 audio (.wav per scene) into the animated video clips.
Uses MoviePy to set_audio, trim/loop to match timing_manifest durations.
"""

import os
import glob
from pathlib import Path
from typing import List, Dict, Any

import numpy as np
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips
from moviepy.audio.AudioClip import AudioArrayClip

SYNCED_DIR = Path("outputs/video/synced")
SYNCED_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _silence(duration: float, fps: int = 44100) -> AudioArrayClip:
    samples = int(duration * fps)
    arr     = np.zeros((samples, 2), dtype=np.float32)
    return AudioArrayClip(arr, fps=fps)


def _resolve_audio(task: dict, audio_dir: str) -> str:
    """
    Find the audio file for a scene. Tries multiple patterns because
    Phase 2 may write scene_1.wav, scene_01.wav, or scene_001.wav.
    """
    sid = task["scene_id"]

    # 1. Use path already set in task (from timing_manifest)
    candidate = task.get("audio_path", "")
    if candidate and os.path.exists(candidate):
        return candidate

    # 2. Search audio_dir — exact scene file first, never individual line files
    for pattern in [
        f"scene_{sid:02d}.wav",
        f"scene_{sid}.wav",
        f"scene_{sid:03d}.wav",
    ]:
        matches = glob.glob(os.path.join(audio_dir, pattern))
        if matches:
            return matches[0]

    return ""   # not found


def _sync_scene(task: dict, audio_dir: str) -> str:
    sid        = task["scene_id"]
    video_path = task["animated_clip"]
    duration   = task["duration_sec"]
    out_path   = str(SYNCED_DIR / f"scene_{sid:02d}_synced.mp4")

    video = VideoFileClip(video_path)

    # ── Loop or trim video to match target duration ────────────────────────
    if video.duration < duration - 0.05:
        loops = int(duration / video.duration) + 1
        video = concatenate_videoclips([video] * loops).subclip(0, duration)
    elif video.duration > duration + 0.05:
        video = video.subclip(0, duration)

    # ── Find and attach audio ──────────────────────────────────────────────
    audio_path = _resolve_audio(task, audio_dir)

    if audio_path:
        print(f"  ✅ Scene {sid}: audio found → {audio_path}")
        audio = AudioFileClip(audio_path)
        # Trim audio if longer than video
        if audio.duration > video.duration:
            audio = audio.subclip(0, video.duration)
        video = video.set_audio(audio)
    else:
        print(f"  ⚠️  Scene {sid}: no audio file found in '{audio_dir}', using silence.")
        video = video.set_audio(_silence(video.duration))

    video.write_videofile(
        out_path,
        codec       = "libx264",
        audio_codec = "aac",
        fps         = 24,
        preset      = "fast",
        logger      = None,
    )
    video.close()
    return out_path


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────

def av_sync_agent(state: dict) -> dict:
    print("[Phase 3 · A/V Sync Agent] Merging audio into video clips…")

    task_graph: List[Dict[str, Any]] = state["task_graph"]
    audio_dir   = state.get("audio_dir", "outputs/audio")
    synced_results = []

    # Debug: show what audio files are actually present
    wav_files = glob.glob(os.path.join(audio_dir, "**/*.wav"), recursive=True) + \
                glob.glob(os.path.join(audio_dir, "*.wav"))
    if wav_files:
        print(f"  Audio files found in '{audio_dir}':")
        for w in wav_files:
            print(f"    {w}")
    else:
        print(f"  ⚠️  No .wav files found in '{audio_dir}' — check your Phase 2 output path.")

    for task in task_graph:
        sid = task["scene_id"]

        # Skip scenes that errored or weren't animated
        if task["status"] == "error" or not task.get("animated_clip"):
            print(f"  ⏭  Scene {sid}: skipped (status={task['status']}, animated_clip={task.get('animated_clip')})")
            synced_results.append({"scene_id": sid, "status": "skipped"})
            continue

        # Check animated clip actually exists on disk
        animated = task["animated_clip"]
        if not os.path.exists(animated):
            print(f"  ❌ Scene {sid}: animated clip not found on disk: {animated}")
            task["status"] = "error"
            task["error"]  = f"animated clip missing: {animated}"
            synced_results.append({"scene_id": sid, "status": "error", "error": task["error"]})
            continue

        try:
            out_path = _sync_scene(task, audio_dir)
            task["synced_clip"] = out_path
            task["status"]      = "synced"
            print(f"  ✅ Scene {sid}: synced → {out_path}")
            synced_results.append({"scene_id": sid, "clip_path": out_path, "status": "done"})
        except Exception as e:
            import traceback
            print(f"  ❌ Scene {sid}: sync failed: {e}")
            print(traceback.format_exc())
            task["status"] = "error"
            task["error"]  = str(e)
            synced_results.append({"scene_id": sid, "status": "error", "error": str(e)})

    ok = sum(1 for r in synced_results if r["status"] == "done")
    print(f"[Phase 3 · A/V Sync Agent] ✅ {ok}/{len(task_graph)} scenes synced.")
    return {**state, "task_graph": task_graph, "synced_results": synced_results}