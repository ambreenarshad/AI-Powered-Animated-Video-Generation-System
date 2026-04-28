#agents/scriptwriter.py
from mcp.registry import registry
import re

def extract_num_scenes(prompt: str) -> int:
    """Extract number of scenes from prompt, default to 3 if not found."""
    # Match patterns like "3-scene", "3 scene", "three scenes", "5 scenes" etc.
    word_to_num = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
    }

    # Match digit patterns: "3-scene", "3 scene(s)", "3-act"
    digit_match = re.search(r'\b(\d+)\s*[-]?\s*scene', prompt, re.IGNORECASE)
    if digit_match:
        return int(digit_match.group(1))

    # Match word patterns: "three scenes", "five-scene"
    word_pattern = '|'.join(word_to_num.keys())
    word_match = re.search(rf'\b({word_pattern})\s*[-]?\s*scene', prompt, re.IGNORECASE)
    if word_match:
        return word_to_num[word_match.group(1).lower()]

    return 3  # default


def scriptwriter_agent(state: dict) -> dict:
    """
    Scriptwriter Agent
    ------------------
    Handles both initial generation and regeneration with HITL feedback.
    Extracts num_scenes from the user prompt; defaults to 3 if not specified.
    MCP Tools: generate_script_segment, commit_memory
    """
    # SKIP if manual input already provided
    if state.get("input_mode") == "manual" and state.get("script"):
        print("[Scriptwriter] ⏭️ Skipping generation (manual input provided).")
        return state
    
    tool = registry.get_tool("generate_script_segment")
    memory_tool = registry.get_tool("commit_memory")

    feedback = state.get("hitl_feedback", "")
    base_prompt = state["user_input"]

    # Extract scene count from original prompt
    num_scenes = extract_num_scenes(base_prompt)

    if feedback:
        print(f"\n[Scriptwriter] Regenerating script with feedback: '{feedback}'")
        prompt = f"{base_prompt}\n\nRevision feedback from reviewer: {feedback}. Please address this feedback in the new version."
    else:
        print(f"\n[Scriptwriter] Generating script ({num_scenes} scenes)...")
        prompt = base_prompt

    result = tool({
        "prompt": prompt,
        "num_scenes": num_scenes
    })

    state["script"] = result
    state["hitl_feedback"] = ""  # clear after use

    print(f"[Scriptwriter] Generated {len(result.get('scenes', []))} scenes.")

    memory_tool({
        "text": str(result),
        "metadata": {"type": "script"}
    })

    return state