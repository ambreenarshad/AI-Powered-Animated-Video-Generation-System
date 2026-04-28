# state2.py
"""
Phase 2 Graph State
Carries all data through the audio synthesis pipeline.
"""
from typing import TypedDict, List, Dict, Any, Optional


class SceneTask(TypedDict):
    scene_id:   int
    location:   str
    characters: List[str]
    dialogue:   List[Dict[str, Any]]
    char_meta:  List[Dict[str, Any]]
    audio_path: Optional[str]       # filled by Voice Synthesis Agent
    line_wavs:  List[str]           # per-line wav paths
    status:     str                 # pending | audio_done | error
    error:      Optional[str]


class Phase2State(TypedDict):
    # ── Inputs (from Phase 1 outputs) ─────────────────────────────────────
    scene_manifest_path: str
    character_db_path:   str

    # ── Parsed data ────────────────────────────────────────────────────────
    scenes:     List[Dict[str, Any]]
    characters: List[Dict[str, Any]]

    # ── Task graph ─────────────────────────────────────────────────────────
    task_graph: List[SceneTask]

    # ── Results ────────────────────────────────────────────────────────────
    audio_results: List[Dict]   # {scene_id, audio_path, duration, line_wavs}

    # ── Final outputs ──────────────────────────────────────────────────────
    audio_tracks:     List[str]  # outputs/audio/scene_XX.wav paths
    timing_manifest:  List[Dict] # [{scene_id, audio_file, start_ms, end_ms}]
    task_log:         List[Dict]

    # ── Control ────────────────────────────────────────────────────────────
    status: str
    error:  Optional[str]