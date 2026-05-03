# mcp/tools3.py
"""
Phase 3 MCP Tools  —  Video Generation & Composition
──────────────────────────────────────────────────────
Tools:
  1. image_generator       — generates a still image per scene via DALL-E or SD
  2. scene_animator        — applies Ken Burns / zoom-pan to produce an animated clip
  3. av_compositor         — syncs audio to visual clips + builds final MP4
  4. commit_memory         — write entries to vector store

Image backend priority: DALL-E 3 (if OPENAI_API_KEY set) → Stable Diffusion
                         (if SD_API_URL set) → solid-colour placeholder
Animation backend: FFmpeg (required); MoviePy as helper for duration queries
Composition: FFmpeg concat + overlay pipeline
"""

import os
import re
import json
import time
import wave
import shutil
import hashlib
import subprocess
import urllib.request
from typing import Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import openai as _openai
    HAS_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
except ImportError:
    HAS_OPENAI = False

# ── Config ────────────────────────────────────────────────────────────────────
SD_API_URL     = os.getenv("SD_API_URL", "")          # e.g. http://127.0.0.1:7860
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OUTPUT_DIR     = "outputs/video"

# Transition duration between scenes (seconds)
TRANSITION_SECS = 1.0

# Ken Burns constants
KB_ZOOM_FACTOR  = 1.08   # 8 % zoom over the full clip duration
IMAGE_W, IMAGE_H = 1280, 720

