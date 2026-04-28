#agents/character.py
from mcp.registry import registry
from llm import get_llm_response
import json
import re

def extract_character_details(char_name: str, script_context: str) -> dict:
    """Use LLM to generate rich character metadata from script context."""
    prompt = f"""Given this screenplay context, describe the character "{char_name}".
Respond ONLY with a valid JSON object, no extra text:
{{
  "name": "{char_name}",
  "gender": "male or female — infer from the character's name, dialogue, and how other characters refer to them",
  "personality": "2-3 personality traits based on their dialogue",
  "appearance": "physical description suitable for image generation",
  "style": "visual/cinematic style (e.g. noir, realistic, stylized)"
}}

Script context:
{script_context}"""

    response = get_llm_response(prompt)

    try:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            # Normalise gender to a clean "male"/"female" string; default to "male"
            # if the LLM returned something unexpected.
            raw_gender = str(data.get("gender", "")).lower().strip()
            data["gender"] = "female" if "female" in raw_gender else "male"
            return data
    except:
        pass

    # Fallback if LLM doesn't return clean JSON
    return {
        "name": char_name,
        "gender": "male",
        "personality": "determined, complex",
        "appearance": "cinematic character, realistic proportions",
        "style": "realistic"
    }


def character_agent(state: dict) -> dict:
    """
    Character Designer Agent
    ------------------------
    Role: Extracts and formalizes character identities from the script.

    Outputs per character (per spec):
    - Name
    - Gender
    - Personality traits
    - Appearance description
    - Reference style

    Key Feature: Maintains identity consistency across scenes.
    Gender is stored in character_db.json and used downstream by
    voice_cloning_synthesizer for voice selection (no name/pronoun heuristics).

    MCP Tools used: commit_memory
    """
    print("\n[Character Designer] Extracting character identities...")

    memory_tool = registry.get_tool("commit_memory")

    # Build script context string for LLM
    script_context = json.dumps(state["script"], indent=2)

    # Collect unique characters across all scenes
    seen = set()
    characters = []

    for scene in state["script"]["scenes"]:
        for char_name in scene.get("characters", []):
            if char_name not in seen:
                seen.add(char_name)

                # Generate rich character metadata via LLM (includes gender)
                char_data = extract_character_details(char_name, script_context)
                characters.append(char_data)

                print(f"  → Character: {char_name} | Gender: {char_data.get('gender')} | Style: {char_data.get('style')}")

                # Commit each character to persistent memory
                memory_tool({
                    "text": str(char_data),
                    "metadata": {"type": "character", "name": char_name}
                })

    state["characters"] = characters
    print(f"[Character Designer] ✅ {len(characters)} characters processed.")

    return state