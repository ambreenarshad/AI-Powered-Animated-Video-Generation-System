"""
agents3/ken_burns.py
─────────────────────
Per-character video generation using Wan Image-to-Video (I2V) models.

Correct DashScope International model IDs for video generation:
  Primary:   wan2.7-i2v-2026-04-25   ← Latest Wan2.7 I2V (April 2025 release)
  Fallback1: wan2.7-i2v              ← Wan2.7 I2V stable
  Fallback2: wan2.5-i2v-preview      ← Wan2.5 I2V Preview
  Fallback3: wan2.2-i2v-plus         ← Wan2.2 I2V Plus (proven working)
  Fallback4: wan2.1-i2v-plus         ← Wan2.1 I2V Plus (widest availability)
  Fallback5: wan2.1-i2v-turbo        ← Wan2.1 I2V Turbo (fastest)

NOTE: Model IDs on DashScope use lowercase with hyphens.
      "wan2.6-i2v-plus" does NOT exist — the correct IDs are above.
      Always verify at: https://help.aliyun.com/zh/model-studio/
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from state3 import Phase3State

# ── Config ────────────────────────────────────────────────────────────────────
dashscope_base = "https://dashscope-intl.aliyuncs.com/api/v1"

I2V_SUBMIT_URL = (
    f"{dashscope_base}/services/aigc/video-generation/video-synthesis"
)
TASK_QUERY_URL = f"{dashscope_base}/tasks/{{task_id}}"

# Model priority list — tries each in order until one succeeds
I2V_MODELS = [
    "wan2.7-i2v-2026-04-25",   # Latest Wan2.7 I2V (best quality)
    "wan2.7-i2v",              # Wan2.7 I2V stable
    "wan2.5-i2v-preview",      # Wan2.5 I2V Preview
    "wan2.2-i2v-plus",         # Wan2.2 I2V Plus (proven)
    "wan2.2-i2v-flash",        # Wan2.2 I2V Flash (fast)
    "wan2.1-i2v-plus",         # Wan2.1 I2V Plus (wide availability)
    "wan2.1-i2v-turbo",        # Wan2.1 I2V Turbo (fastest fallback)
]

CLIPS_DIR     = Path("outputs/clips")
POLL_INTERVAL = 8     # seconds between polls
MAX_WAIT      = 600   # 10 minutes max per clip


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_base64_data_uri(image_path: str) -> str:
    """Read image and return a base64 data URI."""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")

    # Detect format from file extension
    ext = Path(image_path).suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{data}"


def _poll_task(task_id: str, api_key: str) -> dict:
    """Poll until SUCCEEDED or FAILED. Returns output dict."""
    url     = TASK_QUERY_URL.format(task_id=task_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0

    while elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data   = resp.json()
        status = data.get("output", {}).get("task_status", "UNKNOWN")

        if status == "SUCCEEDED":
            return data["output"]
        if status in ("FAILED", "CANCELED"):
            err_msg = data.get("output", {}).get("message", "no message")
            raise RuntimeError(f"Task {task_id} {status}: {err_msg}")

        print(f"        ⏳ {task_id[:14]}… {status} ({elapsed}s elapsed)")

    raise TimeoutError(f"Task {task_id} timed out after {MAX_WAIT}s")


def _download_video(url: str, dest: Path) -> str:
    """Download video from URL to dest path."""
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return str(dest)


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_video_prompt(
    char_name: str,
    char_info: dict,
    dialogue_lines: list[dict],
    location: str,
) -> str:
    all_text = " ".join(
        d.get("line", "") for d in dialogue_lines if d.get("line")
    ).strip()

    # Flatten appearance dict
    appearance = char_info.get("appearance", {})
    if isinstance(appearance, dict):
        age    = appearance.get("age", "")
        hair   = appearance.get("hair", "")
        eyes   = appearance.get("eyes", "")
        attire = appearance.get("attire", "")
    else:
        age = hair = eyes = attire = ""

    # Personality list or string
    personality = char_info.get("personality", char_info.get("traits", ""))
    if isinstance(personality, list):
        personality = ", ".join(personality)

    gender = char_info.get("gender", "")

    # Speech section
    if all_text:
        excerpt = all_text[:140].rstrip()
        if len(all_text) > 140:
            excerpt += "…"
        speech_part = (
            f"{char_name} is speaking. Mouth moves naturally in sync with dialogue. "
            f'Dialogue: "{excerpt}". '
        )
    else:
        speech_part = (
            f"{char_name} looks at camera with a calm, natural expression. "
            "Subtle breathing and natural blinking. "
        )

    # Visual cue
    visual_cues = [d.get("visual_cue", "") for d in dialogue_lines if d.get("visual_cue")]
    cue_part = f"{visual_cues[0][:80]}. " if visual_cues else ""

    # Character description for animation fidelity
    desc_parts = []
    if gender:
        desc_parts.append(gender)
    if age:
        desc_parts.append(f"age {age}")
    if hair:
        desc_parts.append(f"{hair} hair")
    if eyes:
        desc_parts.append(f"{eyes} eyes")
    if attire:
        desc_parts.append(f"wearing {attire}")
    if personality:
        desc_parts.append(f"personality: {personality}")
    char_desc = f"Character description: {', '.join(desc_parts)}. " if desc_parts else ""

    prompt = (
        f"Cinematic short video clip. "
        f"Location: {location}. "
        + char_desc
        + speech_part
        + cue_part
        + "Natural realistic lip movement, subtle head motion, realistic blinking, "
          "gentle breathing. "
          "Dramatic chiaroscuro lighting, film grain, 35mm anamorphic lens aesthetic. "
          "High quality, photorealistic, no text overlay, no watermark."
    )
    return prompt


# ── Core video generation ─────────────────────────────────────────────────────

def _submit_i2v_task(
    model: str,
    image_path: str,
    prompt: str,
    api_key: str,
) -> str:
    """Submit an I2V task and return the task_id."""
    headers = {
        "Authorization":     f"Bearer {api_key}",
        "Content-Type":      "application/json",
        "X-DashScope-Async": "enable",
    }

    # Use base64 data URI for the image (most compatible method)
    img_data_uri = _to_base64_data_uri(image_path)

    payload = {
        "model": model,
        "input": {
            "prompt":  prompt,
            "img_url": img_data_uri,
        },
        "parameters": {
            "resolution":    "480P",
            "prompt_extend": True,
            "watermark":     False,
        },
    }

    resp = requests.post(
        I2V_SUBMIT_URL, headers=headers, json=payload, timeout=60
    )

    if resp.status_code != 200:
        err_body = ""
        try:
            err_body = resp.json().get("message", resp.text[:200])
        except Exception:
            err_body = resp.text[:200]
        raise RuntimeError(f"HTTP {resp.status_code}: {err_body}")

    data    = resp.json()
    task_id = data.get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"No task_id in response: {data}")

    return task_id


def _generate_character_video(
    clip: dict,
    char_info: dict,
    location: str,
    api_key: str,
    out_path: Path,
) -> bool:
    """
    Try each I2V model in priority order.
    Returns True on success, raises on total failure.
    """
    char_name  = clip["character_name"]
    image_path = clip.get("image_path")
    dialogue   = clip.get("dialogue_lines", [])

    if not image_path or not Path(image_path).exists():
        raise FileNotFoundError(f"Character image not found: {image_path}")

    prompt = _build_video_prompt(char_name, char_info, dialogue, location)
    print(f"    Prompt ({len(prompt)} chars): {prompt[:120]}…")

    last_error = None
    for model in I2V_MODELS:
        try:
            print(f"    → Submitting [{model}]…")
            task_id = _submit_i2v_task(model, image_path, prompt, api_key)
            print(f"    → task_id={task_id[:16]}… polling…")

            output = _poll_task(task_id, api_key)

            # Extract video URL
            video_url = (
                output.get("video_url")
                or output.get("url")
                or (output.get("results") or [{}])[0].get("url", "")
                or (output.get("videos") or [{}])[0].get("url", "")
            )
            if not video_url:
                raise RuntimeError(f"No video URL in output: {list(output.keys())}")

            _download_video(video_url, out_path)
            size_kb = out_path.stat().st_size // 1024
            print(f"    ✅ [{model}] downloaded {size_kb} KB → {out_path}")
            return True

        except Exception as exc:
            print(f"    ⚠  [{model}] failed: {exc}")
            last_error = exc
            time.sleep(2)

    raise RuntimeError(f"All I2V models failed. Last error: {last_error}")


# ── Static image fallback (FFmpeg) ────────────────────────────────────────────

def _static_fallback(clip: dict, out_path: Path) -> bool:
    """
    Encode the character still image as a static video clip using FFmpeg.
    Used when all I2V API calls fail.
    """
    import subprocess
    import shutil

    image_path = clip.get("image_path")
    duration   = clip.get("duration_sec", 5.0)

    if not image_path or not Path(image_path).exists():
        print(f"    ❌ Static fallback: no image at {image_path}")
        return False
    if not shutil.which("ffmpeg"):
        print("    ❌ Static fallback: ffmpeg not found")
        return False

    try:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i",    image_path,
            "-vf",   (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black"
            ),
            "-c:v",     "libx264",
            "-pix_fmt", "yuv420p",
            "-t",       f"{duration:.3f}",
            "-r",       "24",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            print(f"    ❌ FFmpeg static fallback error: {result.stderr.decode()[-200:]}")
            return False
        if not out_path.exists() or out_path.stat().st_size < 1000:
            return False
        print(f"    ℹ Static fallback clip created: {out_path}")
        return True
    except Exception as e:
        print(f"    ❌ Static fallback exception: {e}")
        return False


# ── Agent ─────────────────────────────────────────────────────────────────────

def ken_burns_agent(state: "Phase3State") -> "Phase3State":
    """
    Generate per-character videos using Wan I2V models.
    Falls back to a static-image clip if all API calls fail.
    """
    print("\n[Phase3][VideoGen] Generating per-character videos (Wan I2V)…")

    CLIPS_DIR.mkdir(parents=True, exist_ok=True)

    api_key    = state.get("dashscope_api_key") or os.getenv("DASHSCOPE_API_KEY", "")
    task_graph = state["task_graph"]
    char_list  = state.get("characters", [])

    # Build character info lookup
    char_map: dict[str, dict] = {c.get("name", ""): c for c in char_list}

    ok_count  = 0
    err_count = 0

    for task in task_graph:
        sid      = task["scene_id"]
        location = task.get("location", "unknown location")

        for clip in task["character_clips"]:
            char_name = clip["character_name"]
            safe_name = char_name.replace(" ", "_")
            out_path  = CLIPS_DIR / f"scene_{sid:02d}_{safe_name}.mp4"

            # Skip if already generated and large enough
            if out_path.exists() and out_path.stat().st_size > 10_000:
                print(f"  ⏭  Scene {sid} · {char_name}: clip exists — skipping")
                clip["raw_video_path"] = str(out_path)
                if clip["status"] == "image_done":
                    clip["status"] = "video_done"
                ok_count += 1
                continue

            # Cannot generate video without image
            if clip["status"] == "pending" or not clip.get("image_path"):
                print(f"  ⚠  Scene {sid} · {char_name}: no image — using static fallback")
                if _static_fallback(clip, out_path):
                    clip["raw_video_path"] = str(out_path)
                    clip["status"]         = "video_done"
                    ok_count += 1
                else:
                    clip["status"] = "error"
                    clip["error"]  = "No image and static fallback failed"
                    err_count += 1
                continue

            print(f"\n  [Scene {sid} · {char_name}] Generating video…")
            char_info = char_map.get(char_name, {})

            try:
                if api_key:
                    success = _generate_character_video(
                        clip, char_info, location, api_key, out_path
                    )
                    if success:
                        clip["raw_video_path"] = str(out_path)
                        clip["status"]         = "video_done"
                        sz = out_path.stat().st_size // 1024
                        print(f"  ✅ Scene {sid} · {char_name} → {out_path} [{sz} KB]")
                        ok_count += 1
                        continue
                else:
                    print(f"  ⚠  No API key — using static fallback for {char_name}")

            except Exception as exc:
                print(f"  ⚠  Scene {sid} · {char_name}: I2V API failed ({exc})")

            # Fallback: static image clip
            print(f"       Falling back to static-image clip…")
            if _static_fallback(clip, out_path):
                clip["raw_video_path"] = str(out_path)
                clip["status"]         = "video_done"
                print(f"  ℹ  Scene {sid} · {char_name}: static fallback used")
                ok_count += 1
            else:
                clip["status"] = "error"
                clip["error"]  = "All video generation methods failed"
                err_count += 1

    print(f"\n[Phase3][VideoGen] Complete — {ok_count} done, {err_count} errors\n")
    return {**state, "task_graph": task_graph}