# run_phase2.py
"""
Headless CLI runner for Phase 2.
Use this when running on a server without a display,
or to test the pipeline without the Tkinter GUI.

Usage:
    python run_phase2.py
    python run_phase2.py --manifest outputs/scene_manifest.json \
                         --chardb   outputs/character_db.json   \
                         --images   outputs/images
"""

import argparse
import json
import sys
import os


def main():
    parser = argparse.ArgumentParser(description="PROJECT MONTAGE Phase 2 — headless runner")
    parser.add_argument("--manifest", default="outputs/scene_manifest.json",
                        help="Path to scene_manifest.json from Phase 1")
    parser.add_argument("--chardb",   default="outputs/character_db.json",
                        help="Path to character_db.json from Phase 1")
    parser.add_argument("--images",   default="outputs/images",
                        help="Path to images directory from Phase 1")
    args = parser.parse_args()

    print("=" * 60)
    print("  PROJECT MONTAGE — Phase 2: The Studio Floor")
    print("=" * 60)

    # Validate inputs
    for path, label in [(args.manifest, "scene_manifest.json"),
                        (args.chardb,   "character_db.json")]:
        if not os.path.exists(path):
            print(f"❌ {label} not found at '{path}'. Run Phase 1 first.")
            sys.exit(1)

    from mcp.init2 import register_tools_p2
    from graph2 import build_graph2
    from utils.json_utils2 import save_outputs_p2

    register_tools_p2()

    state = {
        "scene_manifest_path": args.manifest,
        "character_db_path":   args.chardb,
        "images_dir":          args.images,
        "scenes":              [],
        "characters":          [],
        "task_graph":          [],
        "audio_results":       [],
        "video_results":       [],
        "swapped_results":     [],
        "synced_results":      [],
        "final_videos":        [],
        "audio_tracks":        [],
        "task_log":            [],
        "status":              "processing",
        "error":               None,
    }

    print("\n▶  Building graph…")
    graph = build_graph2()

    print("▶  Invoking pipeline…\n")
    result = graph.invoke(state)

    save_outputs_p2(result)

    print("\n" + "=" * 60)
    print("✅  Phase 2 Complete!")
    print(f"    Final videos : {result.get('final_videos', [])}")
    print(f"    Audio tracks : {result.get('audio_tracks', [])}")
    print("    Logs         : outputs/logs/phase2_task_log.json")
    print("    Manifest     : outputs/phase2_manifest.json")
    print("=" * 60)


if __name__ == "__main__":
    main()