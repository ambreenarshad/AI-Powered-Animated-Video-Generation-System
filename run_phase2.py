# run_phase2.py
"""
Headless CLI runner for Phase 2  —  Audio Generation.

Usage:
    python run_phase2.py
    python run_phase2.py --manifest outputs/scene_manifest.json \
                         --chardb   outputs/character_db.json
"""

import argparse
import sys
import os


def main():
    parser = argparse.ArgumentParser(
        description="PROJECT MONTAGE Phase 2 — Audio Generation (headless)"
    )
    parser.add_argument("--manifest", default="outputs/scene_manifest.json",
                        help="Path to scene_manifest.json from Phase 1")
    parser.add_argument("--chardb",   default="outputs/character_db.json",
                        help="Path to character_db.json from Phase 1")
    args = parser.parse_args()

    print("=" * 60)
    print("  PROJECT MONTAGE — Phase 2: Audio Generation")
    print("=" * 60)

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
        "scenes":              [],
        "characters":          [],
        "task_graph":          [],
        "audio_results":       [],
        "audio_tracks":        [],
        "timing_manifest":     [],
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
    print(f"    Audio tracks     : {result.get('audio_tracks', [])}")
    print(f"    Timing manifest  : outputs/timing_manifest.json")
    print(f"    Task log         : outputs/logs/phase2_task_log.json")
    print(f"    Phase manifest   : outputs/phase2_manifest.json")
    print("=" * 60)


if __name__ == "__main__":
    main()