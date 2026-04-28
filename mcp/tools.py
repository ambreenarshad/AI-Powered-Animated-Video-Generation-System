#mcp/tools.py
from random import random
from time import time
import urllib

from llm import get_llm_response
from memory.vector_store import store_memory, query_memory
import json
import os
import re
import requests
from dotenv import load_dotenv

load_dotenv()

HF_API_KEY = os.getenv("HF_API_KEYY")


# ─── MCP Tool Schemas ─────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "generate_script_segment": {
        "tool": "generate_script_segment",
        "input_schema": {
            "prompt": "string - the creative prompt for script generation",
            "num_scenes": "int - number of scenes to generate (default: 3)"
        }
    },
    "commit_memory": {
        "tool": "commit_memory",
        "input_schema": {
            "text": "string - content to store",
            "metadata": "dict - metadata tags e.g. {'type': 'script'}"
        }
    },
    "generate_image": {
        "tool": "generate_image",
        "input_schema": {
            "name": "string - character name",
            "appearance": "string - appearance description (optional)",
            "style": "string - visual style (optional)"
        }
    }
}


def extract_json(text):
    try:
        return json.loads(text)
    except:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    raise Exception("No valid JSON found in LLM response")


# ─── TOOL 1: Script Generation ────────────────────────────────────────────────

def generate_script_segment(input_data: dict) -> dict:
    prompt = input_data["prompt"]
    num_scenes = input_data.get("num_scenes", 3)

    memory_context = query_memory(prompt)
    context_text = "\n".join([doc.page_content for doc in memory_context]) if memory_context else "No prior context."

    final_prompt = f"""You are a professional screenplay writer.
Generate a structured screenplay in VALID JSON only. No explanation, no markdown, no extra text.

Context from memory:
{context_text}

User Prompt:
{prompt}

Output ONLY this JSON format:
{{
  "scenes": [
    {{
      "scene_id": 1,
      "location": "specific location name",
      "characters": ["Character A", "Character B"],
      "dialogue": [
        {{
          "speaker": "Character A",
          "line": "dialogue text here",
          "visual_cue": "cinematic direction e.g. Close-up, tense lighting"
        }}
      ]
    }}
  ]
}}

Generate exactly {num_scenes} scenes. Output ONLY the JSON object."""

    response_text = get_llm_response(final_prompt)

    try:
        return extract_json(response_text)
    except Exception as e:
        raise Exception(f"Failed to parse LLM output into JSON: {e}\nRaw output:\n{response_text[:500]}")


# ─── TOOL 2: Memory Commit ────────────────────────────────────────────────────

def commit_memory(input_data: dict) -> dict:
    store_memory(
        text=input_data["text"],
        metadata=input_data.get("metadata", {})
    )
    return {"status": "stored"}


# ─── TOOL 3: Image Generation ─────────────────────────────────────────────────
# def generate_image(input_data: dict) -> dict:
#     os.makedirs("outputs/images", exist_ok=True)

#     char_name = input_data["name"]
#     appearance = input_data.get("appearance", "cinematic realistic style")
#     style = input_data.get("style", "realistic")

#     # 🔥 Shorter prompt (important for Pollinations)
#     sd_prompt = f"Portrait of {char_name}, {appearance}, {style}, cinematic lighting, detailed, 4k"

#     safe_name = char_name.replace(' ', '_').replace('/', '_')
#     filename = f"outputs/images/{safe_name}.png"

#     encoded_prompt = urllib.parse.quote(sd_prompt)
#     url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=512&height=512"

#     MAX_RETRIES = 3

#     for attempt in range(MAX_RETRIES):
#         try:
#             print(f"  Attempt {attempt+1} for {char_name}...")

#             response = requests.get(url, timeout=90)

#             if response.status_code == 200:
#                 with open(filename, "wb") as f:
#                     f.write(response.content)

#                 print(f"  Image generated: {filename}")
#                 return {"image_path": filename, "prompt_used": sd_prompt}

#             elif response.status_code == 429:
#                 print("  Rate limited. Waiting before retry...")
#                 time.sleep(5 + random.uniform(1, 3))

#             else:
#                 print(f"  Error {response.status_code}")

#         except requests.exceptions.Timeout:
#             print("  Timeout. Retrying...")
#             time.sleep(5)

#         except Exception as e:
#             print(f"  Exception: {e}")
#             time.sleep(3)

#     # ❌ fallback
#     placeholder = filename.replace(".png", "_placeholder.txt")
#     with open(placeholder, "w") as f:
#         f.write(f"PROMPT: {sd_prompt}")

#     return {"image_path": placeholder, "prompt_used": sd_prompt}


def generate_image(input_data: dict) -> dict:
    """
    MCP Tool: generate_image
    Calls Hugging Face Inference API (SDXL) — returns raw PNG bytes directly.
    Falls back to a placeholder text file if API key missing or call fails.
    """
    os.makedirs("outputs/images", exist_ok=True)

    char_name = input_data["name"]
    appearance = input_data.get("appearance", "cinematic realistic style")
    style = input_data.get("style", "realistic")

    sd_prompt = f"Portrait of {char_name}, {appearance}, {style}, ultra realistic, cinematic lighting, highly detailed, 4k, sharp focus"
    safe_name = char_name.replace(' ', '_').replace('/', '_')
    filename = f"outputs/images/{safe_name}.png"

    # New model endpoint
    API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

    if HF_API_KEY:
        try:
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {HF_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": sd_prompt,
                    "parameters": {
                        "num_inference_steps": 8,      # 4-10 is good for schnell (higher = better but slower)
                        "guidance_scale": 0.0,         # FLUX.1-schnell usually works best at 0.0
                        "width": 1024,
                        "height": 1024,
                        # "seed": 42                   # Uncomment if you want reproducible results
                    }
                },
                timeout=180
            )

            if response.status_code == 200:
                with open(filename, "wb") as f:
                    f.write(response.content)
                print(f"  ✅ Image generated with FLUX.1-schnell: {filename}")
                return {"image_path": filename, "prompt_used": sd_prompt}

            else:
                print(f"  ❌ HF API error {response.status_code} for {char_name}: {response.text[:300]}")

        except requests.exceptions.Timeout:
            print(f"  ⏳ HF API timed out for {char_name}.")
        except Exception as e:
            print(f"  ❌ Error using FLUX: {e}")
    else:
        print(f"  ⚠️ HF_API_KEY not set — using placeholder.")

    # Fallback placeholder
    placeholder = filename.replace(".png", "_placeholder.txt")
    with open(placeholder, "w") as f:
        f.write(f"SD_PROMPT: {sd_prompt}")
    print(f"  Placeholder written: {placeholder}")

    return {"image_path": placeholder, "prompt_used": sd_prompt}