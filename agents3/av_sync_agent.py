"""
agents3/av_sync_agent.py
─────────────────────────
Attaches per-character dialogue audio to each character's video clip.

Audio search order (most specific → least specific):
  1. clip["audio_path"]                              (already set in manifest_loader)
  2. outputs/audio/scene_XX_CharName.wav
  3. outputs/audio/scene_XX_CharName_safe.wav        (spaces → underscores)
  4. outputs/audio/scene_XX_charname.wav             (lowercase)
  5. outputs/audio/scene_XX.wav                      (whole-scene fallback)
  6. Generated silence                               (last resort)

Sync strategy:
  - Audio duration drives the final clip length (dialogue is the master clock)
  - Video loops if shorter than audio
  - Video trims if longer than audio
  - Output always 1280×720, yuv420p, AAC 192k
"""

from __future__ import annotations

import glob
import os
import subprocess
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

SYNCED_DIR = Path("outputs/video/synced")
SYNCED_DIR.mkdir(parents=True, exist_ok=True)


# ── FFprobe helpers ───────────────────────────────────────────────────────────

def _probe_duration(path: str) -> float:
    """Return file duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True, timeout=20,
        )
        val = r.stdout.strip()
        return float(val) if val else 5.0
    except Exception:
        return 5.0


# ── Silence generator ─────────────────────────────────────────────────────────

def _generate_silence(duration: float, out_path: Path) -> str:
    """Generate a silent WAV of the given duration."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", f"{duration:.3f}",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return str(out_path)


# ── Audio file finder ─────────────────────────────────────────────────────────

def _find_audio(clip: dict, audio_dir: str) -> str | None:
    """
    Find the best matching audio file for this character clip.
    Returns the path string or None.
    """
    sid       = clip["scene_id"]
    char_name = clip["character_name"]
    safe_name = char_name.replace(" ", "_")

    # Use already-set path first
    existing = clip.get("audio_path", "")
    if existing and os.path.exists(existing):
        return existing

    # Candidate filenames (most specific → least specific)
    candidates = [
        f"scene_{sid:02d}_{char_name}.wav",
        f"scene_{sid:02d}_{safe_name}.wav",
        f"scene_{sid:02d}_{char_name.lower()}.wav",
        f"scene_{sid:02d}_{safe_name.lower()}.wav",
        f"scene_{sid:03d}_{char_name}.wav",
        f"scene_{sid:03d}_{safe_name}.wav",
        f"scene_{sid:02d}.wav",
        f"scene_{sid}.wav",
        f"scene_{sid:03d}.wav",
    ]

    for name in candidates:
        path = os.path.join(audio_dir, name)
        if os.path.exists(path):
            return path

    # Glob wildcard fallback: scene_XX_*.wav
    for pattern in [
        os.path.join(audio_dir, f"scene_{sid:02d}*.wav"),
        os.path.join(audio_dir, f"scene_{sid}*.wav"),
    ]:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]

    return None


# ── Core sync function ────────────────────────────────────────────────────────

