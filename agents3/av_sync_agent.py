"""
agents3/av_sync_agent.py
─────────────────────────
For every clip in outputs/clips/:
  1. Strip (mute) the model-generated audio track completely
  2. Find all matching WAV lines for that character+scene in outputs/audio/
  3. Concatenate those WAV lines in order → single audio track
  4. Mux muted video + concatenated audio → outputs/video/synced/

Audio filename patterns searched (in priority order):
  scene_01_Jack_line_000.wav   ← per-line files (concatenated in order)
  scene_01_Jack.wav            ← single combined file for character
  scene_01.wav                 ← whole-scene fallback
  → silence                    ← last resort

Output naming:
  outputs/clips/scene_01_Jack.mp4  →  outputs/video/synced/scene_01_Jack_synced.mp4
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


# ── FFprobe ───────────────────────────────────────────────────────────────────

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
        return float(val) if val else 5.0
    except Exception:
        return 5.0


# ── Silence generator ─────────────────────────────────────────────────────────

def _generate_silence(duration: float, out_path: Path) -> str:
    subprocess.run(
        ["ffmpeg", "-y",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{duration:.3f}",
         "-c:a", "pcm_s16le", str(out_path)],
        capture_output=True, timeout=30,
    )
    return str(out_path)


# ── Audio finder ──────────────────────────────────────────────────────────────

def _find_audio_files(scene_id: int, char_name: str, audio_dir: str) -> list[str]:
    """
    Return an ordered list of WAV files for this character+scene.

    Priority:
      1. Per-line files:  scene_01_Jack_line_000.wav, scene_01_Jack_line_001.wav
         (sorted by filename so they play in dialogue order)
      2. Single combined: scene_01_Jack.wav
      3. Whole-scene:     scene_01.wav
    Returns [] if nothing found.
    """
    sid       = scene_id
    safe_name = char_name.replace(" ", "_")

    # ── 1. Per-line files ─────────────────────────────────────────────────────
    line_patterns = [
        os.path.join(audio_dir, f"scene_{sid:02d}_{char_name}_line_*.wav"),
        os.path.join(audio_dir, f"scene_{sid:02d}_{safe_name}_line_*.wav"),
        os.path.join(audio_dir, f"scene_{sid:02d}_{char_name.lower()}_line_*.wav"),
        os.path.join(audio_dir, f"scene_{sid:02d}_{safe_name.lower()}_line_*.wav"),
        os.path.join(audio_dir, f"scene_{sid:03d}_{char_name}_line_*.wav"),
        os.path.join(audio_dir, f"scene_{sid:03d}_{safe_name}_line_*.wav"),
    ]
    for pat in line_patterns:
        matches = sorted(glob.glob(pat))   # sorted = line_000, line_001, …
        if matches:
            return matches

    # ── 2. Single combined character file ─────────────────────────────────────
    combined_candidates = [
        f"scene_{sid:02d}_{char_name}.wav",
        f"scene_{sid:02d}_{safe_name}.wav",
        f"scene_{sid:02d}_{char_name.lower()}.wav",
        f"scene_{sid:02d}_{safe_name.lower()}.wav",
        f"scene_{sid:03d}_{char_name}.wav",
        f"scene_{sid:03d}_{safe_name}.wav",
    ]
    for name in combined_candidates:
        p = os.path.join(audio_dir, name)
        if os.path.exists(p):
            return [p]

    # ── 3. Whole-scene fallback ───────────────────────────────────────────────
    for name in [f"scene_{sid:02d}.wav", f"scene_{sid}.wav", f"scene_{sid:03d}.wav"]:
        p = os.path.join(audio_dir, name)
        if os.path.exists(p):
            return [p]

    return []


# ── Concatenate multiple WAVs into one ────────────────────────────────────────

def _concat_wavs(wav_paths: list[str], out_path: Path) -> str:
    """
    Concatenate one or more WAV files into a single WAV via FFmpeg concat.
    Single file → just copy it.
    """
    if len(wav_paths) == 1:
        shutil.copy(wav_paths[0], out_path)
        return str(out_path)

    list_file = out_path.parent / f"_wavlist_{out_path.stem}.txt"
    with open(list_file, "w") as f:
        for p in wav_paths:
            escaped = os.path.abspath(p).replace("\\", "/")
            f.write(f"file '{escaped}'\n")

    result = subprocess.run(
        ["ffmpeg", "-y",
         "-f", "concat", "-safe", "0",
         "-i", str(list_file),
         "-c", "copy",
         str(out_path)],
        capture_output=True, timeout=120,
    )
    try:
        list_file.unlink()
    except OSError:
        pass

    if result.returncode != 0 or not out_path.exists():
        raise RuntimeError(
            f"WAV concat failed:\n{result.stderr.decode()[-300:]}"
        )
    return str(out_path)


# ── Core mux: muted video + dialogue audio → synced mp4 ──────────────────────

def _mux(video_path: str, audio_path: str, out_path: Path) -> str:
    """
    Strip the model-generated audio from video_path, attach audio_path,
    and write the result to out_path.

    The -map directives ensure:
      - video stream comes from input 0  (the clip)
      - audio stream comes from input 1  (our WAV)
    so the model's original audio is completely discarded.
    """
    vid_dur   = _probe_duration(video_path)
    audio_dur = _probe_duration(audio_path)
    final_dur = max(audio_dur, vid_dur, 2.0)

    # Loop video if it is shorter than the audio track
    if vid_dur < final_dur - 0.1:
        video_input = ["-stream_loop", "-1", "-i", video_path]
    else:
        video_input = ["-i", video_path]

    vf = (
        f"trim=0:{final_dur:.3f},setpts=PTS-STARTPTS,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    af = f"atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS"

    cmd = (
        ["ffmpeg", "-y"]
        + video_input          # input 0: video clip (model-generated)
        + ["-i", audio_path]   # input 1: our dialogue WAV
        + [
            "-map", "0:v:0",   # take VIDEO from input 0
            "-map", "1:a:0",   # take AUDIO from input 1 only (drops model audio)
            "-vf",      vf,
            "-af",      af,
            "-c:v",     "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a",     "aac",
            "-b:a",     "192k",
            "-t",       f"{final_dur:.3f}",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode()[-500:])
    if not out_path.exists() or out_path.stat().st_size < 5_000:
        raise RuntimeError("FFmpeg produced no/empty output")
    return str(out_path)


# ── Agent ─────────────────────────────────────────────────────────────────────

def av_sync_agent(state: "Phase3State") -> "Phase3State":
    print("[Phase3][A/V Sync] Muting model audio and attaching dialogue WAVs…")

    task_graph = state["task_graph"]
    audio_dir  = state.get("audio_dir", "outputs/audio")

    tmp_dir = SYNCED_DIR / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Print available audio files for reference
    all_wavs = sorted(glob.glob(os.path.join(audio_dir, "*.wav")))
    print(f"  Audio folder '{audio_dir}': {len(all_wavs)} WAV file(s)")
    for w in all_wavs[:20]:
        print(f"    {os.path.basename(w)}")
    if len(all_wavs) > 20:
        print(f"    … and {len(all_wavs) - 20} more")

    ok_count  = 0
    err_count = 0

    for task in task_graph:
        sid = task["scene_id"]

        # Deduplicate character clips — keep first occurrence of each name
        seen: set[str] = set()
        deduped: list[dict] = []
        for clip in task.get("character_clips", []):
            name = clip.get("character_name", "")
            if name and name not in seen:
                seen.add(name)
                deduped.append(clip)
            elif name:
                print(f"  ⚠  Scene {sid}: duplicate clip for '{name}' dropped")
        task["character_clips"] = deduped

        for clip in task["character_clips"]:
            char_name = clip.get("character_name", "")
            safe_name = char_name.replace(" ", "_")

            # Deterministic output path — one file per (scene, character)
            out_path = SYNCED_DIR / f"scene_{sid:02d}_{safe_name}_synced.mp4"

            # Reuse if already valid (skip re-processing on reruns)
            if out_path.exists() and out_path.stat().st_size > 5_000:
                print(f"  ⏭  Scene {sid} · {char_name}: already synced — reusing "
                      f"{out_path.name}")
                clip["synced_path"] = str(out_path)
                clip["status"]      = "synced"
                ok_count += 1
                continue

            # Locate source video in outputs/clips/
            raw_video = clip.get("raw_video_path", "")
            if not raw_video or not os.path.exists(raw_video):
                print(f"  ⚠  Scene {sid} · {char_name}: source video not found "
                      f"({raw_video!r}) — skipping")
                continue

            print(f"\n  [Scene {sid} · {char_name}]")
            print(f"    Source : {os.path.basename(raw_video)}")

            # Find WAV file(s) for this character+scene
            wav_files = _find_audio_files(sid, char_name, audio_dir)

            if wav_files:
                print(f"    Audio  : {[os.path.basename(w) for w in wav_files]}")
                if len(wav_files) == 1:
                    combined_wav = wav_files[0]
                else:
                    combined_path = tmp_dir / f"scene_{sid:02d}_{safe_name}_combined.wav"
                    combined_wav  = _concat_wavs(wav_files, combined_path)
                    print(f"    Merged {len(wav_files)} line WAVs → "
                          f"{os.path.basename(combined_wav)}")
            else:
                print(f"    Audio  : ⚠ none found — using silence")
                sil_path    = tmp_dir / f"scene_{sid:02d}_{safe_name}_silence.wav"
                vid_dur     = _probe_duration(raw_video)
                combined_wav = _generate_silence(vid_dur, sil_path)

            # Mux: model video (audio stripped) + our WAV
            try:
                _mux(raw_video, combined_wav, out_path)
                clip["synced_path"] = str(out_path)
                clip["status"]      = "synced"
                dur = _probe_duration(str(out_path))
                sz  = out_path.stat().st_size // 1024
                print(f"    ✅ {out_path.name}  [{dur:.1f}s, {sz} KB]")
                ok_count += 1
            except Exception as exc:
                print(f"    ❌ Mux failed: {exc}")
                clip["synced_path"] = raw_video   # fallback so pipeline continues
                clip["status"]      = "synced"
                clip["error"]       = str(exc)
                err_count += 1

    # Tidy up temp concat files
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    total = ok_count + err_count
    print(f"\n[Phase3][A/V Sync] ✅ {ok_count}/{total} clips synced.\n")
    return {**state, "task_graph": task_graph}