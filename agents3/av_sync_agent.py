"""
agents3/av_sync_agent.py
─────────────────────────
For every clip in outputs/clips/:
  1. Strip (mute) the model-generated audio track completely
  2. Find all matching WAV lines for that character+scene in outputs/audio/
  3. Concatenate those WAV lines in order → single audio track
  4. Generate a per-character SRT whose timestamps are derived directly from
     the actual WAV file durations — NOT from the timing manifest offsets.
  5. Burn subtitles + mux audio → outputs/video/synced/

Why WAV-duration timestamps?
  The audio track for this clip is literally the concatenation of the per-line
  WAV files.  The only timestamps that are guaranteed to match the audio are
  the ones computed from the WAV files themselves:
    line 0 → 0.000 … wav[0].duration
    line 1 → wav[0].duration … wav[0].duration + wav[1].duration
    …
  Using the timing-manifest's absolute start_ms/end_ms and subtracting a
  scene offset introduces drift whenever the manifest timestamps don't align
  perfectly with the actual synthesised speech length.

Audio filename patterns searched (in priority order):
  scene_01_Jack_line_000.wav   ← per-line files (concatenated in order)
  scene_01_Jack.wav            ← single combined file for character
  scene_01.wav                 ← whole-scene fallback
  → silence                    ← last resort

Output naming:
  outputs/clips/scene_01_Jack.mp4  →  outputs/video/synced/scene_01_Jack_synced.mp4
  outputs/video/synced/scene_01_Jack_synced.srt  ← subtitle sidecar
"""

from __future__ import annotations

import glob
import os
import subprocess
import shutil
import wave
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

SYNCED_DIR = Path("outputs/video/synced")
SYNCED_DIR.mkdir(parents=True, exist_ok=True)


# ── Duration helpers ──────────────────────────────────────────────────────────

def _probe_duration(path: str) -> float:
    """Duration of any media file via ffprobe."""
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


def _wav_duration(path: str) -> float:
    """
    Read WAV duration directly from the file header — fast and exact.
    Falls back to ffprobe if the file is not a standard PCM WAV.
    """
    try:
        with contextlib.closing(wave.open(path, "r")) as wf:
            frames = wf.getnframes()
            rate   = wf.getframerate()
            if rate > 0 and frames > 0:
                return frames / rate
    except Exception:
        pass
    return _probe_duration(path)


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
        matches = sorted(glob.glob(pat))
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


# ── SRT builder — timestamps derived from actual WAV durations ────────────────

