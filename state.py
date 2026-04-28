#state.py
from typing import TypedDict, List, Dict, Any

class GraphState(TypedDict):
    input_mode: str        # "manual" | "auto"
    user_input: str        # raw user prompt or label
    script: Dict[str, Any] # structured scene_manifest
    characters: List[Dict] # character_db entries
    images: List[str]      # image file paths
    status: str            # "processing" | "complete" | "rejected"
    hitl_feedback: str   # stores reviewer feedback for regeneration