#agents/image.py
import random
import time

from mcp.registry import registry

def image_agent(state: dict) -> dict:
    """
    Image Synthesizer Agent
    -----------------------
    Role: Generates visual representations of characters.

    Implementation (per spec):
    - Stable Diffusion / ComfyUI (local) accessed via MCP
    - Builds SD prompts from character metadata (appearance + style)

    Output: Character reference images saved to outputs/images/

    MCP Tools used: generate_image, commit_memory
    """
    print("\n[Image Synthesizer] Generating character visuals...")

    tool = registry.get_tool("generate_image")
    memory_tool = registry.get_tool("commit_memory")

    images = []

    for char in state["characters"]:
        print(f"  → Synthesizing image for: {char['name']}")

        # Pass full character metadata to image tool for SD prompt construction
        result = tool({
            "name": char["name"],
            "appearance": char.get("appearance", "cinematic character"),
            "style": char.get("style", "realistic")
        })

        images.append(result["image_path"])
        print(f"  → Saved: {result['image_path']}")
        print(f"  → SD Prompt: {result.get('prompt_used', 'N/A')}")

        # Commit image reference to persistent memory (supports identity handling)
        memory_tool({
            "text": result["image_path"],
            "metadata": {
                "type": "image",
                "character": char["name"],
                "prompt": result.get("prompt_used", "")
            }
        })

        # ✅ 🔥 IMPORTANT FIX (rate limit handling)
        time.sleep(random.uniform(2, 4))
        
    state["images"] = images
    print(f"[Image Synthesizer] ✅ {len(images)} images generated.")

    return state