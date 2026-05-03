# agents3/manifest_loader.py
"""
Manifest Loader Agent  —  Phase 3
Reads Phase 1 scene_manifest + character_db and Phase 2 timing_manifest.
Populates scene_videos list with one SceneVideo entry per scene.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from state3 import Phase3State


def manifest_loader_agent(state: "Phase3State") -> "Phase3State":
    print("\n[Phase3][ManifestLoader] Loading manifests…")

    # ── Load scene manifest ───────────────────────────────────────────────────
    sm_path = Path(state["scene_manifest_path"])
    if not sm_path.exists():
        raise FileNotFoundError(f"scene_manifest not found: {sm_path}")
    with open(sm_path) as f:
        sm = json.load(f)
    scenes = sm.get("scenes", sm) if isinstance(sm, dict) else sm
    print(f"  → {len(scenes)} scenes loaded from {sm_path}")

    # ── Load character DB ─────────────────────────────────────────────────────
    cb_path = Path(state["character_db_path"])
    if not cb_path.exists():
        raise FileNotFoundError(f"character_db not found: {cb_path}")
    with open(cb_path) as f:
        cb = json.load(f)
    characters = cb.get("characters", cb) if isinstance(cb, dict) else cb
    print(f"  → {len(characters)} characters loaded from {cb_path}")

    # ── Load timing manifest ──────────────────────────────────────────────────
    tm_path = Path(state["timing_manifest_path"])
    if not tm_path.exists():
        raise FileNotFoundError(f"timing_manifest not found: {tm_path}")
    with open(tm_path) as f:
        tm = json.load(f)
    timing = tm if isinstance(tm, list) else tm.get("timing", [])
    print(f"  → {len(timing)} timing entries loaded from {tm_path}")

    # ── Build timing lookup: scene_id → duration_seconds ─────────────────────
    timing_by_scene: dict[int, float] = {}
    for entry in timing:
        sid = entry.get("scene_id")
        start_ms = entry.get("start_ms", 0)
        end_ms   = entry.get("end_ms",   0)
        dur = (end_ms - start_ms) / 1000.0
        if sid is not None:
            timing_by_scene[sid] = timing_by_scene.get(sid, 0) + dur

    audio_dir = Path(state.get("audio_dir", "outputs/audio"))

    # ── Build scene_videos list ───────────────────────────────────────────────
    scene_videos = []
    for scene in scenes:
        sid      = scene["scene_id"]
        dur      = timing_by_scene.get(sid, 5.0)   # fallback 5 s
        audio_p  = audio_dir / f"scene_{sid:02d}.wav"

        sv = {
            "scene_id":   sid,
            "location":   scene.get("location", ""),
            "image_path": None,
            "video_clip": None,
            "audio_path": str(audio_p) if audio_p.exists() else None,
            "duration":   max(dur, 3.0),
            "status":     "pending",
            "error":      None,
        }
        has_audio = "✓" if audio_p.exists() else "✗"
        print(f"  ✅ Scene {sid}: '{sv['location']}' | "
              f"dur={sv['duration']:.1f}s | audio={has_audio}")
        scene_videos.append(sv)

    print(f"[Phase3][ManifestLoader] ✅ Ready — {len(scene_videos)} scenes queued.\n")

    return {
        **state,
        "scenes":          scenes,
        "characters":      characters,
        "timing_manifest": timing,
        "scene_videos":    scene_videos,
        "status":          "processing",
    }