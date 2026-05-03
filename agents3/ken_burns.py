# agents3/ken_burns.py
"""
Ken Burns Agent  —  Phase 3
─────────────────────────────
Converts each scene's base image into an animated video clip by rendering
every single frame individually via PIL, then encoding them into an MP4
with MoviePy.

Frame-by-frame pipeline per scene:
  1. Load base image (outputs/images/scene_XX.png)
  2. For each frame t ∈ [0, duration * FPS]:
       a. Compute zoom level and pan offset using a smooth easing curve
       b. Crop the zoomed region from the source image
       c. Resize crop back to output resolution
       d. Apply per-frame effects: subtle vignette, slight brightness drift
       e. Write frame to outputs/frames/scene_XX/frame_NNNNN.png
  3. Encode frame sequence → outputs/clips/scene_XX.mp4 via MoviePy

Motion presets (cycle per scene):
  - ZOOM_IN_CENTER   : slow zoom into centre
  - ZOOM_IN_LEFT     : zoom + pan right (left-anchored)
  - ZOOM_IN_RIGHT    : zoom + pan left (right-anchored)
  - PAN_LEFT_TO_RIGHT: horizontal pan at fixed zoom
  - PAN_RIGHT_TO_LEFT: reverse horizontal pan
"""

from __future__ import annotations
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

# ── Constants ─────────────────────────────────────────────────────────────────
FPS        = 24
OUT_W      = 1280
OUT_H      = 720
CLIPS_DIR  = Path("outputs/clips")
FRAMES_DIR = Path("outputs/frames")

# Motion preset definitions: (zoom_start, zoom_end, pan_x_start, pan_x_end, pan_y_start, pan_y_end)
# Zoom values are multipliers on the crop size (1.0 = full image, 1.3 = 30% zoomed in)
MOTION_PRESETS = [
    # name               z0    z1    px0   px1   py0   py1
    ("ZOOM_IN_CENTER",   1.0,  1.25, 0.5,  0.5,  0.5,  0.5),
    ("ZOOM_IN_LEFT",     1.0,  1.30, 0.3,  0.5,  0.5,  0.5),
    ("ZOOM_IN_RIGHT",    1.0,  1.30, 0.7,  0.5,  0.5,  0.5),
    ("PAN_L_TO_R",       1.15, 1.15, 0.25, 0.75, 0.5,  0.5),
    ("PAN_R_TO_L",       1.15, 1.15, 0.75, 0.25, 0.5,  0.5),
    ("ZOOM_OUT_CENTER",  1.30, 1.0,  0.5,  0.5,  0.5,  0.5),
    ("DIAGONAL_DRIFT",   1.10, 1.25, 0.3,  0.6,  0.4,  0.6),
]


# ── Easing ────────────────────────────────────────────────────────────────────
def _ease_in_out(t: float) -> float:
    """Smooth cubic ease-in-out: 0 → 1."""
    return t * t * (3.0 - 2.0 * t)


