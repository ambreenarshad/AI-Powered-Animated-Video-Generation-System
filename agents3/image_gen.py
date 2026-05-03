"""
agents3/image_gen.py
─────────────────────
Generates one cinematic image per CHARACTER per scene.

Model: wan2.5-t2i-preview  (DashScope International, raw HTTP async)
Endpoint: /services/aigc/text2image/image-synthesis

wan2.5-t2i-preview must be called via raw HTTP (not the ImageSynthesis SDK
which only accepts legacy wanx-prefixed model IDs).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from state3 import Phase3State

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL       = "https://dashscope-intl.aliyuncs.com/api/v1"
T2I_SUBMIT_URL = f"{BASE_URL}/services/aigc/text2image/image-synthesis"
TASK_QUERY_URL = f"{BASE_URL}/tasks/{{task_id}}"

T2I_MODEL     = "wan2.5-t2i-preview"
OUT_DIR       = Path("outputs/images/characters")
WIDTH         = 1280
HEIGHT        = 720
RETRIES       = 3
POLL_INTERVAL = 6    # seconds between polls
MAX_WAIT      = 300  # 5 minutes max


# ── Poll helper ───────────────────────────────────────────────────────────────

def _poll_task(task_id: str, api_key: str) -> dict:
    url     = TASK_QUERY_URL.format(task_id=task_id)
    headers = {"Authorization": f"Bearer {api_key}"}
    elapsed = 0
    while elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        resp   = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data   = resp.json()
        status = data.get("output", {}).get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            return data["output"]
        if status in ("FAILED", "CANCELED"):
            msg = data.get("output", {}).get("message", str(data))
            raise RuntimeError(f"Task {task_id} {status}: {msg}")
        print(f"        ⏳ {task_id[:14]}… {status} ({elapsed}s)")
    raise TimeoutError(f"Task {task_id} timed out after {MAX_WAIT}s")


# ── Prompt builder ────────────────────────────────────────────────────────────

def _flatten_appearance(appearance) -> dict:
    if isinstance(appearance, dict):
        return appearance
    if isinstance(appearance, str) and appearance:
        return {"description": appearance}
    return {}


def _build_character_prompt(char_name, char_info, scene, dialogue_lines):
    location    = scene.get("location", "unknown location")
    style       = char_info.get("style", "cinematic noir")
    app         = _flatten_appearance(char_info.get("appearance", {}))
    age         = app.get("age",    "")
    height      = app.get("height", "")
    hair        = app.get("hair",   "")
    eyes        = app.get("eyes",   "")
    attire      = app.get("attire", char_info.get("clothing", ""))
    personality = char_info.get("personality", char_info.get("traits", ""))
    if isinstance(personality, list):
        personality = ", ".join(personality)
    gender     = char_info.get("gender", "")
    visual_cue = next(
        (d["visual_cue"] for d in dialogue_lines if d.get("visual_cue", "").strip()), ""
    )

    parts = [
        "Cinematic portrait still frame, dramatic noir lighting, film grain, 35mm anamorphic lens.",
        f"Location: {location}.",
        f"Subject: {char_name}",
    ]
    if gender:
        parts[-1] += f", {gender}"
    parts[-1] += ", single person, centered composition."
    if age:       parts.append(f"Age: {age}.")
    if height:    parts.append(f"Height: {height}.")
    if hair:      parts.append(f"Hair: {hair}.")
    if eyes:      parts.append(f"Eyes: {eyes}.")
    if attire:    parts.append(f"Wearing: {attire}.")
    if personality: parts.append(f"Expression and demeanor: {personality}.")
    if visual_cue:  parts.append(f"Shot direction: {visual_cue}.")
    parts += [f"Visual style: {style}.",
              "Photorealistic, 4K, highly detailed, professional cinematography.",
              "No text, no watermark."]
    return " ".join(parts)


# ── Image generation via raw HTTP ─────────────────────────────────────────────

def _generate_image(prompt: str, api_key: str, out_path: Path) -> bool:
    headers = {
        "Authorization":     f"Bearer {api_key}",
        "Content-Type":      "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": T2I_MODEL,
        "input": {"prompt": prompt},
        "parameters": {
            "size":      f"{WIDTH}*{HEIGHT}",
            "n":         1,
            "watermark": False,
        },
    }

    for attempt in range(1, RETRIES + 1):
        try:
            print(f"    → [{T2I_MODEL}] attempt {attempt}/{RETRIES}…")
            resp = requests.post(T2I_SUBMIT_URL, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                try:
                    body = resp.json().get("message", resp.text[:300])
                except Exception:
                    body = resp.text[:300]
                raise RuntimeError(f"HTTP {resp.status_code}: {body}")

            data    = resp.json()
            task_id = data.get("output", {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"No task_id: {data}")

            print(f"    → task_id={task_id[:16]}… polling…")
            output  = _poll_task(task_id, api_key)

            results = output.get("results") or output.get("images") or []
            if not results:
                raise RuntimeError(f"Empty results: {output}")

            item    = results[0]
            img_url = (item.get("url") or item.get("img_url") or "") if isinstance(item, dict) else str(item)
            if not img_url:
                raise RuntimeError(f"No image URL: {item}")

            img_resp = requests.get(img_url, timeout=120)
            img_resp.raise_for_status()
            if len(img_resp.content) < 5_000:
                raise ValueError(f"Image too small: {len(img_resp.content)} B")

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(img_resp.content)
            print(f"    ✅ Saved {len(img_resp.content)//1024} KB → {out_path.name}")
            return True

        except Exception as exc:
            print(f"    ⚠  [{T2I_MODEL}] attempt {attempt} failed: {exc}")
            if attempt < RETRIES:
                time.sleep(4)
    return False


# ── Gradient placeholder ──────────────────────────────────────────────────────

def _gradient_placeholder(char_name: str, scene_id: int, out_path: Path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        import struct, zlib
        def _chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        png = (b'\x89PNG\r\n\x1a\n'
               + _chunk(b'IHDR', struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
               + _chunk(b'IDAT', zlib.compress(b'\x00\xff\x00\x00' * 64))
               + _chunk(b'IEND', b''))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(png)
        return

    palettes = [
        ((10,15,35),(60,80,140)), ((30,10,10),(120,40,30)),
        ((10,28,15),(30,80,50)),  ((25,20,10),(90,70,20)),
        ((20,10,30),(70,30,100)),
    ]
    top, bot = palettes[scene_id % len(palettes)]
    img  = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line([(0,y),(WIDTH,y)], fill=(
            int(top[0]+(bot[0]-top[0])*t),
            int(top[1]+(bot[1]-top[1])*t),
            int(top[2]+(bot[2]-top[2])*t),
        ))
    vig = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    vd  = ImageDraw.Draw(vig)
    for i in range(80):
        vd.rectangle([i,i,WIDTH-i,HEIGHT-i], outline=(0,0,0,int(180*(i/80)**2)))
    img  = Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        fb = ImageFont.truetype("arial.ttf", 52)
        fs = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        fb = fs = ImageFont.load_default()
    draw.text((60,60),  f"SCENE {scene_id}", font=fs, fill=(200,170,80))
    draw.text((60,110), char_name.upper(),    font=fb, fill=(240,230,200))
    draw.line([(60,108),(360,108)], fill=(180,140,50), width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")
    print(f"    ℹ Placeholder: {out_path.name}")


# ── Agent ─────────────────────────────────────────────────────────────────────

def image_gen_agent(state: "Phase3State") -> "Phase3State":
    print(f"\n[Phase3][ImageGen] Generating per-character images ({T2I_MODEL})…")

    api_key   = state.get("dashscope_api_key") or os.getenv("DASHSCOPE_API_KEY", "")
    task_graph = state["task_graph"]
    char_map   = {c.get("name",""): c for c in state.get("characters",[])}
    scene_map  = {s["scene_id"]: s for s in state.get("scenes",[])}

    ai_count = pl_count = skip_count = 0

    for task in task_graph:
        sid   = task["scene_id"]
        scene = scene_map.get(sid, {"scene_id": sid, "location": task.get("location","")})

        for clip in task["character_clips"]:
            char_name = clip["character_name"]
            safe_name = char_name.replace(" ","_")
            out_path  = OUT_DIR / f"scene_{sid:02d}_{safe_name}.png"

            if out_path.exists() and out_path.stat().st_size > 5_000:
                print(f"  ⏭  Scene {sid} · {char_name}: exists — skipping")
                clip["image_path"] = str(out_path)
                if clip["status"] == "pending":
                    clip["status"] = "image_done"
                skip_count += 1
                continue

            char_info = char_map.get(char_name, {})
            prompt    = _build_character_prompt(char_name, char_info, scene,
                                                clip.get("dialogue_lines",[]))
            print(f"\n  [Scene {sid} · {char_name}]")
            print(f"  Prompt: {prompt[:140]}…")

            generated = False
            if api_key:
                generated = _generate_image(prompt, api_key, out_path)
            else:
                print("  ⚠  No DASHSCOPE_API_KEY — skipping AI generation")

            if generated:
                ai_count += 1
            else:
                print(f"  ⚠  Scene {sid} · {char_name}: falling back to placeholder")
                _gradient_placeholder(char_name, sid, out_path)
                pl_count += 1

            clip["image_path"] = str(out_path)
            clip["status"]     = "image_done"
            time.sleep(1.0)

    total = ai_count + pl_count + skip_count
    print(f"\n[Phase3][ImageGen] Complete — "
          f"{ai_count} AI | {pl_count} placeholders | {skip_count} cached ({total} total)\n")
    return {**state, "task_graph": task_graph}