# ── Tool schemas ──────────────────────────────────────────────────────────────
TOOL_SCHEMAS_3 = {
    "image_generator": {
        "tool": "image_generator",
        "input_schema": {
            "scene_id":   "int",
            "prompt":     "str — visual description for image generation",
            "style":      "str — optional style hint",
            "output_dir": "str",
        },
    },
    "scene_animator": {
        "tool": "scene_animator",
        "input_schema": {
            "scene_id":   "int",
            "image_path": "str",
            "duration":   "float — clip length in seconds",
            "output_dir": "str",
            "kb_style":   "str — zoom_in | zoom_out | pan_left | pan_right (auto if omitted)",
        },
    },
    "av_compositor": {
        "tool": "av_compositor",
        "input_schema": {
            "scene_videos":   "list[SceneVideo]",
            "output_path":    "str",
            "add_subtitles":  "bool",
            "timing_manifest":"list",
        },
    },
    "commit_memory": {
        "tool": "commit_memory",
        "input_schema": {"text": "str", "metadata": "dict"},
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


def _ffmpeg(*args, **kwargs) -> subprocess.CompletedProcess:
    """Run ffmpeg quietly, raising on non-zero exit."""
    cmd = ["ffmpeg", "-y"] + list(args)
    return subprocess.run(cmd, capture_output=True, check=True, timeout=300, **kwargs)


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _wav_duration(path: str) -> float:
    """Return WAV duration in seconds, or 4.0 as fallback."""
    try:
        with wave.open(path, "r") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 4.0


def _stable_color(scene_id: int) -> str:
    """Derive a unique background colour from scene_id for placeholder images."""
    palette = [
        "0f1923", "1a0f23", "231a0f", "0f230f",
        "23100f", "0f1f23", "1a230f", "200f23",
    ]
    return palette[scene_id % len(palette)]


def _kb_style_for(scene_id: int) -> str:
    styles = ["zoom_in", "zoom_out", "pan_left", "pan_right"]
    return styles[scene_id % len(styles)]


# ── Image prompt engineering ──────────────────────────────────────────────────

def _build_image_prompt(scene: dict, characters: list) -> str:
    location   = scene.get("location", "cinematic location")
    visual_cues = []
    for turn in scene.get("dialogue", []):
        cue = turn.get("visual_cue", "").strip()
        if cue:
            visual_cues.append(cue)

    char_names = scene.get("characters", [])
    char_desc_parts = []
    char_map = {c.get("name", ""): c for c in characters}
    for name in char_names:
        meta = char_map.get(name, {})
        appearance = meta.get("appearance", "")
        if appearance:
            char_desc_parts.append(f"{name}: {appearance}")

    prompt_parts = [
        f"Cinematic still frame, {location}.",
    ]
    if char_desc_parts:
        prompt_parts.append("Characters: " + "; ".join(char_desc_parts) + ".")
    if visual_cues:
        prompt_parts.append("Visual direction: " + " ".join(visual_cues[:2]) + ".")
    prompt_parts += [
        "Dramatic lighting, film grain, anamorphic lens, 16:9 aspect ratio.",
        "High detail, professional cinematography, award-winning photograph.",
    ]

    style = char_map.get(char_names[0], {}).get("style", "cinematic") if char_names else "cinematic"
    prompt_parts.append(f"Style: {style}.")

    return " ".join(prompt_parts)


# ── Backend: DALL-E 3 ─────────────────────────────────────────────────────────

def _generate_dalle(prompt: str, out_path: str) -> bool:
    if not HAS_OPENAI or not OPENAI_API_KEY:
        return False
    try:
        client = _openai.OpenAI(api_key=OPENAI_API_KEY)
        resp = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",
            quality="standard",
            n=1,
        )
        url = resp.data[0].url
        urllib.request.urlretrieve(url, out_path)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    except Exception as e:
        print(f"  ⚠ DALL-E 3 failed: {e}")
        return False


# ── Backend: Stable Diffusion (Automatic1111 / ComfyUI REST) ─────────────────

def _generate_sd(prompt: str, out_path: str) -> bool:
    if not SD_API_URL or not HAS_REQUESTS:
        return False
    try:
        payload = {
            "prompt":          prompt,
            "negative_prompt": "blurry, low quality, cartoon, anime, text, watermark",
            "width":           IMAGE_W,
            "height":          IMAGE_H,
            "steps":           25,
            "cfg_scale":       7.5,
            "sampler_name":    "DPM++ 2M Karras",
        }
        r = _requests.post(
            f"{SD_API_URL.rstrip('/')}/sdapi/v1/txt2img",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        import base64
        img_b64 = r.json()["images"][0]
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(img_b64))
        return os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    except Exception as e:
        print(f"  ⚠ Stable Diffusion failed: {e}")
        return False


# ── Backend: FFmpeg placeholder (solid colour + text) ────────────────────────

def _generate_placeholder(scene_id: int, location: str, out_path: str) -> bool:
    """Generate a minimal cinematic placeholder image with FFmpeg."""
    if not _has_ffmpeg():
        return False
    try:
        color   = _stable_color(scene_id)
        label   = location[:40].replace("'", "")
        caption = f"Scene {scene_id}\\n{label}"
        _ffmpeg(
            "-f",    "lavfi",
            "-i",    f"color=0x{color}:s={IMAGE_W}x{IMAGE_H}:d=1",
            "-vf",   (
                f"drawtext=fontcolor=0xc9a84c:fontsize=36:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:text='{caption}'"
            ),
            "-frames:v", "1",
            out_path,
        )
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        print(f"  ⚠ Placeholder generation failed: {e}")
        return False


# ─── TOOL 1: Image Generator ─────────────────────────────────────────────────

def image_generator(input_data: Dict) -> Dict:
    scene_id   = input_data["scene_id"]
    prompt     = input_data["prompt"]
    output_dir = input_data.get("output_dir", OUTPUT_DIR)
    _ensure_dir(output_dir)

    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}.png")

    # Try backends in priority order
    if _generate_dalle(prompt, out_path):
        method = "dalle3"
    elif _generate_sd(prompt, out_path):
        method = "stable_diffusion"
    else:
        location = input_data.get("location", f"Scene {scene_id}")
        _generate_placeholder(scene_id, location, out_path)
        method = "placeholder"

    success = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    print(f"  🖼  Scene {scene_id} image → {out_path}  [{method}]")

    return {
        "scene_id":   scene_id,
        "image_path": out_path if success else None,
        "method":     method,
        "status":     "done" if success else "error",
    }


# ─── TOOL 2: Scene Animator (Ken Burns via FFmpeg) ───────────────────────────