def _sync_clip(clip: dict, audio_dir: str, silence_dir: Path) -> str:
    """
    Mux audio into a character video clip.
    Returns the output path string.
    """
    sid        = clip["scene_id"]
    char_name  = clip["character_name"]
    video_path = clip["raw_video_path"]
    safe_name  = char_name.replace(" ", "_")

    out_path = SYNCED_DIR / f"scene_{sid:02d}_{safe_name}_synced.mp4"

    # Probe actual video duration
    actual_vid_dur = _probe_duration(video_path)

    # Find audio
    audio_path = _find_audio(clip, audio_dir)
    if audio_path:
        print(f"    ✅ Audio: {os.path.basename(audio_path)}")
        audio_dur = _probe_duration(audio_path)
    else:
        print(f"    ⚠  No audio for scene {sid} · {char_name} — generating silence")
        sil_path   = silence_dir / f"silence_{sid:02d}_{safe_name}.wav"
        audio_path = _generate_silence(actual_vid_dur, sil_path)
        audio_dur  = actual_vid_dur

    # Final duration = max(audio, video, 2s minimum)
    final_dur = max(audio_dur, actual_vid_dur, 2.0)

    # ── Build FFmpeg command ──────────────────────────────────────────────────
    # If video is shorter than audio, loop it
    if actual_vid_dur < final_dur - 0.1:
        video_input_args = ["-stream_loop", "-1", "-i", video_path]
    else:
        video_input_args = ["-i", video_path]

    # Video filter: trim, normalize resolution, set pts
    vf = (
        f"trim=0:{final_dur:.3f},"
        "setpts=PTS-STARTPTS,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    # Audio filter: trim and normalize pts
    af = f"atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS"

    cmd = (
        ["ffmpeg", "-y"]
        + video_input_args
        + ["-i", audio_path]
        + [
            "-vf",     vf,
            "-af",     af,
            "-c:v",    "libx264",
            "-pix_fmt","yuv420p",
            "-c:a",    "aac",
            "-b:a",    "192k",
            "-t",      f"{final_dur:.3f}",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        stderr = result.stderr.decode()[-500:]
        raise RuntimeError(
            f"FFmpeg mux failed for {char_name} scene {sid}:\n{stderr}"
        )

    if not out_path.exists() or out_path.stat().st_size < 5000:
        raise RuntimeError(f"FFmpeg produced no/empty output for {char_name} scene {sid}")

    return str(out_path)


# ── Agent ─────────────────────────────────────────────────────────────────────

def av_sync_agent(state: "Phase3State") -> "Phase3State":
    print("[Phase3][A/V Sync] Attaching dialogue audio to character video clips…")

    task_graph = state["task_graph"]
    audio_dir  = state.get("audio_dir", "outputs/audio")

    silence_dir = Path("outputs/video/silence")
    silence_dir.mkdir(parents=True, exist_ok=True)

    # List available audio files for debugging
    wav_files = sorted(
        glob.glob(os.path.join(audio_dir, "**/*.wav"), recursive=True)
        + glob.glob(os.path.join(audio_dir, "*.wav"))
    )
    if wav_files:
        print(f"  Found {len(wav_files)} WAV file(s) in '{audio_dir}':")
        for w in wav_files[:15]:
            print(f"    {os.path.basename(w)}")
        if len(wav_files) > 15:
            print(f"    … and {len(wav_files) - 15} more")
    else:
        print(f"  ⚠  No WAV files found in '{audio_dir}'")

    ok_count  = 0
    err_count = 0

    for task in task_graph:
        sid = task["scene_id"]

        for clip in task["character_clips"]:
            char_name = clip["character_name"]
            safe_name = char_name.replace(" ", "_")

            # Skip if no video
            raw_video = clip.get("raw_video_path", "")
            if not raw_video or not os.path.exists(raw_video):
                print(f"  ⏭  Scene {sid} · {char_name}: no video — skipping A/V sync")
                continue

            # Skip if synced clip already exists and is valid
            synced_path = SYNCED_DIR / f"scene_{sid:02d}_{safe_name}_synced.mp4"
            if synced_path.exists() and synced_path.stat().st_size > 5_000:
                print(f"  ⏭  Scene {sid} · {char_name}: synced clip exists — skipping")
                clip["synced_path"] = str(synced_path)
                clip["status"]      = "synced"
                ok_count += 1
                continue

            print(f"\n  [Scene {sid} · {char_name}] Syncing audio…")

            try:
                out = _sync_clip(clip, audio_dir, silence_dir)
                clip["synced_path"] = out
                clip["status"]      = "synced"
                dur = _probe_duration(out)
                sz  = os.path.getsize(out) // 1024
                print(f"  ✅ Scene {sid} · {char_name} → {out} [{dur:.1f}s, {sz} KB]")
                ok_count += 1

            except Exception as exc:
                print(f"  ❌ Scene {sid} · {char_name} sync failed: {exc}")
                # Fall back to raw video without synced audio
                clip["synced_path"] = raw_video
                clip["status"]      = "synced"   # allow pipeline to continue
                clip["error"]       = str(exc)
                err_count += 1

    total = ok_count + err_count
    print(f"\n[Phase3][A/V Sync] ✅ {ok_count}/{total} clips synced.\n")
    return {**state, "task_graph": task_graph}