# ── Single frame renderer ─────────────────────────────────────────────────────
def _render_frame(src_img, t_norm: float, preset: tuple, frame_idx: int):
    """
    Render one frame.

    Args:
        src_img:   PIL Image (the base scene image, large enough to crop from)
        t_norm:    normalised time 0.0 → 1.0
        preset:    motion preset tuple
        frame_idx: frame number (used for subtle flicker)

    Returns:
        PIL Image of size (OUT_W, OUT_H)
    """
    from PIL import Image, ImageEnhance, ImageFilter

    _, z0, z1, px0, px1, py0, py1 = preset
    ease = _ease_in_out(t_norm)

    zoom   = z0 + (z1 - z0) * ease
    pan_x  = px0 + (px1 - px0) * ease
    pan_y  = py0 + (py1 - py0) * ease

    src_w, src_h = src_img.size

    # Crop window size (smaller = more zoomed in)
    crop_w = int(src_w / zoom)
    crop_h = int(src_h / zoom)

    # Crop centre position
    cx = int(pan_x * src_w)
    cy = int(pan_y * src_h)

    # Clamp crop box inside source
    x0 = max(0, min(cx - crop_w // 2, src_w - crop_w))
    y0 = max(0, min(cy - crop_h // 2, src_h - crop_h))
    x1 = x0 + crop_w
    y1 = y0 + crop_h

    frame = src_img.crop((x0, y0, x1, y1)).resize((OUT_W, OUT_H), Image.LANCZOS)

    # Subtle brightness drift (film breathing effect, ±2%)
    breath = 1.0 + 0.02 * math.sin(frame_idx * 0.15)
    frame  = ImageEnhance.Brightness(frame).enhance(breath)

    # Very light vignette burned into every frame
    if not hasattr(_render_frame, "_vignette"):
        vig = Image.new("RGBA", (OUT_W, OUT_H), (0, 0, 0, 0))
        from PIL import ImageDraw
        vd = ImageDraw.Draw(vig)
        for i in range(60):
            alpha = int(120 * (i / 60) ** 2)
            vd.rectangle([i, i, OUT_W - i, OUT_H - i], outline=(0, 0, 0, alpha))
        _render_frame._vignette = vig

    composited = Image.alpha_composite(frame.convert("RGBA"),
                                       _render_frame._vignette)
    return composited.convert("RGB")


# ── Scene processor ───────────────────────────────────────────────────────────
def _process_scene(sv: dict, preset: tuple) -> str | None:
    """
    Render all frames for one scene and encode to MP4.
    Returns output clip path, or None on error.
    """
    from PIL import Image

    sid        = sv["scene_id"]
    image_path = sv.get("image_path")
    duration   = sv.get("duration", 5.0)

    if not image_path or not Path(image_path).exists():
        print(f"  ❌ Scene {sid}: no base image found at {image_path}")
        return None

    # Output paths
    clip_path   = CLIPS_DIR / f"scene_{sid:02d}.mp4"
    frames_dir  = FRAMES_DIR / f"scene_{sid:02d}"
    frames_dir.mkdir(parents=True, exist_ok=True)
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    total_frames = max(int(duration * FPS), 1)
    print(f"  [Scene {sid}] Rendering {total_frames} frames "
          f"({duration:.1f}s @ {FPS}fps) — preset: {preset[0]}")

    # Load source image — upscale slightly so Ken Burns has room to crop
    src = Image.open(image_path).convert("RGB")
    # Upscale source to 1.5× so zoom crops never go out of bounds
    src = src.resize((int(src.width * 1.5), int(src.height * 1.5)), Image.LANCZOS)

    frame_paths = []
    for i in range(total_frames):
        t_norm     = i / max(total_frames - 1, 1)
        frame_img  = _render_frame(src, t_norm, preset, i)
        frame_file = frames_dir / f"frame_{i:05d}.png"
        frame_img.save(str(frame_file), "PNG", optimize=False)
        frame_paths.append(str(frame_file))

        if i % FPS == 0:   # progress every second
            print(f"    frame {i+1}/{total_frames} …")

    print(f"  [Scene {sid}] ✅ {total_frames} frames written — encoding MP4…")

    # ── Encode with MoviePy ───────────────────────────────────────────────────
    try:
        from moviepy.editor import ImageSequenceClip
        clip = ImageSequenceClip(frame_paths, fps=FPS)
        clip.write_videofile(
            str(clip_path),
            fps=FPS,
            codec="libx264",
            preset="fast",
            ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p"],
            logger=None,
        )
        clip.close()
    except Exception as exc:
        # Fallback: use ffmpeg directly via subprocess
        print(f"  ⚠  MoviePy encode failed ({exc}) — trying ffmpeg subprocess…")
        import subprocess
        pattern = str(frames_dir / "frame_%05d.png")
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", pattern,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(clip_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ❌ ffmpeg failed: {result.stderr[-300:]}")
            return None

    # Clean up frames to save disk (optional — comment out to keep frames)
    for fp in frame_paths:
        try:
            os.remove(fp)
        except OSError:
            pass

    print(f"  ✅ Scene {sid} clip → {clip_path}")
    return str(clip_path)


# ── Agent entry point ─────────────────────────────────────────────────────────
def ken_burns_agent(state: "Phase3State") -> "Phase3State":
    print("\n[Phase3][KenBurns] Rendering frame-by-frame Ken Burns animations…")
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    scene_videos = state.get("scene_videos", [])
    errors = 0

    for idx, sv in enumerate(scene_videos):
        sid       = sv["scene_id"]
        clip_path = CLIPS_DIR / f"scene_{sid:02d}.mp4"

        if clip_path.exists() and clip_path.stat().st_size > 10_000:
            print(f"  ⏭  Scene {sid}: clip already exists — skipping")
            sv["video_clip"] = str(clip_path)
            if sv["status"] == "image_done":
                sv["status"] = "clip_done"
            continue

        preset = MOTION_PRESETS[idx % len(MOTION_PRESETS)]
        result = _process_scene(sv, preset)

        if result:
            sv["video_clip"] = result
            sv["status"]     = "clip_done"
        else:
            sv["status"] = "error"
            sv["error"]  = "Ken Burns rendering failed"
            errors += 1

    ok = len(scene_videos) - errors
    print(f"[Phase3][KenBurns] Complete — {ok} clips rendered, {errors} errors\n")
    return {**state, "scene_videos": scene_videos}