# agents3/image_gen.py
"""
Image Generation Agent  —  Phase 3
────────────────────────────────────
Generates one cinematic base image per scene using Pollinations.AI (free, no key).
The Ken Burns agent then renders these into per-frame sequences.

Pollinations endpoint (no API key, completely free):
  GET https://image.pollinations.ai/prompt/{encoded_prompt}
      ?width=1280&height=720&model=flux&seed={seed}&nologo=true&enhance=true
"""

from __future__ import annotations
import time
import random
import urllib.request
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State

OUT_DIR = Path("outputs/images")
TIMEOUT = 90
RETRIES = 3
WIDTH   = 1280
HEIGHT  = 720


def _build_prompt(scene: dict) -> str:
    location   = scene.get("location", "unknown location")
    characters = scene.get("characters", [])
    dialogue   = scene.get("dialogue", [])
    visual_cue = next((d.get("visual_cue","").strip() for d in dialogue
                       if d.get("visual_cue","").strip()), "")
    char_str   = ", ".join(characters) if characters else "two characters"
    parts = [
        "cinematic still frame", "noir style", "dramatic chiaroscuro lighting",
        "film grain", "35mm anamorphic lens",
        f"location: {location}", f"characters: {char_str}",
    ]
    if visual_cue:
        parts.append(f"shot: {visual_cue}")
    parts += ["no text", "no watermark", "highly detailed", "4k"]
    return ", ".join(parts)


def _fetch_pollinations(prompt: str, seed: int, out_path: Path) -> bool:
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={WIDTH}&height={HEIGHT}&model=flux"
        f"&seed={seed}&nologo=true&enhance=true"
    )
    for attempt in range(1, RETRIES + 1):
        try:
            print(f"    → Pollinations request (attempt {attempt}/{RETRIES})…")
            req = urllib.request.Request(url, headers={"User-Agent": "ProjectMontage/1.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
            if len(data) < 5_000:
                raise ValueError(f"Response too small ({len(data)} B)")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            return True
        except Exception as exc:
            print(f"    ⚠  Attempt {attempt} failed: {exc}")
            if attempt < RETRIES:
                time.sleep(4)
    return False


def _make_gradient_placeholder(scene: dict, out_path: Path) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
        return "bare_png"

    sid      = scene.get("scene_id", 1)
    location = scene.get("location", "Unknown")
    palettes = [
        ((10,15,35),(60,80,140)), ((30,10,10),(120,40,30)),
        ((10,28,15),(30,80,50)),  ((25,20,10),(90,70,20)),
        ((20,10,30),(70,30,100)),
    ]
    top, bot = palettes[(sid - 1) % len(palettes)]
    img  = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        t = y / HEIGHT
        draw.line([(0,y),(WIDTH,y)], fill=tuple(int(top[i]+(bot[i]-top[i])*t) for i in range(3)))
    vig = Image.new("RGBA", (WIDTH, HEIGHT), (0,0,0,0))
    vd  = ImageDraw.Draw(vig)
    for i in range(80):
        vd.rectangle([i,i,WIDTH-i,HEIGHT-i], outline=(0,0,0,int(180*(i/80)**2)))
    img = Image.alpha_composite(img.convert("RGBA"), vig).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        fb = ImageFont.truetype("arial.ttf", 52)
        fs = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        fb = fs = ImageFont.load_default()
    draw.text((60,60), f"SCENE {sid}", font=fs, fill=(200,170,80))
    draw.text((60,110), location.upper(), font=fb, fill=(240,230,200))
    draw.line([(60,108),(300,108)], fill=(180,140,50), width=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")
    return "gradient_placeholder"


def image_gen_agent(state: "Phase3State") -> "Phase3State":
    print("\n[Phase3][ImageGen] Starting per-scene image generation…")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scene_videos = state.get("scene_videos", [])
    scenes_by_id = {s["scene_id"]: s for s in state.get("scenes", [])}
    ai_count = pl_count = 0

    for sv in scene_videos:
        sid      = sv["scene_id"]
        out_path = OUT_DIR / f"scene_{sid:02d}.png"
        if out_path.exists() and out_path.stat().st_size > 5_000:
            print(f"  ⏭  Scene {sid}: image already exists — skipping")
            sv["image_path"] = str(out_path)
            if sv["status"] == "pending":
                sv["status"] = "image_done"
            continue
        scene  = scenes_by_id.get(sid, {"scene_id":sid,"location":sv.get("location",""),"characters":[],"dialogue":[]})
        prompt = _build_prompt(scene)
        seed   = random.randint(1000, 99999)
        print(f"  [Scene {sid}] Generating image…")
        print(f"    Prompt: {prompt[:100]}…")
        ok = _fetch_pollinations(prompt, seed, out_path)
        if ok:
            print(f"  ✅ Scene {sid} → {out_path} [{out_path.stat().st_size//1024} KB, AI]")
            ai_count += 1
        else:
            print(f"  ⚠  Scene {sid}: network failed — using gradient placeholder")
            _make_gradient_placeholder(scene, out_path)
            print(f"  ✅ Scene {sid} → {out_path} [gradient_placeholder]")
            pl_count += 1
        sv["image_path"] = str(out_path)
        sv["status"]     = "image_done"
        time.sleep(1.5)

    print(f"[Phase3][ImageGen] Complete — {ai_count} AI-generated, {pl_count} placeholders\n")
    return {**state, "scene_videos": scene_videos}