# agents2/face_swap.py
"""
Face Swap Agent
───────────────
Role   : Maps generated character images onto video frames.
         Validates identity before every swap to prevent leakage.
Outputs: state["swapped_results"] — [{scene_id, swapped_video_path}]
MCP    : face_swapper, identity_validator, commit_memory
"""
import os
import json
from mcp.registry2 import registry2

OUTPUT_DIR = "outputs/frames"


def face_swap_agent(state: dict) -> dict:
    print("\n[Face Swap] Mapping character identities onto video frames…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    swap_tool     = registry2.get_tool("face_swapper")
    validate_tool = registry2.get_tool("identity_validator")
    commit_tool   = registry2.get_tool("commit_memory")

    task_graph    = state.get("task_graph", [])
    video_results = {r["scene_id"]: r for r in state.get("video_results", [])}
    characters    = state.get("characters", [])

    # Build {name: image_path} lookup from character DB
    char_image_map = {
        c["name"]: c.get("image_path", "")
        for c in characters
    }

    swapped_results = []

    for task in task_graph:
        scene_id = task["scene_id"]
        vr       = video_results.get(scene_id, {})

        if vr.get("status") != "done":
            print(f"  ⚠ Scene {scene_id}: no valid video — skipping face swap")
            swapped_results.append({
                "scene_id": scene_id,
                "status":   "skipped",
                "reason":   "no valid source video"
            })
            continue

        video_path = vr["video_path"]

        # Only attempt swap for characters present in this scene
        scene_char_images = {
            name: char_image_map.get(name, "")
            for name in task["characters"]
        }

        # Pre-validate each character
        validated_images = {}
        for char_name, img_path in scene_char_images.items():
            check = validate_tool({
                "character_name": char_name,
                "image_path":     img_path,
                "character_db":   characters
            })
            if check["valid"]:
                validated_images[char_name] = img_path
            else:
                print(f"  ⚠ Identity check failed for {char_name}: {check['reason']}")

        try:
            result = swap_tool({
                "scene_id":        scene_id,
                "video_path":      video_path,
                "character_images": validated_images,
                "output_dir":      OUTPUT_DIR
            })

            commit_tool({
                "text": json.dumps({
                    "scene_id":           scene_id,
                    "swapped_video_path": result["swapped_video_path"],
                    "validated_chars":    result["validated_chars"]
                }),
                "metadata": {"type": "face_swapped", "scene_id": str(scene_id), "phase": "2"}
            })

            swapped_results.append({
                "scene_id":           scene_id,
                "swapped_video_path": result["swapped_video_path"],
                "validated_chars":    result["validated_chars"],
                "face_swap_dir":      OUTPUT_DIR,           # ← NEW: so lip_sync can find slots JSON
                "character_images":   validated_images,     # ← NEW: so lip_sync can reload face imgs
                "status":             "done"
            })

            # ── Store on task so lip_sync_agent can read directly ──────────
            task["swapped_video_path"] = result["swapped_video_path"]
            task["character_images"]   = validated_images   # ← NEW
            task["face_swap_dir"]      = OUTPUT_DIR         # ← NEW

            if task["status"] == "video_done":
                task["status"] = "swapped"
            print(f"  ✅ Scene {scene_id} face-swapped → {result['swapped_video_path']}")

        except Exception as e:
            print(f"  ❌ Face swap failed for scene {scene_id}: {e}")
            swapped_results.append({
                "scene_id": scene_id,
                "status":   "error",
                "error":    str(e)
            })

    state["swapped_results"] = swapped_results
    done = sum(1 for r in swapped_results if r["status"] == "done")
    print(f"[Face Swap] ✅ {done}/{len(task_graph)} scenes face-swapped.\n")
    return {
    "swapped_results": swapped_results
    }