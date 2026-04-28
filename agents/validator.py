#agents/validator.py
def validator_agent(state: dict) -> dict:
    """
    Script Validator Agent
    ----------------------
    Role: Ensures correctness of scripts (both manual and auto-generated).

    Validation Checks (per spec):
    1. Scene headers exist
    2. Dialogue is labeled (speaker present)
    3. Actions/visual cues are structured

    Failure Handling:
    - Raises exception with specific correction suggestions
    """
    print("\n[Validator] Validating script structure...")
    script = state["script"]
    if not script or "scenes" not in script or not script.get("scenes"):
        raise Exception("❌ No scenes detected. Ensure proper 'Scene X:' headings or valid JSON format.")
    errors = []

    # Check 1: Top-level scenes key exists
    if "scenes" not in script:
        raise Exception("❌ Invalid Script: Missing 'scenes' key. Expected format: {'scenes': [...]}")

    if not isinstance(script["scenes"], list) or len(script["scenes"]) == 0:
        raise Exception("❌ Invalid Script: 'scenes' must be a non-empty list.")

    for i, scene in enumerate(script["scenes"]):
        scene_label = f"Scene {i+1}"

        # Check 2: Scene headers (scene_id + location)
        if "scene_id" not in scene:
            errors.append(f"{scene_label}: Missing 'scene_id' (scene header)")
        if "location" not in scene:
            errors.append(f"{scene_label}: Missing 'location' (scene header)")

        # Check 3: Characters listed
        if "characters" not in scene or not scene["characters"]:
            errors.append(f"{scene_label}: Missing or empty 'characters' list")

        # Check 4: Dialogue exists and is labeled
        if "dialogue" not in scene:
            errors.append(f"{scene_label}: Missing 'dialogue' block")
        else:
            for j, line in enumerate(scene["dialogue"]):
                if "speaker" not in line:
                    errors.append(f"{scene_label}, Line {j+1}: Missing 'speaker' (dialogue label)")
                if "line" not in line:
                    errors.append(f"{scene_label}, Line {j+1}: Missing 'line' (dialogue text)")
                # Check 5: Visual cues (action descriptions)
                if "visual_cue" not in line:
                    errors.append(f"{scene_label}, Line {j+1}: Missing 'visual_cue' (action description)")

    if errors:
        suggestion = "\n  - ".join(errors)
        raise Exception(f"❌ Script Validation Failed. Corrections needed:\n  - {suggestion}")

    print(f"[Validator] ✅ Script passed validation. {len(script['scenes'])} scenes verified.")
    return state