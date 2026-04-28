# agents2/scene_parser.py
"""
Scene Parser Agent
──────────────────
Role   : Loads scene_manifest.json + character_db.json and decomposes
         them into a parallelisable task graph via the get_task_graph MCP tool.
Outputs: state["task_graph"] — one SceneTask per scene.
"""
import json
import os
from mcp.registry2 import registry2


def scene_parser_agent(state: dict) -> dict:
    print("\n[Scene Parser] Loading Phase 1 outputs…")

    # ── Load scene manifest ──────────────────────────────────────────────────
    manifest_path = state.get("scene_manifest_path", "outputs/scene_manifest.json")
    char_db_path  = state.get("character_db_path",   "outputs/character_db.json")
    images_dir    = state.get("images_dir",           "outputs/images")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(
            f"[Scene Parser] ❌ scene_manifest.json not found at '{manifest_path}'. "
            "Run Phase 1 first."
        )

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    characters = []
    if os.path.exists(char_db_path):
        with open(char_db_path, "r") as f:
            characters = json.load(f)
        print(f"  → Loaded {len(characters)} characters from character_db.json")
    else:
        print("  ⚠ character_db.json not found — proceeding without character metadata")

    scenes = manifest.get("scenes", [])
    if not scenes:
        raise ValueError("[Scene Parser] ❌ No scenes found in scene_manifest.json")

    print(f"  → Parsed {len(scenes)} scenes from manifest")

    # ── Attach image paths to character metadata ─────────────────────────────
    for char in characters:
        safe_name  = char["name"].replace(" ", "_").replace("/", "_")
        img_path   = os.path.join(images_dir, f"{safe_name}.png")
        placeholder = os.path.join(images_dir, f"{safe_name}_placeholder.txt")
        if os.path.exists(img_path):
            char["image_path"] = img_path
        elif os.path.exists(placeholder):
            char["image_path"] = placeholder
        else:
            char["image_path"] = ""

    # ── Build task graph via MCP ──────────────────────────────────────────────
    get_task_graph = registry2.get_tool("get_task_graph")
    result = get_task_graph({
        "scenes":     scenes,
        "characters": characters
    })

    task_graph = result["task_graph"]

    # ── Commit to memory ─────────────────────────────────────────────────────
    commit = registry2.get_tool("commit_memory")
    commit({
        "text": json.dumps({"task_graph_summary": [
            {"scene_id": t["scene_id"], "location": t["location"],
             "characters": t["characters"]}
            for t in task_graph
        ]}),
        "metadata": {"type": "task_graph", "phase": "2"}
    })

    state["scenes"]     = scenes
    state["characters"] = characters
    state["task_graph"] = task_graph

    print(f"[Scene Parser] ✅ Task graph built — {len(task_graph)} tasks ready for parallel execution.\n")
    return {
    "scenes": scenes,
    "characters": characters,
    "task_graph": task_graph
    }