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
