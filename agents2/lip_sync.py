# agents2/lip_sync.py
"""
Lip Sync Agent  —  Fusion Layer
────────────────────────────────
Role   : Convergence point of the audio and video branches.
         Performs frame-by-frame temporal alignment of audio waveform with
         facial geometry in face-swapped video.
Outputs: state["synced_results"]  — [{scene_id, synced_video_path}]
         state["final_videos"]    — paths to raw_scenes/scene_XX.mp4
         state["audio_tracks"]    — paths to outputs/audio/scene_XX.wav
MCP    : lip_sync_aligner, commit_memory
"""
import os
import json
import shutil
from mcp.registry2 import registry2

OUTPUT_DIR     = "outputs/raw_scenes"
AUDIO_COPY_DIR = "outputs/audio"   # already populated; just reference


def lip_sync_agent(state: dict) -> dict:
    print("\n[Lip Sync] Fusing audio + video branches (temporal alignment)…")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    aligner_tool  = registry2.get_tool("lip_sync_aligner")
    commit_tool   = registry2.get_tool("commit_memory")

    task_graph      = state.get("task_graph", [])
    audio_results   = {r["scene_id"]: r for r in state.get("audio_results",   [])}
    swapped_results = {r["scene_id"]: r for r in state.get("swapped_results", [])}

    synced_results = []
    final_videos   = []
    audio_tracks   = []

    for task in task_graph:
        scene_id = task["scene_id"]
        ar = audio_results.get(scene_id,   {})
        sr = swapped_results.get(scene_id, {})

        # ── Pick best available video source ─────────────────────────────────
        video_path = (
            sr.get("swapped_video_path")
            or task.get("video_path")
        )
        audio_path = ar.get("audio_path") or task.get("audio_path")

        if not video_path:
            print(f"  ⚠ Scene {scene_id}: no video source — skipping lip sync")
            synced_results.append({"scene_id": scene_id, "status": "skipped",
                                   "reason": "no video source"})
            continue

        if not audio_path:
            print(f"  ⚠ Scene {scene_id}: no audio source — skipping lip sync")
            synced_results.append({"scene_id": scene_id, "status": "skipped",
                                   "reason": "no audio source"})
            continue

        # ── Gather lipsync inputs ─────────────────────────────────────────────
        # face_swap_dir: where face_swapper wrote slots JSON & swapped video.
        # Falls back to swapped_results entry, then task, then OUTPUT_DIR.
        face_swap_dir = (
            task.get("face_swap_dir")
            or sr.get("face_swap_dir")
            or os.path.dirname(video_path)
            or OUTPUT_DIR
        )

        # character_images: {name: path} needed to reload face images for redraw.
        # face_swap.py now stores this on the task directly.
        character_images = (
            task.get("character_images")
            or sr.get("character_images")
            or {}
        )

        try:
            result = aligner_tool({
                "scene_id":         scene_id,
                "video_path":       video_path,
                "audio_path":       audio_path,
                "output_dir":       OUTPUT_DIR,
                "dialogue":         task.get("dialogue", []),
                "line_wav_paths":   ar.get("line_wavs", []),
                "character_images": character_images,    # face images for portrait redraw
                "face_swap_dir":    face_swap_dir,       # where slots JSON lives
            })

            synced_path = result.get("synced_video_path")

            commit_tool({
                "text": json.dumps({
                    "scene_id":          scene_id,
                    "synced_video_path": synced_path,
                    "audio_duration":    result.get("audio_duration"),
                    "total_frames":      result.get("total_frames")
                }),
                "metadata": {"type": "lip_synced", "scene_id": str(scene_id), "phase": "2"}
            })

            synced_results.append({
                "scene_id":          scene_id,
                "synced_video_path": synced_path,
                "audio_duration":    result.get("audio_duration"),
                "total_frames":      result.get("total_frames"),
                "alignment_log":     result.get("alignment_log"),
                "status":            "done"
            })

            if synced_path:
                final_videos.append(synced_path)
            if audio_path:
                audio_tracks.append(audio_path)

            task["synced_video_path"] = synced_path
            task["status"]            = "synced"

            print(f"  ✅ Scene {scene_id} lip-synced → {synced_path} "
                  f"({result.get('total_frames',0)} frames @ 25fps)")

        except Exception as e:
            print(f"  ❌ Lip sync failed for scene {scene_id}: {e}")
            synced_results.append({
                "scene_id": scene_id,
                "status":   "error",
                "error":    str(e)
            })

    state["synced_results"] = synced_results
    state["final_videos"]   = final_videos
    state["audio_tracks"]   = audio_tracks

    done = sum(1 for r in synced_results if r["status"] == "done")
    print(f"[Lip Sync] ✅ {done}/{len(task_graph)} scenes fully synchronised.\n")
    return {
    "synced_results": synced_results,
    "final_videos":   final_videos,
    "audio_tracks":   audio_tracks
    }