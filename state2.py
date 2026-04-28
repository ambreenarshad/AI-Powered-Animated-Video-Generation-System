# state2.py
"""
Phase 2 Graph State
Carries all data through the audiovisual synthesis pipeline.
"""
from typing import TypedDict, List, Dict, Any, Optional


class SceneTask(TypedDict):
    scene_id: int
    location: str
    characters: List[str]
    dialogue: List[Dict[str, Any]]
    audio_path: Optional[str]       # filled by Voice Synthesis Agent
    video_path: Optional[str]       # filled by Video Generation Agent
    swapped_video_path: Optional[str]  # filled by Face Swap Agent
    synced_video_path: Optional[str]   # filled by Lip Sync Agent
    status: str                     # pending | audio_done | video_done | swapped | synced | error
    error: Optional[str]


class Phase2State(TypedDict):
    # ── Inputs (from Phase 1 outputs) ──────────────────────────────────────
    scene_manifest_path: str          # path to scene_manifest.json
    character_db_path: str            # path to character_db.json
    images_dir: str                   # path to outputs/images/

    # ── Parsed data ─────────────────────────────────────────────────────────
    scenes: List[Dict[str, Any]]      # raw scenes from manifest
    characters: List[Dict[str, Any]]  # character metadata

    # ── Task graph ──────────────────────────────────────────────────────────
    task_graph: List[SceneTask]       # one task per scene

    # ── Parallel branch results ─────────────────────────────────────────────
    audio_results: List[Dict]         # {scene_id, audio_path, duration}
    video_results: List[Dict]         # {scene_id, video_path, frame_dir}
    swapped_results: List[Dict]       # {scene_id, swapped_video_path}
    synced_results: List[Dict]        # {scene_id, synced_video_path}

    # ── Final outputs ───────────────────────────────────────────────────────
    final_videos: List[str]           # raw_scenes/scene_XX.mp4 paths
    audio_tracks: List[str]           # outputs/audio/scene_XX.wav paths
    task_log: List[Dict]              # structured execution log

    # ── Control ─────────────────────────────────────────────────────────────
    status: str                       # processing | complete | error
    error: Optional[str]