"""
tests/test_edit_agent.py
─────────────────────────
Test coverage for edit intent classification across ≥10 edit query types.
Uses only the rule-based fallback (no LLM needed) so tests run offline.

Run with:  python -m pytest tests/test_edit_agent.py -v
       or:  python tests/test_edit_agent.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.edit_agent import _rule_based_classify


# ── Test cases ────────────────────────────────────────────────────────────────

CASES = [
    # (query, expected_intent, expected_target, scope_contains)
    (
        "Change voice tone to whispered for scene 2",
        "change_voice_tone", "audio", "scene:2",
    ),
    (
        "Make the scene darker",
        "make_scene_darker", "video_frame", "all",
    ),
    (
        "Make scene 1 brighter",
        "make_scene_brighter", "video_frame", "scene:1",
    ),
    (
        "Add background jazz music",
        "add_background_music", "audio", "all",
    ),
    (
        "Remove subtitle from the video",
        "remove_subtitle", "video", "all",
    ),
    (
        "Add subtitle please",
        "add_subtitle", "video", "all",
    ),
    (
        "Change character Jack's design to noir style",
        "change_character_design", "video_frame", "character:Jack",
    ),
    (
        "Speed up scene 3",
        "speed_up_scene", "video", "scene:3",
    ),
    (
        "Slow down the current scene",
        "slow_down_scene", "video", "all",
    ),
    (
        "Regenerate the script",
        "regenerate_script", "script", "all",
    ),
    (
        "Apply noir filter to all scenes",
        "apply_image_filter", "video_frame", "all",
    ),
    (
        "Apply sepia filter to scene 2",
        "apply_image_filter", "video_frame", "scene:2",
    ),
    (
        "Change the dialogue in scene 1",
        "change_dialogue", "script", "scene:1",
    ),
    (
        "Recompose and rebuild the video",
        "recompose_video", "video", "all",
    ),
    (
        "Change scene location to Paris",
        "change_scene_location", "video_frame", "all",
    ),
    (
        "Make it darker and more dramatic in scene 2",
        "make_scene_darker", "video_frame", "scene:2",
    ),
    (
        "Deep voice for character May",
        "change_voice_tone", "audio", "character:May",
    ),
    (
        "Add warm color grading",
        "apply_image_filter", "video_frame", "all",
    ),
    (
        "Rewrite script with more tension",
        "regenerate_script", "script", "all",
    ),
    (
        "Speed up to make it quicker overall",
        "speed_up_scene", "video", "all",
    ),
]


def run_tests():
    passed = 0
    failed = 0
    errors = []

    print("=" * 70)
    print("  Edit Intent Classification — Test Suite")
    print("=" * 70)

    for i, (query, exp_intent, exp_target, exp_scope) in enumerate(CASES, 1):
        result = _rule_based_classify(query)

        ok_intent = result["intent"]  == exp_intent
        ok_target = result["target"]  == exp_target
        ok_scope  = exp_scope in result["scope"] or result["scope"] == exp_scope

        passed_case = ok_intent and ok_target and ok_scope

        status = "✅" if passed_case else "❌"
        print(f"\n  [{i:02d}] {status} Query: \"{query}\"")

        if not ok_intent:
            print(f"        intent:  expected={exp_intent!r}  got={result['intent']!r}")
        if not ok_target:
            print(f"        target:  expected={exp_target!r}  got={result['target']!r}")
        if not ok_scope:
            print(f"        scope:   expected contains {exp_scope!r}  got={result['scope']!r}")

        if passed_case:
            passed += 1
            print(f"        intent={result['intent']}  target={result['target']}  scope={result['scope']}")
        else:
            failed += 1
            errors.append((i, query, result))

    print("\n" + "=" * 70)
    print(f"  Results: {passed}/{len(CASES)} passed, {failed} failed")
    print("=" * 70)

    if failed:
        print("\nFailed cases:")
        for idx, q, r in errors:
            print(f"  [{idx:02d}] {q!r}")
            print(f"       → {r}")

    return failed == 0


# ── Pytest integration ────────────────────────────────────────────────────────

import pytest

@pytest.mark.parametrize("query,exp_intent,exp_target,exp_scope", CASES)
def test_classify(query, exp_intent, exp_target, exp_scope):
    result = _rule_based_classify(query)
    assert result["intent"] == exp_intent,  \
        f"Intent mismatch for '{query}': expected '{exp_intent}', got '{result['intent']}'"
    assert result["target"] == exp_target,  \
        f"Target mismatch for '{query}': expected '{exp_target}', got '{result['target']}'"
    assert exp_scope in result["scope"] or result["scope"] == exp_scope, \
        f"Scope mismatch for '{query}': expected '{exp_scope}', got '{result['scope']}'"


def test_parameters_populated():
    """Ensure common parameters are filled for key intents."""
    r = _rule_based_classify("Change voice tone to whispered")
    assert r["parameters"].get("tone") == "whispered"

    r = _rule_based_classify("Make scene darker")
    assert r["parameters"].get("brightness", 0) < 0

    r = _rule_based_classify("Add background music")
    assert "volume" in r["parameters"]

    r = _rule_based_classify("Apply noir filter")
    assert r["parameters"].get("filter") == "noir"

    r = _rule_based_classify("Apply sepia filter")
    assert r["parameters"].get("filter") == "sepia"

    r = _rule_based_classify("Speed up scene 2")
    assert r["parameters"].get("factor", 1.0) > 1.0

    r = _rule_based_classify("Slow down scene 1")
    assert r["parameters"].get("factor", 1.0) < 1.0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)