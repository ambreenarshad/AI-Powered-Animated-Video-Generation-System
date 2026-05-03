# agents3/scene_visual_agent.py
"""
Scene Visual Agent  —  WAN (Singapore / International endpoint)
────────────────────────────────────────────────────────────────
Two-step pipeline per scene:
  Step 1 → Text-to-Image  (wan2.5-t2i-preview)  → still keyframe PNG
  Step 2 → Image-to-Video (wan2.2-i2v-plus)     → animated MP4 clip

Image is passed to I2V as base64 in the request body (not file:// URI).
"""

import os
import base64
import requests
from http import HTTPStatus
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlparse, unquote
from typing import List, Dict, Any

import dashscope
from dashscope import ImageSynthesis

# ── International (Singapore) endpoint ───────────────────────────────────────
dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"

T2I_MODEL = "wan2.5-t2i-preview"
I2V_MODEL = "wan2.2-i2v-plus"

# I2V is called via raw HTTP because the SDK's VideoSynthesis.async_call()
# does not reliably accept base64 image payloads across all SDK versions.
I2V_URL        = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
TASK_QUERY_URL = "https://dashscope-intl.aliyuncs.com/api/v1/tasks/{task_id}"

FRAMES_DIR = Path("outputs/video/frames")
RAW_DIR    = Path("outputs/video/raw")
FRAMES_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

POLL_INTERVAL = 8    # seconds
MAX_WAIT      = 400  # seconds


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_api_key(state: dict) -> str:
    key = state.get("wan_api_key") or os.getenv("DASHSCOPE_API_KEY", "")
    if not key:
        raise ValueError(
            "No API key found. Set DASHSCOPE_API_KEY env var or enter it in the UI."
        )
    return key


def _download(url: str, dest: Path) -> str:
    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    return str(dest)


def _to_base64(image_path: str) -> str:
    """Read image file and return base64-encoded string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _poll_task(task_id: str, api_key: str) -> dict:
    """Poll DashScope task until SUCCEEDED or FAILED. Returns output dict."""
    import time
    url     = TASK_QUERY_URL.format(task_id=task_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0

    while elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        resp   = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        data   = resp.json()
        status = data.get("output", {}).get("task_status", "")

        if status == "SUCCEEDED":
            return data["output"]
        if status in ("FAILED", "CANCELED"):
            raise RuntimeError(f"Task {task_id} {status}: {data}")

        print(f"        ⏳ {task_id[:10]}… {status} ({elapsed}s)")

    raise TimeoutError(f"Task {task_id} timed out after {MAX_WAIT}s")


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Text → Image  (wan2.5-t2i-preview, via DashScope SDK)
# ─────────────────────────────────────────────────────────────────────────────

def _text_to_image(prompt: str, scene_id: int, api_key: str) -> str:
    print(f"      [T2I] submitting scene {scene_id} ({T2I_MODEL})...")

    rsp = ImageSynthesis.async_call(
        api_key       = api_key,
        model         = T2I_MODEL,
        prompt        = prompt,
        n             = 1,
        size          = "1280*720",
        prompt_extend = True,
        watermark     = False,
    )

    if rsp.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"T2I submit failed [{rsp.status_code}]: {rsp.code} — {rsp.message}"
        )

    print(f"      [T2I] task_id={rsp.output.task_id[:12]}... polling...")
    rsp = ImageSynthesis.wait(task=rsp, api_key=api_key)

    if rsp.status_code != HTTPStatus.OK:
        raise RuntimeError(
            f"T2I failed [{rsp.status_code}]: {rsp.code} — {rsp.message}"
        )

    results = rsp.output.get("results") or rsp.output.get("images") or []
    if not results:
        raise RuntimeError(f"T2I: empty results: {rsp.output}")

    img_url = results[0].get("url")
    if not img_url:
        raise RuntimeError(f"T2I: no url in results[0]: {results[0]}")

    dest = FRAMES_DIR / f"scene_{scene_id:02d}_frame.png"
    path = _download(img_url, dest)
    print(f"      [T2I] ✅ keyframe saved: {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Image → Video  (wan2.2-i2v-plus, via raw HTTP + base64)
# ─────────────────────────────────────────────────────────────────────────────

def _image_to_video(image_path: str, prompt: str,
                    duration: float, scene_id: int, api_key: str) -> str:
    # wan2.2-i2v-plus does not support custom duration — uses model default (~5s)
    # Encode image as base64 — most reliable cross-platform method
    print(f"      [I2V] encoding image as base64...")
    img_b64 = _to_base64(image_path)

    print(f"      [I2V] submitting scene {scene_id} ({I2V_MODEL})...")

    headers = {
        "Authorization":    f"Bearer {api_key}",
        "Content-Type":     "application/json",
        "X-DashScope-Async":"enable",
    }
    payload = {
        "model": I2V_MODEL,
        "input": {
            "prompt":  prompt,
            "img_url": f"data:image/png;base64,{img_b64}",
        },
        "parameters": {
            "resolution":    "480P",
            "prompt_extend": True,
            "watermark":     False,
        },
    }

    resp = requests.post(I2V_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data    = resp.json()
    task_id = data.get("output", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"I2V submit failed: {data}")

    print(f"      [I2V] task_id={task_id[:12]}... polling (model default duration)...")
    output = _poll_task(task_id, api_key)

    video_url = (
        output.get("video_url")
        or (output.get("results") or [{}])[0].get("url", "")
    )
    if not video_url:
        raise RuntimeError(f"I2V: no video_url in output: {output}")

    dest = RAW_DIR / f"scene_{scene_id:02d}_raw.mp4"
    path = _download(video_url, dest)
    print(f"      [I2V] ✅ raw video saved: {path}")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Per-scene orchestration
# ─────────────────────────────────────────────────────────────────────────────

def _generate_scene(task: dict, api_key: str) -> str:
    sid    = task["scene_id"]
    prompt = task["visual_prompt"]
    dur    = task["duration_sec"]

    print(f"  -> Scene {sid}: Step 1 — Text -> Image...")
    frame_path = _text_to_image(prompt, sid, api_key)

    print(f"  -> Scene {sid}: Step 2 — Image -> Video...")
    video_path = _image_to_video(frame_path, prompt, dur, sid, api_key)

    return video_path


# ─────────────────────────────────────────────────────────────────────────────
# Agent entry point
# ─────────────────────────────────────────────────────────────────────────────

def scene_visual_agent(state: dict) -> dict:
    print("[Phase 3 · Scene Visual Agent] WAN Singapore — T2I(wan2.5) -> I2V(wan2.2)...")

    api_key = _get_api_key(state)
    dashscope.api_key = api_key

    task_graph: List[Dict[str, Any]] = state["task_graph"]
    visual_results = []

    for task in task_graph:
        sid = task["scene_id"]
        try:
            video_path = _generate_scene(task, api_key)
            task["raw_frames"] = [video_path]
            task["status"]     = "frames_done"
            visual_results.append({
                "scene_id":   sid,
                "video_path": video_path,
                "status":     "done",
            })
        except Exception as e:
            print(f"  ❌ Scene {sid} failed: {e}")
            task["status"] = "error"
            task["error"]  = str(e)
            visual_results.append({
                "scene_id": sid,
                "status":   "error",
                "error":    str(e),
            })

    ok  = sum(1 for r in visual_results if r["status"] == "done")
    err = len(visual_results) - ok
    print(f"[Phase 3 · Scene Visual Agent] {ok} done, {err} errors.")

    return {**state, "task_graph": task_graph, "visual_results": visual_results}