def _ms_to_srt_time(ms: float) -> str:
    ms = max(0.0, ms)
    total_ms = int(round(ms))
    h,  rem  = divmod(total_ms, 3_600_000)
    m,  rem  = divmod(rem,       60_000)
    s,  rem  = divmod(rem,        1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{rem:03d}"


def _build_srt_from_wavs(
    wav_paths: list[str],
    dialogue_lines: list[dict],
) -> str:
    """
    Build an SRT whose timestamps come from measuring the WAV files directly.

    Case A — per-line WAVs (multiple files, or single file with '_line_' in name):
      Each WAV corresponds to exactly one dialogue line.
      subtitle[i] starts when wav[0..i-1] have finished and ends when wav[i]
      finishes.  This is the only timing that is guaranteed to be in sync.

    Case B — single combined WAV:
      We know only the total duration.  If the manifest supplied start_ms/end_ms
      we use them, scaled to match the actual WAV length.  Otherwise we divide
      the duration equally among the lines.

    Returns an SRT-formatted string (empty string if no lines).
    """
    lines_with_text = [d for d in dialogue_lines if d.get("line", "").strip()]
    if not lines_with_text:
        return ""

    entries: list[str] = []
    idx = 1

    # ── Case A: one WAV per line ──────────────────────────────────────────────
    is_per_line = (
        len(wav_paths) > 1
        or (len(wav_paths) == 1 and "_line_" in os.path.basename(wav_paths[0]))
    )

    if is_per_line and len(wav_paths) >= len(lines_with_text):
        cursor_ms = 0.0
        for i, dlg in enumerate(lines_with_text):
            wav_dur_s  = _wav_duration(wav_paths[i]) if i < len(wav_paths) else 2.0
            wav_dur_ms = wav_dur_s * 1000.0

            start_ms = cursor_ms
            end_ms   = cursor_ms + wav_dur_ms

            speaker = dlg.get("speaker", "")
            text    = f"{speaker}: {dlg['line']}" if speaker else dlg["line"]
            entries.append(
                f"{idx}\n"
                f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}\n"
                f"{text}\n"
            )
            idx      += 1
            cursor_ms = end_ms  # next subtitle starts exactly where this WAV ends

        return "\n".join(entries)

    # ── Case B: single combined WAV ───────────────────────────────────────────
    total_wav_ms = _wav_duration(wav_paths[0]) * 1000.0 if wav_paths else 5000.0

    has_manifest_timing = all(
        d.get("start_ms") is not None and d.get("end_ms") is not None
        for d in lines_with_text
    )

    if has_manifest_timing:
        # Make timestamps relative to the first line, then scale to WAV length
        first_abs      = min(d["start_ms"] for d in lines_with_text)
        last_abs       = max(d["end_ms"]   for d in lines_with_text)
        manifest_span  = max(last_abs - first_abs, 1)
        scale          = total_wav_ms / manifest_span

        for dlg in lines_with_text:
            rel_start = (dlg["start_ms"] - first_abs) * scale
            rel_end   = (dlg["end_ms"]   - first_abs) * scale
            rel_start = max(0.0,           min(rel_start, total_wav_ms - 100))
            rel_end   = max(rel_start + 300, min(rel_end, total_wav_ms))

            speaker = dlg.get("speaker", "")
            text    = f"{speaker}: {dlg['line']}" if speaker else dlg["line"]
            entries.append(
                f"{idx}\n"
                f"{_ms_to_srt_time(rel_start)} --> {_ms_to_srt_time(rel_end)}\n"
                f"{text}\n"
            )
            idx += 1
    else:
        # No manifest timing — divide WAV equally
        slot_ms   = total_wav_ms / len(lines_with_text)
        cursor_ms = 0.0
        for dlg in lines_with_text:
            start_ms = cursor_ms
            end_ms   = cursor_ms + slot_ms
            speaker  = dlg.get("speaker", "")
            text     = f"{speaker}: {dlg['line']}" if speaker else dlg["line"]
            entries.append(
                f"{idx}\n"
                f"{_ms_to_srt_time(start_ms)} --> {_ms_to_srt_time(end_ms)}\n"
                f"{text}\n"
            )
            idx      += 1
            cursor_ms = end_ms

    return "\n".join(entries)


def _write_srt(
    wav_paths: list[str],
    dialogue_lines: list[dict],
    srt_path: Path,
) -> bool:
    """Write SRT file derived from WAV durations. Returns True if written."""
    content = _build_srt_from_wavs(wav_paths, dialogue_lines)
    if not content.strip():
        return False
    srt_path.write_text(content, encoding="utf-8")
    return True


# ── Core mux: muted video + dialogue audio + subtitles → synced mp4 ──────────

