"""
Phase 3 Graph State
Carries all data through the video generation & composition pipeline.

Pipeline (new):
  1. manifest_loader    — loads scene/character/timing manifests
  2. image_gen          — per-character per-scene image via Qwen-Image-2.0-Pro
  3. ken_burns          — per-character per-scene video via Wan2.6-I2V (lip-sync prompt)
  4. av_sync            — attach each character's dialogue audio to their video
  5. scene_merge        — composite all character videos for one scene into a single clip
  6. compositor         — concatenate all scene clips + burn subtitles → final MP4
"""

from typing import TypedDict, List, Dict, Any, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Per-character video unit (one per character per scene)
# ─────────────────────────────────────────────────────────────────────────────

class CharacterClip(TypedDict):
    scene_id:       int
    character_name: str
    image_path:     Optional[str]   # Qwen-generated character image
    raw_video_path: Optional[str]   # Wan2.6-I2V output (lip-sync video)
    audio_path:     Optional[str]   # per-character dialogue WAV
    synced_path:    Optional[str]   # video + audio merged
    dialogue_lines: List[Dict]      # [{speaker, line, visual_cue, start_ms, end_ms}]
    duration_sec:   float
    status:         str             # pending | image_done | video_done | synced | error
    error:          Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# Per-scene task (wraps multiple CharacterClips)
# ─────────────────────────────────────────────────────────────────────────────

class SceneVideoTask(TypedDict):
    scene_id:        int
    location:        str
    characters:      List[str]
    dialogue:        List[Dict]
    duration_sec:    float
    start_ms:        int
    end_ms:          int

    # Per-character clips
    character_clips: List[CharacterClip]

    # Final merged scene clip (after scene_merge agent)
    merged_clip:     Optional[str]

    # Control
    status:  str            # pending | chars_done | merged | error
    error:   Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# Top-level pipeline state
# ─────────────────────────────────────────────────────────────────────────────

class Phase3State(TypedDict):
    # ── Inputs ─────────────────────────────────────────────────────────────────
    scene_manifest_path:  str
    timing_manifest_path: str
    character_db_path:    str
    audio_dir:            str
    dashscope_api_key:    str     # used for both Qwen image + Wan video
    enable_subtitles:     bool

    # ── Parsed manifests ───────────────────────────────────────────────────────
    scenes:          List[Dict[str, Any]]
    characters:      List[Dict[str, Any]]   # from character_db
    timing_manifest: List[Dict[str, Any]]

    # ── Task graph (one entry per scene) ──────────────────────────────────────
    task_graph: List[SceneVideoTask]

    # ── Final outputs ──────────────────────────────────────────────────────────
    final_output:  str
    subtitle_file: Optional[str]

    # ── Control ────────────────────────────────────────────────────────────────
    status:   str
    error:    Optional[str]
    task_log: List[Dict]