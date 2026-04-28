# agents2/video_gen.py
"""
Video Generation Agent
──────────────────────
Role   : Generates scene visuals from character references + scene descriptions.
         Runs in parallel with Voice Synthesis Agent (audio branch).
Outputs: state["video_results"] — [{scene_id, video_path, frame_dir}]
MCP    : query_stock_footage, commit_memory
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from mcp.registry2 import registry2

OUTPUT_DIR = "outputs/frames"


def _collect_visual_cues(dialogue: list) -> list:
    return [
        turn["visual_cue"]
        for turn in dialogue
        if turn.get("visual_cue")
    ]


def _process_single_scene(task: dict, footage_tool, commit_tool) -> dict:
    scene_id    = task["scene_id"]
    location    = task["location"]
    dialogue    = task["dialogue"]
    characters  = task["characters"]
    visual_cues = _collect_visual_cues(dialogue)

    try:
        result = footage_tool({
            "scene_id":    scene_id,
            "location":    location,
            "visual_cues": visual_cues,
            "characters":  characters,
            "output_dir":  OUTPUT_DIR
        })

        commit_tool({
            "text": json.dumps({
                "scene_id":   scene_id,
                "video_path": result["video_path"],
                "frame_dir":  result["frame_dir"],
                "num_frames": result["num_frames"]
            }),
            "metadata": {"type": "video_raw", "scene_id": str(scene_id), "phase": "2"}
        })

        return {
            "scene_id":   scene_id,
            "video_path": result["video_path"],
            "frame_dir":  result["frame_dir"],
            "num_frames": result["num_frames"],
            "method":     result.get("method", "placeholder"),
            "status":     "done"
        }

    except Exception as e:
        print(f"  ❌ Video gen failed for scene {scene_id}: {e}")
        return {
            "scene_id": scene_id,
            "status":   "error",
            "error":    str(e)
        }


def video_gen_agent(state: dict) -> dict:
    print("\n[Video Generation] Starting parallel video generation…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    footage_tool = registry2.get_tool("query_stock_footage")
    commit_tool  = registry2.get_tool("commit_memory")
    task_graph   = state.get("task_graph", [])

    if not task_graph:
        print("  ⚠ No tasks in task graph — skipping video generation")
        state["video_results"] = []
        return state

    video_results = []

    with ThreadPoolExecutor(max_workers=min(4, len(task_graph))) as executor:
        futures = {
            executor.submit(_process_single_scene, task, footage_tool, commit_tool): task["scene_id"]
            for task in task_graph
        }
        for future in as_completed(futures):
            result = future.result()
            video_results.append(result)
            sid = result["scene_id"]
            if result["status"] == "done":
                print(f"  ✅ Scene {sid} video ready → {result['video_path']}  ({result.get('num_frames',0)} frames)")
            else:
                print(f"  ❌ Scene {sid} video FAILED: {result.get('error')}")

    video_results.sort(key=lambda r: r["scene_id"])

    # Update task graph
    video_map = {r["scene_id"]: r for r in video_results}
    for task in state["task_graph"]:
        vr = video_map.get(task["scene_id"], {})
        if vr.get("status") == "done":
            task["video_path"] = vr["video_path"]
            if task["status"] == "audio_done":
                task["status"] = "video_done"
        elif task["status"] != "error":
            task["status"] = "error"
            task["error"]  = vr.get("error", "unknown")

    state["video_results"] = video_results
    done = sum(1 for r in video_results if r["status"] == "done")
    print(f"[Video Generation] ✅ {done}/{len(task_graph)} scenes generated.\n")
    return {
    "video_results": video_results
    }