def _mux(
    video_path: str,
    audio_path: str,
    out_path: Path,
    srt_path: Path | None = None,
) -> str:
    """
    Strip the model-generated audio from video_path, attach audio_path,
    optionally burn subtitles from srt_path, and write to out_path.

    -map 0:v:0  → video from the clip
    -map 1:a:0  → audio from our WAV only (model audio discarded)
    """
    vid_dur   = _probe_duration(video_path)
    audio_dur = _probe_duration(audio_path)
    final_dur = max(audio_dur, vid_dur, 2.0)

    video_input = (
        ["-stream_loop", "-1", "-i", video_path]
        if vid_dur < final_dur - 0.1
        else ["-i", video_path]
    )

    base_vf = (
        f"trim=0:{final_dur:.3f},setpts=PTS-STARTPTS,"
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    if srt_path and srt_path.exists():
        srt_str = str(srt_path.resolve())
        if os.name == "nt":
            srt_str = srt_str.replace("\\", "/").replace(":/", "\\:/", 1)
        else:
            srt_str = srt_str.replace(":", "\\:")
        vf = (
            base_vf + ","
            f"subtitles='{srt_str}':force_style="
            "'FontSize=18,PrimaryColour=&HFFFFFF,"
            "OutlineColour=&H000000,Outline=2,Shadow=1,"
            "Alignment=2,MarginV=20'"
        )
        print(f"    📝 Burning subtitles from {srt_path.name}")
    else:
        vf = base_vf

    af = f"atrim=0:{final_dur:.3f},asetpts=PTS-STARTPTS"

    cmd = (
        ["ffmpeg", "-y"]
        + video_input
        + ["-i", audio_path]
        + [
            "-map",     "0:v:0",
            "-map",     "1:a:0",
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
    print("[Phase3][A/V Sync] Syncing audio, building WAV-timed subtitles, muxing…")

    task_graph = state["task_graph"]
    audio_dir  = state.get("audio_dir", "outputs/audio")

    tmp_dir = SYNCED_DIR / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

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

        # Deduplicate character clips
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

            out_path = SYNCED_DIR / f"scene_{sid:02d}_{safe_name}_synced.mp4"
            srt_path = SYNCED_DIR / f"scene_{sid:02d}_{safe_name}_synced.srt"

            # Reuse already-synced clip
            if out_path.exists() and out_path.stat().st_size > 5_000:
                print(f"  ⏭  Scene {sid} · {char_name}: already synced — reusing")
                clip["synced_path"]   = str(out_path)
                clip["subtitle_path"] = str(srt_path) if srt_path.exists() else None
                clip["status"]        = "synced"
                ok_count += 1
                continue

            # Source video
            raw_video = clip.get("raw_video_path", "")
            if not raw_video or not os.path.exists(raw_video):
                print(f"  ⚠  Scene {sid} · {char_name}: source video not found "
                      f"({raw_video!r}) — skipping")
                continue

            print(f"\n  [Scene {sid} · {char_name}]")
            print(f"    Source : {os.path.basename(raw_video)}")

            # Find WAV files
            wav_files = _find_audio_files(sid, char_name, audio_dir)

            if wav_files:
                print(f"    Audio  : {[os.path.basename(w) for w in wav_files]}")

                # Log per-line WAV durations for verification
                if len(wav_files) > 1:
                    for i, wf in enumerate(wav_files):
                        dur = _wav_duration(wf)
                        print(f"             line_{i:03d}: {dur:.3f}s")

                if len(wav_files) == 1:
                    combined_wav      = wav_files[0]
                    wav_files_for_srt = wav_files
                else:
                    combined_path     = tmp_dir / f"scene_{sid:02d}_{safe_name}_combined.wav"
                    combined_wav      = _concat_wavs(wav_files, combined_path)
                    wav_files_for_srt = wav_files  # keep per-line list for SRT timing
                    print(f"    Merged {len(wav_files)} WAVs → "
                          f"{os.path.basename(combined_wav)}")
            else:
                print(f"    Audio  : ⚠ none found — using silence")
                sil_path          = tmp_dir / f"scene_{sid:02d}_{safe_name}_silence.wav"
                vid_dur           = _probe_duration(raw_video)
                combined_wav      = _generate_silence(vid_dur, sil_path)
                wav_files_for_srt = [combined_wav]

            # Build SRT timed directly from WAV file durations
            dialogue_lines = clip.get("dialogue_lines", [])
            has_subs       = _write_srt(wav_files_for_srt, dialogue_lines, srt_path)

            if has_subs:
                n_text = len([d for d in dialogue_lines if d.get("line", "").strip()])
                print(f"    Subs   : {srt_path.name} ({n_text} line(s), WAV-timed)")
                active_srt = srt_path
            else:
                print(f"    Subs   : none (no dialogue lines)")
                active_srt = None

            # Mux: stripped video + our audio + burned subtitles
            try:
                _mux(raw_video, combined_wav, out_path, active_srt)
                clip["synced_path"]   = str(out_path)
                clip["subtitle_path"] = str(active_srt) if active_srt else None
                clip["status"]        = "synced"
                dur = _probe_duration(str(out_path))
                sz  = out_path.stat().st_size // 1024
                print(f"    ✅ {out_path.name}  [{dur:.1f}s, {sz} KB]")
                ok_count += 1
            except Exception as exc:
                print(f"    ❌ Mux failed: {exc}")
                clip["synced_path"]   = raw_video
                clip["subtitle_path"] = None
                clip["status"]        = "synced"
                clip["error"]         = str(exc)
                err_count += 1

    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    total = ok_count + err_count
    print(f"\n[Phase3][A/V Sync] ✅ {ok_count}/{total} clips synced.\n")
    return {**state, "task_graph": task_graph}