def scene_animator(input_data: Dict) -> Dict:
    """
    Applies a Ken Burns (zoom / pan) effect to a still image, producing a
    short MP4 clip of the specified duration.  Uses pure FFmpeg zoompan filter.
    """
    scene_id   = input_data["scene_id"]
    image_path = input_data["image_path"]
    duration   = max(float(input_data.get("duration", 4.0)), 2.0)
    output_dir = input_data.get("output_dir", OUTPUT_DIR)
    kb_style   = input_data.get("kb_style") or _kb_style_for(scene_id)
    _ensure_dir(output_dir)

    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}_clip.mp4")

    if not image_path or not os.path.exists(image_path):
        print(f"  ⚠ Scene {scene_id}: image not found — generating placeholder clip")
        # Write a silent black MP4 as fallback
        try:
            _ffmpeg(
                "-f",    "lavfi",
                "-i",    f"color=black:s={IMAGE_W}x{IMAGE_H}:d={duration:.2f}",
                "-c:v",  "libx264", "-pix_fmt", "yuv420p",
                out_path,
            )
        except Exception:
            pass
        return {"scene_id": scene_id, "video_clip": out_path,
                "status": "done", "kb_style": "none"}

    fps    = 25
    frames = int(duration * fps)

    # ── zoompan filter expressions per style ─────────────────────────────────
    W, H = IMAGE_W, IMAGE_H

    if kb_style == "zoom_in":
        zoom_expr = f"'if(lte(zoom,1.0),1.0,zoom-0.{int((KB_ZOOM_FACTOR-1)*10000):04d})'"
        # Actually: start at 1.0 → end at KB_ZOOM_FACTOR
        zoom_expr  = f"'1.0+((zoom-1.0)+{(KB_ZOOM_FACTOR-1)/frames:.6f})*on'"
        # Simpler, reliable approach:
        zoom_expr  = f"'zoom+{(KB_ZOOM_FACTOR-1)/frames:.6f}'"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    elif kb_style == "zoom_out":
        start_zoom = KB_ZOOM_FACTOR
        zoom_expr  = f"'{start_zoom:.4f}-on*{(KB_ZOOM_FACTOR-1)/frames:.6f}'"
        x_expr, y_expr = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    elif kb_style == "pan_left":
        zoom_expr = "1.04"
        x_expr    = f"'(iw-iw/zoom)*on/{frames}'"
        y_expr    = "ih/2-(ih/zoom/2)"

    else:  # pan_right
        zoom_expr = "1.04"
        x_expr    = f"'(iw-iw/zoom)*(1-on/{frames})'"
        y_expr    = "ih/2-(ih/zoom/2)"

    zoompan_filter = (
        f"scale={W*2}:{H*2},"
        f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
        f":d={frames}:s={W}x{H}:fps={fps},"
        f"trim=duration={duration:.3f},"
        f"setpts=PTS-STARTPTS"
    )

    try:
        _ffmpeg(
            "-loop",   "1",
            "-i",      image_path,
            "-vf",     zoompan_filter,
            "-c:v",    "libx264",
            "-pix_fmt","yuv420p",
            "-t",      f"{duration:.3f}",
            "-r",      str(fps),
            out_path,
        )
        success = os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except subprocess.CalledProcessError as e:
        print(f"  ⚠ FFmpeg zoompan failed (scene {scene_id}): {e.stderr.decode()[-300:]}")
        # Fallback: simple static clip (no zoom)
        try:
            _ffmpeg(
                "-loop",   "1",
                "-i",      image_path,
                "-vf",     f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                           f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2",
                "-c:v",    "libx264",
                "-pix_fmt","yuv420p",
                "-t",      f"{duration:.3f}",
                "-r",      str(fps),
                out_path,
            )
            success = os.path.exists(out_path) and os.path.getsize(out_path) > 0
        except Exception as e2:
            print(f"  ❌ Fallback clip failed (scene {scene_id}): {e2}")
            success = False

    print(f"  🎞  Scene {scene_id} clip → {out_path}  [{kb_style}, {duration:.1f}s]")
    return {
        "scene_id":   scene_id,
        "video_clip": out_path if success else None,
        "kb_style":   kb_style,
        "duration":   duration,
        "status":     "done" if success else "error",
    }


