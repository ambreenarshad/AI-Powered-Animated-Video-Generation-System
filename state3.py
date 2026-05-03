# state3.py
"""
Phase 3 Graph State
Carries all data through the video generation & composition pipeline.
"""
from typing import TypedDict, List, Dict, Any, Optional


class SceneVideoTask(TypedDict):
    scene_id:      int
    location:      str
    visual_prompt: str          # engineered prompt for WAN
    characters:    List[str]
    dialogue:      List[Dict]
    audio_path:    Optional[str]  # from Phase 2
    start_ms:      int
    end_ms:        int
    duration_sec:  float

    # filled by agents
    raw_frames:    List[str]    # paths to WAN-generated frames/clip
    animated_clip: Optional[str]  # after Ken Burns
    synced_clip:   Optional[str]  # after A/V sync
    status:        str          # pending | frames_done | animated | synced | error
    error:         Optional[str]


class Phase3State(TypedDict):
    # ── Inputs ─────────────────────────────────────────────────────────────────
    scene_manifest_path:  str   # outputs/scene_manifest.json  (Phase 1)
    timing_manifest_path: str   # outputs/timing_manifest.json (Phase 2)
    audio_dir:            str   # outputs/audio/               (Phase 2)

    # ── Parsed data ────────────────────────────────────────────────────────────
    scenes:          List[Dict[str, Any]]
    timing_manifest: List[Dict[str, Any]]

    # ── Task graph ─────────────────────────────────────────────────────────────
    task_graph: List[SceneVideoTask]

    # ── Intermediate results ───────────────────────────────────────────────────
    visual_results:   List[Dict]   # {scene_id, frames, status}
    animated_results: List[Dict]   # {scene_id, clip_path, status}
    synced_results:   List[Dict]   # {scene_id, clip_path, status}

    # ── Final outputs ──────────────────────────────────────────────────────────
    final_output:    str           # outputs/video/final_output.mp4
    subtitle_file:   Optional[str] # outputs/video/subtitles.srt (optional)

    # ── Control ────────────────────────────────────────────────────────────────
    enable_subtitles: bool
    wan_api_key:      str
    status:           str
    error:            Optional[str]
    task_log:         List[Dict]