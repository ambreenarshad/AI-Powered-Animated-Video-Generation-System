#utils/json_utils.py
import json
import os

def save_outputs(state):
    os.makedirs("outputs", exist_ok=True)

    with open("outputs/scene_manifest.json", "w") as f:
        json.dump(state["script"], f, indent=2)

    with open("outputs/character_db.json", "w") as f:
        json.dump(state["characters"], f, indent=2)