# ─── TOOL 3: A/V Compositor ──────────────────────────────────────────────────

def _build_subtitles(timing_manifest: List[Dict], srt_path: str):
    """Write a .srt subtitle file from the timing manifest."""
    def ms_to_srt(ms: float) -> str:
        ms = int(ms)
        h, ms  = divmod(ms, 3_600_000)
        m, ms  = divmod(ms, 60_000)
        s, ms  = divmod(ms, 1_000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, entry in enumerate(timing_manifest, start=1):
            start = ms_to_srt(entry.get("start_ms", 0))
            end   = ms_to_srt(entry.get("end_ms",   2000))
            speaker = entry.get("speaker", "")
            line    = entry.get("line", "").strip()
            text    = f"{speaker}: {line}" if speaker else line
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def av_compositor(input_data: Dict) -> Dict:
    """
    Merge per-scene animated clips with their audio tracks, apply cross-fade
    transitions, optionally burn subtitles, and produce the final MP4.

    Steps
    ─────
    1. For each scene: mux video clip + audio WAV → muxed_scene_XX.mp4
    2. Build a concat list and merge with xfade transitions
    3. Optionally burn SRT subtitles onto the final video
    """
    scene_videos   = input_data["scene_videos"]
    output_path    = input_data.get("output_path", "outputs/video/final_output.mp4")
    add_subtitles  = input_data.get("add_subtitles", True)
    timing_manifest= input_data.get("timing_manifest", [])

    _ensure_dir(os.path.dirname(output_path))
    tmp_dir = os.path.join(os.path.dirname(output_path), "_tmp")
    _ensure_dir(tmp_dir)

    # ── Step 1: mux each scene's video + audio ────────────────────────────────
    muxed_clips = []
    for sv in scene_videos:
        sid        = sv["scene_id"]
        video_clip = sv.get("video_clip")
        audio_path = sv.get("audio_path")
        muxed      = os.path.join(tmp_dir, f"muxed_{sid:02d}.mp4")

        if not video_clip or not os.path.exists(video_clip):
            print(f"  ⚠ Scene {sid}: missing video clip — skipping")
            continue

        if audio_path and os.path.exists(audio_path):
            try:
                audio_dur = sv.get("duration", _wav_duration(audio_path))
                _ffmpeg(
                    "-i",      video_clip,
                    "-i",      audio_path,
                    # Trim / pad video to match audio length exactly
                    "-vf",     f"trim=0:{audio_dur:.3f},setpts=PTS-STARTPTS",
                    "-af",     f"apad,atrim=0:{audio_dur:.3f}",
                    "-c:v",    "libx264", "-pix_fmt", "yuv420p",
                    "-c:a",    "aac", "-b:a", "192k",
                    "-shortest",
                    muxed,
                )
                print(f"  🔗 Scene {sid}: video+audio muxed → {muxed}")
            except subprocess.CalledProcessError as e:
                print(f"  ⚠ Scene {sid} mux failed, using video-only: "
                      f"{e.stderr.decode()[-200:]}")
                shutil.copy(video_clip, muxed)
        else:
            # No audio — just copy the video clip
            shutil.copy(video_clip, muxed)
            print(f"  ℹ Scene {sid}: no audio found — video-only clip used")

        if os.path.exists(muxed):
            muxed_clips.append((sid, muxed))

    if not muxed_clips:
        raise RuntimeError("No muxed clips produced — cannot compose final video")

    # ── Step 2: concatenate with xfade transitions ────────────────────────────
    pre_subtitle = os.path.join(tmp_dir, "pre_subtitle.mp4")

    if len(muxed_clips) == 1:
        shutil.copy(muxed_clips[0][1], pre_subtitle)
    else:
        # Build a chain of xfade filters for smooth cross-fades
        # First get durations of each muxed clip
        def _clip_duration(path: str) -> float:
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error",
                     "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1",
                     path],
                    capture_output=True, text=True, timeout=30,
                )
                return float(r.stdout.strip())
            except Exception:
                return 4.0

        durations = [_clip_duration(p) for _, p in muxed_clips]

        # Construct ffmpeg xfade chain
        inputs = []
        for _, p in muxed_clips:
            inputs += ["-i", p]

        # Build filter_complex for N clips
        n = len(muxed_clips)
        td = TRANSITION_SECS
        fc_parts = []
        # Label first input
        prev_v = "[0:v]"
        prev_a = "[0:a]"

        for i in range(1, n):
            offset = sum(durations[:i]) - td * i
            offset = max(offset, 0.01)
            out_v  = f"[xv{i}]"
            out_a  = f"[xa{i}]"
            fc_parts.append(
                f"{prev_v}[{i}:v]xfade=transition=fade:duration={td}:offset={offset:.3f}{out_v}"
            )
            fc_parts.append(
                f"{prev_a}[{i}:a]acrossfade=d={td}{out_a}"
            )
            prev_v = out_v
            prev_a = out_a

        filter_complex = ";".join(fc_parts)
        cmd = (
            inputs
            + ["-filter_complex", filter_complex,
               "-map", prev_v,
               "-map", prev_a,
               "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k",
               pre_subtitle]
        )
        try:
            _ffmpeg(*cmd)
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ xfade chain failed — falling back to simple concat: "
                  f"{e.stderr.decode()[-200:]}")
            # Simple concat fallback
            list_file = os.path.join(tmp_dir, "concat.txt")
            with open(list_file, "w") as f:
                for _, p in muxed_clips:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            _ffmpeg(
                "-f",      "concat",
                "-safe",   "0",
                "-i",      list_file,
                "-c:v",    "libx264", "-pix_fmt", "yuv420p",
                "-c:a",    "aac", "-b:a", "192k",
                pre_subtitle,
            )

    # ── Step 3: optional subtitle burn-in ─────────────────────────────────────
    if add_subtitles and timing_manifest:
        srt_path = os.path.join(tmp_dir, "subtitles.srt")
        _build_subtitles(timing_manifest, srt_path)
        try:
            srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")
            _ffmpeg(
                "-i",   pre_subtitle,
                "-vf",  (
                    f"subtitles='{srt_escaped}'"
                    f":force_style='FontName=Arial,FontSize=18,"
                    f"PrimaryColour=&H00F0E6CC,OutlineColour=&H000F0F0F,"
                    f"Outline=2,Shadow=1,Alignment=2'"
                ),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                output_path,
            )
            print(f"  📝 Subtitles burned in from {srt_path}")
        except subprocess.CalledProcessError as e:
            print(f"  ⚠ Subtitle burn-in failed — using un-subtitled video: "
                  f"{e.stderr.decode()[-200:]}")
            shutil.copy(pre_subtitle, output_path)
    else:
        shutil.copy(pre_subtitle, output_path)

    # Cleanup temp files
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    success = os.path.exists(output_path) and os.path.getsize(output_path) > 0
    size_mb = os.path.getsize(output_path) / 1_048_576 if success else 0
    print(f"  🎬 Final video → {output_path}  ({size_mb:.1f} MB)")

    return {
        "output_path": output_path if success else None,
        "size_mb":     round(size_mb, 2),
        "scene_count": len(muxed_clips),
        "subtitles":   add_subtitles and bool(timing_manifest),
        "status":      "done" if success else "error",
    }


# ─── TOOL 4: commit_memory ────────────────────────────────────────────────────

def commit_memory_p3(input_data: Dict) -> Dict:
    try:
        from memory.vector_store import store_memory
        store_memory(text=input_data["text"], metadata=input_data.get("metadata", {}))
        return {"status": "stored"}
    except Exception as e:
        print(f"  ⚠ Memory commit skipped: {e}")
        return {"status": "skipped", "reason": str(e)}