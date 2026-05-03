"""
agents3/manifest_loader.py
──────────────────────────
Reads Phase 1 scene_manifest + character_db and Phase 2 timing_manifest.
Builds the full task_graph with one SceneVideoTask per scene, each
containing a CharacterClip for every speaking character in that scene.

character_db provides: name, appearance, clothing, age, traits, style
scene_manifest provides: scene_id, location, characters, dialogue, visual_cues
timing_manifest provides: scene_id, speaker, line, start_ms, end_ms
"""

from __future__ import annotations

import json
import os
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
    with open(sm_path, encoding="utf-8") as f:
        sm = json.load(f)
    scenes = sm.get("scenes", sm) if isinstance(sm, dict) else sm
    print(f"  → {len(scenes)} scenes loaded from {sm_path.name}")

    # ── Load character DB ─────────────────────────────────────────────────────
    cb_path = Path(state["character_db_path"])
    if not cb_path.exists():
        raise FileNotFoundError(f"character_db not found: {cb_path}")
    with open(cb_path, encoding="utf-8") as f:
        cb = json.load(f)
    characters_list = cb.get("characters", cb) if isinstance(cb, dict) else cb
    char_map: dict[str, dict] = {}
    for c in characters_list:
        name = c.get("name", "")
        if name:
            char_map[name] = c
    print(f"  → {len(char_map)} characters loaded from {cb_path.name}")
    for name, info in char_map.items():
        appearance = info.get("appearance", {})
        if isinstance(appearance, dict):
            appearance_str = ", ".join(f"{k}: {v}" for k, v in appearance.items())
        elif isinstance(appearance, list):
            appearance_str = ", ".join(str(x) for x in appearance)
        else:
            appearance_str = str(appearance) if appearance else "(no appearance)"
        print(f"    • {name}: {appearance_str[:80]}")

    # ── Load timing manifest ──────────────────────────────────────────────────
    tm_path = Path(state["timing_manifest_path"])
    if not tm_path.exists():
        raise FileNotFoundError(f"timing_manifest not found: {tm_path}")
    with open(tm_path, encoding="utf-8") as f:
        tm = json.load(f)
    timing: list[dict] = tm if isinstance(tm, list) else tm.get("timing", [])
    print(f"  → {len(timing)} timing entries loaded from {tm_path.name}")

    # ── Build timing lookups ──────────────────────────────────────────────────
    # scene-level: scene_id → {start_ms, end_ms}
    scene_timing: dict[int, dict] = {}
    for entry in timing:
        sid = entry.get("scene_id")
        if sid is None:
            continue
        e_start = entry.get("start_ms", 0)
        e_end   = entry.get("end_ms",   5000)
        if sid not in scene_timing:
            scene_timing[sid] = {"start_ms": e_start, "end_ms": e_end}
        else:
            scene_timing[sid]["start_ms"] = min(scene_timing[sid]["start_ms"], e_start)
            scene_timing[sid]["end_ms"]   = max(scene_timing[sid]["end_ms"],   e_end)

    # per-character per-scene: (scene_id, speaker) → [timing entries]
    char_timing: dict[tuple, list[dict]] = {}
    for entry in timing:
        sid     = entry.get("scene_id")
        speaker = entry.get("speaker", "").strip()
        if sid is None or not speaker:
            continue
        char_timing.setdefault((sid, speaker), []).append(entry)

    audio_dir = Path(state.get("audio_dir", "outputs/audio"))

    # ── Build task_graph ──────────────────────────────────────────────────────
    task_graph: list[dict] = []

    for scene in scenes:
        sid        = scene["scene_id"]
        characters = scene.get("characters", [])
        dialogue   = scene.get("dialogue", [])

        # Scene timing from manifest
        st = scene_timing.get(sid, {"start_ms": 0, "end_ms": 5000})
        scene_dur = max((st["end_ms"] - st["start_ms"]) / 1000.0, 3.0)

        # ── Build CharacterClip list ──────────────────────────────────────────
        character_clips: list[dict] = []

        for char_name in characters:
            char_info = char_map.get(char_name, {})

            # Collect timing entries for this character in this scene
            ct_entries = char_timing.get((sid, char_name), [])

            # Enrich dialogue lines with timing data
            timing_by_line: dict[str, dict] = {
                e.get("line", ""): e for e in ct_entries
            }
            char_lines = [d for d in dialogue if d.get("speaker") == char_name]

            enriched_lines = []
            for d in char_lines:
                t = timing_by_line.get(d.get("line", ""), {})
                enriched_lines.append({
                    "speaker":    char_name,
                    "line":       d.get("line", ""),
                    "visual_cue": d.get("visual_cue", ""),
                    "start_ms":   t.get("start_ms", st["start_ms"]),
                    "end_ms":     t.get("end_ms",   st["end_ms"]),
                })

            # Per-character audio path
            char_audio: str | None = None
            safe_name = char_name.replace(" ", "_")
            for pattern in [
                f"scene_{sid:02d}_{char_name}.wav",
                f"scene_{sid:02d}_{safe_name}.wav",
                f"scene_{sid:02d}_{char_name.lower()}.wav",
                f"scene_{sid:02d}_{safe_name.lower()}.wav",
                f"scene_{sid:02d}.wav",
                f"scene_{sid}.wav",
            ]:
                p = audio_dir / pattern
                if p.exists():
                    char_audio = str(p)
                    break

            # Clip duration from the span of this character's lines
            if enriched_lines:
                c_start  = min(l["start_ms"] for l in enriched_lines)
                c_end    = max(l["end_ms"]   for l in enriched_lines)
                char_dur = max((c_end - c_start) / 1000.0, 3.0)
            else:
                char_dur = scene_dur

            audio_sym = f"✓ {os.path.basename(char_audio)}" if char_audio else "✗ (none)"
            print(f"    {char_name} · scene {sid}: "
                  f"dur={char_dur:.1f}s  lines={len(enriched_lines)}  audio={audio_sym}")

            clip: dict = {
                "scene_id":       sid,
                "character_name": char_name,
                "image_path":     None,
                "raw_video_path": None,
                "audio_path":     char_audio,
                "synced_path":    None,
                "dialogue_lines": enriched_lines,
                "duration_sec":   char_dur,
                "status":         "pending",
                "error":          None,
            }
            character_clips.append(clip)

        task: dict = {
            "scene_id":        sid,
            "location":        scene.get("location", ""),
            "characters":      characters,
            "dialogue":        dialogue,
            "duration_sec":    scene_dur,
            "start_ms":        st["start_ms"],
            "end_ms":          st["end_ms"],
            "character_clips": character_clips,
            "merged_clip":     None,
            "status":          "pending",
            "error":           None,
        }
        task_graph.append(task)
        print(f"  ✅ Scene {sid}: '{scene.get('location','')}' "
              f"| {len(characters)} character(s) | {scene_dur:.1f}s")

    total_clips = sum(len(t["character_clips"]) for t in task_graph)
    print(f"\n[Phase3][ManifestLoader] ✅ {len(task_graph)} scenes, "
          f"{total_clips} character clips queued.\n")

    return {
        **state,
        "scenes":          scenes,
        "characters":      characters_list,
        "timing_manifest": timing,
        "task_graph":      task_graph,
        "status":          "processing",
    }