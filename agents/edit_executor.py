"""
agents/edit_executor.py
────────────────────────
Executes classified edit intents on the pipeline outputs.

Key principles:
  • SCOPE IS HONORED — "scene:1" only modifies scene 1, "character:Jack"
    only touches Jack's images/clips/audio.
  • CASCADES — after modifying primary assets (images, per-line WAVs),
    we re-run the downstream merge/sync/composite stages so the changes
    appear in the final video and merged scene clips.
  • Returns the list of files that were actually modified, for snapshot.

Entry point:
    execute_edit(state, intent) → (new_state, modified_paths, label)
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any

# Filter presets used by image filter edits — keep aligned with edit_agent.py
try:
    from agents.edit_agent import FILTER_PRESETS
except Exception:
    FILTER_PRESETS = {
        "sepia":       "colorchannelmixer=rr=0.393:rg=0.769:rb=0.189:gr=0.349:gg=0.686:gb=0.168:br=0.272:bg=0.534:bb=0.131",
        "noir":        "hue=s=0,curves=all='0/0 0.5/0.3 1/0.8'",
        "vintage":     "colorchannelmixer=rr=0.7:rg=0.2:rb=0.1:gr=0.1:gg=0.8:gb=0.1:br=0.1:bg=0.1:bb=0.6",
        "black_white": "hue=s=0",
        "grainy":      "noise=alls=20:allf=t",
        "cinematic":   "curves=all='0/0 0.3/0.2 0.7/0.8 1/1'",
        "darker":      "curves=all='0/0 0.5/0.3 1/0.75'",
        "brighter":    "curves=all='0/0 0.5/0.65 1/1'",
        "warm":        "colorchannelmixer=rr=1.1:rb=0:gr=0:gg=1.0:gb=0:br=0:bg=0:bb=0.85",
        "cold":        "colorchannelmixer=rr=0.85:rb=0:gr=0:gg=1.0:gb=0:br=0:bg=0:bb=1.1",
    }


# ── Public entry ──────────────────────────────────────────────────────────────

def execute_edit(
    state: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[dict[str, Any], list[str], str]:
    """Dispatch to the correct executor based on intent. Returns (state, modified_files, label)."""
    fn = _DISPATCH.get(intent.get("intent", ""))
    if fn is None:
        return state, [], f"⚠ Unknown intent: {intent.get('intent')}"
    try:
        return fn(state, intent)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return state, [], f"❌ Execution failed: {exc}"


# ── Scope helpers ─────────────────────────────────────────────────────────────

def _scene_id_from_filename(name: str) -> int | None:
    m = re.search(r"scene[_\-]?(\d+)", os.path.basename(name), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _character_from_filename(name: str) -> str | None:
    """
    Extract character name from filenames like:
      scene_01_Jack.png
      scene_01_Jack_line_000.wav
      scene_01_Jack_synced.mp4
      scene_01_Jack.mp4
    Returns None if no character can be parsed.
    """
    base = os.path.basename(name)
    base = re.sub(r"\.(png|wav|mp4|jpg|jpeg)$", "", base, flags=re.IGNORECASE)
    m = re.match(r"scene[_\-]?\d+[_\-]([A-Za-z][A-Za-z0-9]*)", base)
    if not m:
        return None
    cand = m.group(1)
    # Reject "merged", "synced", "combined" etc.
    if cand.lower() in {"merged", "synced", "combined", "clip"}:
        return None
    return cand


def _matches_scope(scope: str, scene_id: int | None, character: str | None) -> bool:
    """
    scope formats:
      "all"
      "all_scenes"
      "all_characters"
      "scene:3"
      "character:Jack"
    """
    if not scope or scope in ("all", "all_scenes", "all_characters"):
        return True
    if scope.startswith("scene:"):
        try:
            target = int(scope.split(":", 1)[1])
            return scene_id == target
        except Exception:
            return True
    if scope.startswith("character:"):
        target = scope.split(":", 1)[1].strip().lower()
        return character is not None and character.lower() == target
    return True


def _file_in_scope(path: str, scope: str) -> bool:
    """Check whether a given file path falls inside the requested scope."""
    sid = _scene_id_from_filename(path)
    char = _character_from_filename(path)
    return _matches_scope(scope, sid, char)


# ── FFmpeg helpers ────────────────────────────────────────────────────────────

def _ffmpeg(*args, timeout=120) -> tuple[bool, str]:
    """Run ffmpeg, return (ok, stderr_tail)."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            return False, r.stderr.decode(errors="ignore")[-400:]
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=20,
        )
        return float(r.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _apply_image_filter_to_file(image_path: str, filter_vf: str) -> bool:
    """Apply an FFmpeg -vf filter to an image, replacing it in-place."""
    if not os.path.exists(image_path):
        return False
    tmp = image_path + ".tmp.png"
    ok, err = _ffmpeg("-i", image_path, "-vf", filter_vf, tmp, timeout=60)
    if not ok or not os.path.exists(tmp):
        print(f"    ⚠ Filter failed for {os.path.basename(image_path)}: {err}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    shutil.move(tmp, image_path)
    return True


def _apply_video_filter_to_file(video_path: str, filter_vf: str) -> bool:
    """Apply an FFmpeg -vf filter to a video, preserving its audio."""
    if not os.path.exists(video_path):
        return False
    tmp = video_path + ".tmp.mp4"
    ok, err = _ffmpeg(
        "-i", video_path,
        "-vf", filter_vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        tmp,
        timeout=180,
    )
    if not ok or not os.path.exists(tmp):
        print(f"    ⚠ Video filter failed for {os.path.basename(video_path)}: {err}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    shutil.move(tmp, video_path)
    return True


# ── Cascade helpers ───────────────────────────────────────────────────────────

def _scenes_touched_by_files(file_paths: list[str]) -> set[int]:
    sids: set[int] = set()
    for p in file_paths:
        sid = _scene_id_from_filename(p)
        if sid is not None:
            sids.add(sid)
    return sids


def _rerun_av_sync_for(state: dict, scene_ids: set[int]) -> list[str]:
    """Re-run av_sync_agent for affected scenes; return modified files."""
    try:
        from agents3.av_sync_agent import av_sync_agent
    except Exception as exc:
        print(f"    ⚠ Could not import av_sync_agent: {exc}")
        return []

    if not scene_ids:
        return []

    # Force these scenes to re-sync by deleting their existing synced outputs
    synced_dir = Path("outputs/video/synced")
    deleted: list[Path] = []
    if synced_dir.exists():
        for sid in scene_ids:
            for p in synced_dir.glob(f"scene_{sid:02d}_*_synced.mp4"):
                p.unlink(missing_ok=True)
                deleted.append(p)
            for p in synced_dir.glob(f"scene_{sid:02d}_*_synced.srt"):
                p.unlink(missing_ok=True)

    print(f"    ↻ Re-running av_sync for scene(s) {sorted(scene_ids)}")
    try:
        av_sync_agent(state)
    except Exception as exc:
        print(f"    ⚠ av_sync rerun failed: {exc}")

    modified = []
    for sid in scene_ids:
        modified.extend(str(p) for p in synced_dir.glob(f"scene_{sid:02d}_*_synced.*"))
    return modified


def _rerun_scene_merge_for(state: dict, scene_ids: set[int]) -> list[str]:
    try:
        from agents3.scene_merge_agent import scene_merge_agent
    except Exception as exc:
        print(f"    ⚠ Could not import scene_merge_agent: {exc}")
        return []

    if not scene_ids:
        return []

    scenes_dir = Path("outputs/video/scenes")
    if scenes_dir.exists():
        for sid in scene_ids:
            for p in scenes_dir.glob(f"scene_{sid:02d}_merged.mp4"):
                p.unlink(missing_ok=True)

    print(f"    ↻ Re-running scene_merge for scene(s) {sorted(scene_ids)}")
    try:
        scene_merge_agent(state)
    except Exception as exc:
        print(f"    ⚠ scene_merge rerun failed: {exc}")

    modified = []
    for sid in scene_ids:
        merged = scenes_dir / f"scene_{sid:02d}_merged.mp4"
        if merged.exists():
            modified.append(str(merged))
    return modified


def _rerun_compositor(state: dict) -> list[str]:
    try:
        from agents3.compositor_agent import compositor_agent
    except Exception as exc:
        print(f"    ⚠ Could not import compositor_agent: {exc}")
        return []

    final = Path("outputs/video/final_output.mp4")
    if final.exists():
        final.unlink()

    print(f"    ↻ Re-running compositor")
    try:
        compositor_agent(state)
    except Exception as exc:
        print(f"    ⚠ compositor rerun failed: {exc}")

    return [str(final)] if final.exists() else []


def _cascade_after_visual_change(
    state: dict,
    touched_clip_paths: list[str],
) -> list[str]:
    """
    After per-character clips/images have been modified, re-run:
      av_sync (to mux new audio/subs onto modified clips)
      scene_merge (to combine character clips into scene clip)
      compositor (to produce final_output.mp4)
    Returns all newly produced/modified files.
    """
    sids = _scenes_touched_by_files(touched_clip_paths)
    modified: list[str] = []
    modified += _rerun_av_sync_for(state, sids)
    modified += _rerun_scene_merge_for(state, sids)
    modified += _rerun_compositor(state)
    return modified


def _cascade_after_audio_change(state: dict, touched_audio_paths: list[str]) -> list[str]:
    """
    After per-character audio has changed, the av_sync stage must regenerate
    the synced character clips (which carry the audio track) and then we
    re-merge and recompose.
    """
    return _cascade_after_visual_change(state, touched_audio_paths)


# ─────────────────────────────────────────────────────────────────────────────
# EXECUTORS
# ─────────────────────────────────────────────────────────────────────────────

# ── apply_filter / make_scene_darker / make_scene_brighter ────────────────────

def _exec_apply_filter(state, intent):
    return _apply_filter_generic(state, intent, default_filters=["noir"])


def _exec_make_scene_darker(state, intent):
    return _apply_filter_generic(state, intent, default_filters=["darker"])


def _exec_make_scene_brighter(state, intent):
    return _apply_filter_generic(state, intent, default_filters=["brighter"])


def _apply_filter_generic(state, intent, default_filters: list[str]):
    scope    = intent.get("scope", "all")
    params   = intent.get("parameters", {})
    filters  = params.get("filters") or default_filters
    # Combine multiple filters into one ffmpeg vf chain
    vf_parts = [FILTER_PRESETS[f] for f in filters if f in FILTER_PRESETS]
    if not vf_parts:
        return state, [], f"⚠ No valid filters in {filters}"
    vf = ",".join(vf_parts)

    modified: list[str] = []
    image_dirs = [
        "outputs/images/characters",
        "outputs/images",
    ]

    # 1. Filter character images IN SCOPE
    img_files: list[str] = []
    for d in image_dirs:
        if os.path.isdir(d):
            img_files.extend(glob.glob(os.path.join(d, "*.png")))
            img_files.extend(glob.glob(os.path.join(d, "*.jpg")))
    img_files = sorted(set(img_files))

    n_img = 0
    for img in img_files:
        if not _file_in_scope(img, scope):
            continue
        if _apply_image_filter_to_file(img, vf):
            modified.append(img)
            n_img += 1
    print(f"    🖼  Filtered {n_img} image(s) in scope '{scope}'")

    # 2. Filter raw character video clips IN SCOPE
    clip_files = sorted(glob.glob("outputs/clips/*.mp4"))
    n_vid = 0
    for clip in clip_files:
        if not _file_in_scope(clip, scope):
            continue
        if _apply_video_filter_to_file(clip, vf):
            modified.append(clip)
            n_vid += 1
    print(f"    🎞  Filtered {n_vid} clip(s) in scope '{scope}'")

    # 3. Cascade — re-sync, re-merge, recompose so the change reaches the final
    #    video for the touched scenes.
    touched = [m for m in modified if m.endswith(".mp4") or m.endswith(".png")]
    cascade_files = _cascade_after_visual_change(state, touched)
    modified.extend(cascade_files)

    label = (
        f"Applied filter(s) {filters} to scope '{scope}' "
        f"({n_img} image(s), {n_vid} clip(s))"
    )
    new_state = {**state, "edit_applied": f"apply_filter:{','.join(filters)}"}
    return new_state, sorted(set(modified)), label


# ── change_voice_tone ─────────────────────────────────────────────────────────

# Tone → (speed, pitch) for espeak fallback;
# for edge-tts we use a SSML-style rate/pitch on each line.

_TONE_PARAMS = {
    "whispered": {"rate": "-15%", "pitch": "-10Hz", "volume": "-10%"},
    "whisper":   {"rate": "-15%", "pitch": "-10Hz", "volume": "-10%"},
    "soft":      {"rate": "-10%", "pitch": "-5Hz",  "volume": "-5%"},
    "deep":      {"rate": "-5%",  "pitch": "-25Hz", "volume": "0%"},
    "low":       {"rate": "-5%",  "pitch": "-25Hz", "volume": "0%"},
    "high":      {"rate": "+5%",  "pitch": "+25Hz", "volume": "0%"},
    "dramatic":  {"rate": "-5%",  "pitch": "-5Hz",  "volume": "+5%"},
    "calm":      {"rate": "-10%", "pitch": "-5Hz",  "volume": "0%"},
    "angry":     {"rate": "+10%", "pitch": "+5Hz",  "volume": "+10%"},
    "happy":     {"rate": "+5%",  "pitch": "+10Hz", "volume": "0%"},
    "sad":       {"rate": "-15%", "pitch": "-15Hz", "volume": "-5%"},
    "neutral":   {"rate": "+0%",  "pitch": "+0Hz",  "volume": "+0%"},
}


def _exec_change_voice_tone(state, intent):
    scope  = intent.get("scope", "all")
    params = intent.get("parameters", {})
    tone   = (params.get("tone") or "neutral").lower()
    tone_cfg = _TONE_PARAMS.get(tone, _TONE_PARAMS["neutral"])

    print(f"    🎙  Tone='{tone}' → rate={tone_cfg['rate']} pitch={tone_cfg['pitch']}")

    # Determine which (scene_id, character) pairs to re-synthesise
    targets: list[tuple[int, str]] = []
    task_graph = state.get("task_graph", [])

    if not task_graph:
        # Fall back to inferring from scene_manifest
        try:
            with open("outputs/scene_manifest.json", "r") as f:
                sm = json.load(f)
            scenes = sm.get("scenes", sm) if isinstance(sm, dict) else sm
            for s in scenes:
                sid = s.get("scene_id")
                for d in s.get("dialogue", []):
                    spk = d.get("speaker", "").strip()
                    if not spk:
                        continue
                    if _matches_scope(scope, sid, spk):
                        if (sid, spk) not in targets:
                            targets.append((sid, spk))
        except Exception as exc:
            return state, [], f"⚠ Could not load scene manifest: {exc}"
    else:
        for task in task_graph:
            sid = task["scene_id"]
            for clip in task.get("character_clips", []):
                char = clip.get("character_name", "")
                if _matches_scope(scope, sid, char):
                    targets.append((sid, char))

    if not targets:
        return state, [], f"⚠ No matching (scene, character) for scope '{scope}'"

    # Re-synthesise per-line WAVs for each target
    modified: list[str] = []
    audio_dir = state.get("audio_dir", "outputs/audio")
    os.makedirs(audio_dir, exist_ok=True)

    for sid, char in targets:
        wav_files = sorted(glob.glob(
            os.path.join(audio_dir, f"scene_{sid:02d}_{char}_line_*.wav")
        ))
        if not wav_files:
            # Try alternate naming
            wav_files = sorted(glob.glob(
                os.path.join(audio_dir, f"scene_{sid:02d}_{char.replace(' ', '_')}_line_*.wav")
            ))
        if not wav_files:
            print(f"    ⚠ No per-line WAVs found for scene {sid} · {char}")
            continue

        # Get the dialogue lines for this (scene, character)
        lines = _get_dialogue_lines_for(state, sid, char)
        if len(lines) != len(wav_files):
            print(f"    ⚠ Line count mismatch for scene {sid} · {char}: "
                  f"{len(lines)} vs {len(wav_files)} wav(s) — using min")

        n = min(len(lines), len(wav_files))
        for i in range(n):
            ok = _resynthesise_line(
                text=lines[i],
                out_wav=wav_files[i],
                tone_cfg=tone_cfg,
                character=char,
            )
            if ok:
                modified.append(wav_files[i])

        # Rebuild combined scene WAV if it exists
        scene_wav = os.path.join(audio_dir, f"scene_{sid:02d}.wav")
        if os.path.exists(scene_wav):
            _concat_wavs([w for w in wav_files], scene_wav)
            modified.append(scene_wav)

        print(f"    ✅ Scene {sid} · {char}: {n}/{len(wav_files)} line(s) re-synthesised")

    # Cascade: re-sync those scenes, re-merge, recompose
    cascade_files = _cascade_after_audio_change(state, modified)
    modified.extend(cascade_files)

    label = f"Voice tone='{tone}' for scope '{scope}' — {len(targets)} target(s)"
    return {**state, "edit_applied": f"change_voice_tone:{tone}"}, sorted(set(modified)), label


def _get_dialogue_lines_for(state: dict, sid: int, char: str) -> list[str]:
    """Pull the actual dialogue line texts for (scene, character)."""
    # Prefer task_graph (post-Phase-3 has full data)
    for task in state.get("task_graph", []):
        if task.get("scene_id") != sid:
            continue
        for clip in task.get("character_clips", []):
            if clip.get("character_name") == char:
                return [d.get("line", "") for d in clip.get("dialogue_lines", [])
                        if d.get("line", "").strip()]
        # Phase-2 task graph doesn't have character_clips — pull from dialogue
        out = []
        for d in task.get("dialogue", []):
            if d.get("speaker") == char:
                out.append(d.get("line", ""))
        if out:
            return [l for l in out if l.strip()]

    # Fallback: load scene_manifest from disk
    try:
        with open("outputs/scene_manifest.json", "r") as f:
            sm = json.load(f)
        scenes = sm.get("scenes", sm) if isinstance(sm, dict) else sm
        for s in scenes:
            if s.get("scene_id") != sid:
                continue
            return [d.get("line", "") for d in s.get("dialogue", [])
                    if d.get("speaker") == char and d.get("line", "").strip()]
    except Exception:
        pass
    return []


def _resynthesise_line(text: str, out_wav: str, tone_cfg: dict, character: str) -> bool:
    """
    Re-synthesise a single dialogue line into out_wav using the tone params.
    Tries edge-tts first (with rate/pitch/volume), falls back to espeak-ng.
    Replaces out_wav in-place.
    """
    if not text.strip():
        text = "..."

    # 1. Try edge-tts
    if _try_edge_tts(text, out_wav, tone_cfg, character):
        return True

    # 2. Fallback espeak-ng with mapped pitch/speed
    speed = 145
    pitch = 50
    rate_pct = _parse_pct(tone_cfg["rate"])
    pitch_hz = _parse_hz(tone_cfg["pitch"])
    speed   = max(80, min(220, int(speed * (1 + rate_pct / 100))))
    pitch   = max(0,  min(99,  int(pitch + pitch_hz)))
    return _try_espeak(text, out_wav, speed, pitch)


def _try_edge_tts(text: str, out_wav: str, tone_cfg: dict, character: str) -> bool:
    try:
        import edge_tts
        import asyncio
        import hashlib
    except ImportError:
        return False

    male_voices = [
        "en-US-GuyNeural", "en-GB-RyanNeural", "en-AU-WilliamNeural",
        "en-US-ChristopherNeural", "en-US-EricNeural", "en-GB-ThomasNeural",
        "en-IE-ConnorNeural", "en-US-RogerNeural", "en-NZ-MitchellNeural", "en-CA-LiamNeural",
    ]
    female_voices = [
        "en-US-JennyNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural",
        "en-US-AriaNeural", "en-US-MichelleNeural", "en-GB-LibbyNeural",
        "en-IE-EmilyNeural", "en-US-MonicaNeural", "en-NZ-MollyNeural", "en-CA-ClaraNeural",
    ]

    # Stable per-character voice (matches Phase 2 logic)
    idx = int(hashlib.md5(character.encode()).hexdigest(), 16) % len(male_voices)
    # Assume male if we can't tell — Phase 2 already wrote the original WAV
    voice = male_voices[idx]

    mp3_path = out_wav.replace(".wav", "_resyn.mp3")
    try:
        async def _run():
            comm = edge_tts.Communicate(
                text, voice,
                rate=tone_cfg["rate"],
                pitch=tone_cfg["pitch"],
                volume=tone_cfg["volume"],
            )
            await comm.save(mp3_path)

        try:
            asyncio.run(_run())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_run())
            finally:
                loop.close()

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) < 512:
            return False

        ok, _ = _ffmpeg("-i", mp3_path, out_wav, timeout=30)
        return ok and os.path.exists(out_wav) and os.path.getsize(out_wav) > 512

    except Exception as exc:
        print(f"      ⚠ edge-tts re-synth failed: {exc}")
        return False
    finally:
        if os.path.exists(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError:
                pass


def _try_espeak(text: str, out_wav: str, speed: int, pitch: int) -> bool:
    if not shutil.which("espeak-ng"):
        return False
    try:
        r = subprocess.run(
            ["espeak-ng", "-w", out_wav, "-p", str(pitch), "-s", str(speed), text],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception:
        return False


def _parse_pct(s: str) -> int:
    m = re.match(r"([+-]?\d+)%", s.strip())
    return int(m.group(1)) if m else 0


def _parse_hz(s: str) -> int:
    m = re.match(r"([+-]?\d+)Hz", s.strip())
    return int(m.group(1)) if m else 0


def _concat_wavs(paths: list[str], out: str) -> bool:
    """Concatenate WAVs into a single output WAV using stdlib wave."""
    frames, params = [], None
    for p in paths:
        if not os.path.exists(p):
            continue
        try:
            with wave.open(p, "r") as wf:
                if params is None:
                    params = wf.getparams()
                frames.append(wf.readframes(wf.getnframes()))
        except Exception:
            pass
    if not frames or params is None:
        return False
    with wave.open(out, "w") as wf:
        wf.setparams(params)
        for chunk in frames:
            wf.writeframes(chunk)
    return True


# ── speed_up_scene / slow_down ────────────────────────────────────────────────

def _exec_speed_up_scene(state, intent):
    scope    = intent.get("scope", "all")
    params   = intent.get("parameters", {})
    factor   = float(params.get("speed_factor", 1.5))
    if factor <= 0:
        factor = 1.0
    direction = params.get("direction", "faster" if factor > 1 else "slower")

    modified: list[str] = []

    # Speed-adjust per-character clips IN SCOPE
    clip_files = sorted(glob.glob("outputs/clips/*.mp4"))
    n_clips = 0
    for clip in clip_files:
        if not _file_in_scope(clip, scope):
            continue
        if _speed_adjust_clip(clip, factor):
            modified.append(clip)
            n_clips += 1

    # Speed-adjust the matching synced clips too
    synced_files = sorted(glob.glob("outputs/video/synced/*.mp4"))
    for syn in synced_files:
        if not _file_in_scope(syn, scope):
            continue
        if _speed_adjust_clip(syn, factor):
            modified.append(syn)

    print(f"    ⏩ Speed adjusted ({direction}, ×{factor:.2f}) for "
          f"{n_clips} clip(s) in scope '{scope}'")

    # If we changed synced clips, the existing merged scene clips are stale.
    # Re-run scene_merge to use the new synced ones (skipping av_sync since
    # the audio is already inside the synced clip).
    sids = _scenes_touched_by_files(modified)
    cascade = []
    cascade += _rerun_scene_merge_for(state, sids)
    cascade += _rerun_compositor(state)
    modified.extend(cascade)

    label = f"Scene speed {direction} (×{factor:.2f}) for scope '{scope}' — {n_clips} clip(s)"
    return {**state, "edit_applied": f"speed_{direction}:{factor}"}, sorted(set(modified)), label


def _speed_adjust_clip(clip_path: str, factor: float) -> bool:
    """Speed-adjust a video file in-place."""
    if not os.path.exists(clip_path):
        return False
    if abs(factor - 1.0) < 0.01:
        return False
    pts = 1.0 / factor

    # FFmpeg atempo accepts 0.5..2.0 only; chain if needed
    atempo_chain = _build_atempo_chain(factor)

    tmp = clip_path + ".tmp.mp4"
    ok, err = _ffmpeg(
        "-i", clip_path,
        "-filter_complex",
        f"[0:v]setpts={pts:.4f}*PTS[v];[0:a]{atempo_chain}[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        tmp,
        timeout=240,
    )
    if not ok:
        # Try without audio map (some clips may have no audio)
        ok, err2 = _ffmpeg(
            "-i", clip_path,
            "-vf", f"setpts={pts:.4f}*PTS",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-an",
            tmp,
            timeout=240,
        )
        if not ok:
            print(f"    ⚠ Speed adjust failed for {os.path.basename(clip_path)}: {err2 or err}")
            if os.path.exists(tmp):
                os.remove(tmp)
            return False

    if not os.path.exists(tmp) or os.path.getsize(tmp) < 1000:
        return False
    shutil.move(tmp, clip_path)
    return True


def _build_atempo_chain(factor: float) -> str:
    """Build an atempo filter chain that handles factors outside [0.5, 2.0]."""
    chain = []
    f = factor
    while f > 2.0:
        chain.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        chain.append("atempo=0.5")
        f /= 0.5
    chain.append(f"atempo={f:.4f}")
    return ",".join(chain)


# ── add_background_music ──────────────────────────────────────────────────────

def _exec_add_background_music(state, intent):
    params = intent.get("parameters", {})
    scope  = intent.get("scope", "all")
    volume = float(params.get("volume", 0.18))

    audio_dir = state.get("audio_dir", "outputs/audio")
    os.makedirs(audio_dir, exist_ok=True)
    bgm = os.path.join(audio_dir, "background_music.wav")

    # Generate a 30s ambient pad if no music file exists
    if not os.path.exists(bgm):
        ok, err = _ffmpeg(
            "-f", "lavfi",
            "-i", "sine=frequency=110:duration=30,sine=frequency=165:duration=30,sine=frequency=220:duration=30",
            "-filter_complex", "amix=inputs=3:duration=longest",
            "-af", "volume=0.4",
            "-ac", "1",
            bgm,
            timeout=60,
        )
        if not ok:
            return state, [], f"⚠ Could not generate background music: {err}"

    modified: list[str] = []
    wav_files = sorted(glob.glob(os.path.join(audio_dir, "scene_*.wav")))
    n = 0
    for wav in wav_files:
        if "_line_" in wav or "_combined" in wav or "background_music" in wav:
            continue
        if not _file_in_scope(wav, scope):
            continue
        tmp = wav + ".mix.wav"
        ok, err = _ffmpeg(
            "-i", wav,
            "-i", bgm,
            "-filter_complex",
            f"[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=0",
            "-c:a", "pcm_s16le",
            tmp,
            timeout=120,
        )
        if ok and os.path.exists(tmp):
            shutil.move(tmp, wav)
            modified.append(wav)
            n += 1

    print(f"    🎵 Mixed background music into {n} scene WAV(s)")

    # Cascade — re-sync, re-merge, recompose
    cascade = _cascade_after_audio_change(state, modified)
    modified.extend(cascade)

    label = f"Background music added (vol={volume}) for scope '{scope}' — {n} track(s)"
    return {**state, "edit_applied": "add_background_music"}, sorted(set(modified)), label


# ── remove_subtitle / add_subtitle (toggle) ──────────────────────────────────

def _exec_remove_subtitle(state, intent):
    params = intent.get("parameters", {})
    enable = bool(params.get("enable_subtitles", False))
    new_state = {**state, "enable_subtitles": enable,
                 "edit_applied": "subtitle_toggle"}

    # We can't easily strip burned subtitles from existing clips.
    # The honest approach: invalidate synced clips and re-run from av_sync.
    synced_dir = Path("outputs/video/synced")
    if synced_dir.exists():
        for p in synced_dir.glob("*_synced.mp4"):
            p.unlink(missing_ok=True)
    # If user wants subtitles OFF, also delete all .srt sidecars so av_sync skips burning
    if not enable:
        for p in synced_dir.glob("*.srt") if synced_dir.exists() else []:
            p.unlink(missing_ok=True)

    modified = _cascade_after_visual_change(new_state, [])

    label = ("Subtitles enabled" if enable else "Subtitles removed") + " — full rebuild"
    return new_state, sorted(set(modified)), label


# ── change_character_design ───────────────────────────────────────────────────

def _exec_change_character_design(state, intent):
    """Re-run image+video gen for the targeted character(s)/scene(s)."""
    scope = intent.get("scope", "all")
    params = intent.get("parameters", {})
    description = params.get("description", "") or ""

    # Update character_db if a description was provided
    if description:
        try:
            with open("outputs/character_db.json", "r") as f:
                chars = json.load(f)
            for c in chars:
                name = c.get("name", "")
                if scope.startswith("character:") and name.lower() == scope.split(":", 1)[1].lower():
                    c["appearance"] = (c.get("appearance", "") + " " + description).strip()
            with open("outputs/character_db.json", "w") as f:
                json.dump(chars, f, indent=2)
        except Exception:
            pass

    # Delete existing images/clips IN SCOPE so they get regenerated
    deleted_images: list[str] = []
    deleted_clips:  list[str] = []
    for img in glob.glob("outputs/images/characters/*.png"):
        if _file_in_scope(img, scope):
            os.remove(img)
            deleted_images.append(img)
    for clip in glob.glob("outputs/clips/*.mp4"):
        if _file_in_scope(clip, scope):
            os.remove(clip)
            deleted_clips.append(clip)

    print(f"    🗑  Deleted {len(deleted_images)} image(s), {len(deleted_clips)} clip(s) in scope")

    # Re-run image gen and video gen
    modified: list[str] = []
    try:
        from agents3.image_gen import image_gen_agent
        from agents3.ken_burns import ken_burns_agent
        image_gen_agent(state)
        ken_burns_agent(state)
        # Collect new files
        modified.extend(deleted_images)  # paths now repopulated
        modified.extend(deleted_clips)
    except Exception as exc:
        print(f"    ⚠ Re-generation failed: {exc}")

    # Cascade
    cascade = _cascade_after_visual_change(state, modified)
    modified.extend(cascade)

    label = f"Character design updated for scope '{scope}'"
    return {**state, "edit_applied": "change_character_design"}, sorted(set(modified)), label


# ── regenerate_script ─────────────────────────────────────────────────────────

def _exec_regenerate_script(state, intent):
    try:
        from mcp.registry import registry
        from mcp.init import register_tools
        register_tools()
        tool = registry.get_tool("generate_script_segment")
        n_scenes = len((state.get("script") or {}).get("scenes", [])) or 3
        new_script = tool({
            "prompt":     state.get("user_input", "Generate a thriller script."),
            "num_scenes": n_scenes,
        })
        os.makedirs("outputs", exist_ok=True)
        with open("outputs/scene_manifest.json", "w") as f:
            json.dump(new_script, f, indent=2)
        new_state = {**state, "script": new_script,
                     "edit_applied": "regenerate_script"}
        return new_state, ["outputs/scene_manifest.json"], "Script regenerated"
    except Exception as exc:
        return state, [], f"⚠ Script regeneration failed: {exc}"


# ── change_dialogue ───────────────────────────────────────────────────────────

def _exec_change_dialogue(state, intent):
    params = intent.get("parameters", {})
    new_text = params.get("new_text") or params.get("description", "")
    scope    = intent.get("scope", "all")

    try:
        with open("outputs/scene_manifest.json", "r") as f:
            sm = json.load(f)
    except Exception as exc:
        return state, [], f"⚠ Could not load scene manifest: {exc}"

    scenes = sm.get("scenes", sm) if isinstance(sm, dict) else sm
    n = 0
    for s in scenes:
        sid = s.get("scene_id")
        for d in s.get("dialogue", []):
            if _matches_scope(scope, sid, d.get("speaker", "")):
                if new_text:
                    d["line"] = new_text
                    n += 1
                    break  # change only the first matching line
        if n > 0:
            break

    with open("outputs/scene_manifest.json", "w") as f:
        json.dump(sm if isinstance(sm, dict) else {"scenes": scenes}, f, indent=2)

    new_state = {**state, "script": sm if isinstance(sm, dict) else {"scenes": scenes},
                 "edit_applied": "change_dialogue"}
    return new_state, ["outputs/scene_manifest.json"], f"Dialogue updated ({n} line(s))"


# ── recompose_video ───────────────────────────────────────────────────────────

def _exec_recompose_video(state, intent):
    modified = _rerun_compositor(state)
    return {**state, "edit_applied": "recompose"}, modified, "Video recomposed"


# ── Dispatch table ────────────────────────────────────────────────────────────

_DISPATCH = {
    "apply_filter":            _exec_apply_filter,
    "make_scene_darker":       _exec_make_scene_darker,
    "make_scene_brighter":     _exec_make_scene_brighter,
    "change_voice_tone":       _exec_change_voice_tone,
    "speed_up_scene":          _exec_speed_up_scene,
    "add_background_music":    _exec_add_background_music,
    "remove_subtitle":         _exec_remove_subtitle,
    "add_subtitle":            _exec_remove_subtitle,
    "change_character_design": _exec_change_character_design,
    "regenerate_script":       _exec_regenerate_script,
    "change_dialogue":         _exec_change_dialogue,
    "recompose_video":         _exec_recompose_video,
}