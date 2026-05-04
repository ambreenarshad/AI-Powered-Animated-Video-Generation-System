"""
agents/edit_agent.py
─────────────────────
Edit Intent Classification Agent
Classifies free-text edit queries into structured intent objects.
Uses LLM for semantic understanding + rule-based fallbacks.

Supported intent categories:
  - change_voice_tone      → audio
  - add_background_music   → audio
  - remove_subtitle        → video
  - speed_up_scene         → video
  - make_scene_darker      → video_frame
  - make_scene_brighter    → video_frame
  - change_character_design→ video_frame
  - apply_filter           → video_frame
  - regenerate_script      → script
  - change_dialogue        → script
"""

import re
import json
from llm import get_llm_response


# ── Keyword-based fallback rules ──────────────────────────────────────────────

_INTENT_RULES = [
    # (pattern, intent, target)
    (r"voice|tone|speech|speak|narrator|whisper|louder|softer|tts", "change_voice_tone", "audio"),
    (r"background\s*music|soundtrack|music|bgm|ambient|score", "add_background_music", "audio"),
    (r"remov.*subtitle|no\s*subtitle|without\s*subtitle|hide\s*subtitle", "remove_subtitle", "video"),
    (r"speed\s*up|faster|slow\s*down|slower|pace|tempo", "speed_up_scene", "video"),
    (r"dark(?:er|en)|dim|noir|shadow|moody|gloomy|sinister", "make_scene_darker", "video_frame"),
    (r"bright(?:er|en)|lighter|vivid|saturated|vibrant|sunny", "make_scene_brighter", "video_frame"),
    (r"character.*design|redesign.*character|look.*different|appearance|outfit|costume", "change_character_design", "video_frame"),
    (r"filter|effect|sepia|vintage|black.and.white|b&w|grainy|cinematic", "apply_filter", "video_frame"),
    (r"regenerate.*script|rewrite.*script|new.*script|redo.*script|different.*story", "regenerate_script", "script"),
    (r"change.*dialogue|rewrite.*dialogue|different.*line|edit.*dialog", "change_dialogue", "script"),
    (r"add.*subtitle|subtitle|caption|closed.*caption", "remove_subtitle", "video"),  # toggles subtitle
    (r"recompose|re-render|render.*again|redo.*video|export.*again", "recompose_video", "video"),
]

_SCOPE_RULES = [
    (r"scene\s+(\d+)", "scene"),
    (r"character[:\s]+([A-Za-z\s]+?)(?:\s|$|,)", "character"),
    (r"all\s+scenes?", "all_scenes"),
    (r"all\s+characters?", "all_characters"),
]

_FILTER_PRESETS = {
    "sepia":         {"colorchannelmixer": "rr=0.393:rg=0.769:rb=0.189:gr=0.349:gg=0.686:gb=0.168:br=0.272:bg=0.534:bb=0.131"},
    "noir":          {"colorchannelmixer": "rr=0.299:rg=0.587:rb=0.114:gr=0.299:gg=0.587:gb=0.114:br=0.299:bg=0.587:bb=0.114", "curves": "all='0/0 0.5/0.3 1/0.8'"},
    "vintage":       {"fade": "type=in:duration=0.5", "colorchannelmixer": "rr=0.7:rg=0.3:rb=0.0:gr=0.1:gg=0.8:gb=0.1:br=0.1:bg=0.1:bb=0.6"},
    "black_white":   {"colorchannelmixer": "rr=0.3:rg=0.6:rb=0.1:gr=0.3:gg=0.6:gb=0.1:br=0.3:bg=0.6:bb=0.1"},
    "grainy":        {"noise": "alls=20:allf=t"},
    "cinematic":     {"vignette": "PI/4", "curves": "all='0/0 0.3/0.2 0.7/0.8 1/1'"},
    "darker":        {"curves": "all='0/0 0.5/0.3 1/0.75'"},
    "brighter":      {"curves": "all='0/0 0.5/0.65 1/1'"},
}


def _detect_scope(query: str) -> dict:
    """Extract scope (scene/character) from query text."""
    q = query.lower()
    scope = "all"
    scope_value = None

    for pattern, scope_type in _SCOPE_RULES:
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            scope = scope_type
            if m.lastindex and m.lastindex >= 1:
                scope_value = m.group(1).strip()
            break

    if scope_value:
        return {"scope": f"{scope}:{scope_value}"}
    return {"scope": scope}


def _extract_filters(query: str) -> list:
    """Extract filter names from query."""
    q = query.lower()
    found = []
    for name in _FILTER_PRESETS:
        if name.replace("_", " ") in q or name in q:
            found.append(name)
    # Also match "darker", "brighter" as filter keywords
    if "dark" in q and "darker" not in found:
        found.append("darker")
    if "bright" in q and "brighter" not in found:
        found.append("brighter")
    if "black and white" in q or "b&w" in q or "grayscale" in q:
        found.append("black_white")
    return found


def _rule_based_classify(query: str) -> dict | None:
    """Fast keyword-based classification before calling LLM."""
    q = query.lower().strip()
    for pattern, intent, target in _INTENT_RULES:
        if re.search(pattern, q, re.IGNORECASE):
            scope_info = _detect_scope(query)
            params = {}

            # Extract tone for voice
            if intent == "change_voice_tone":
                tone_match = re.search(
                    r"(whisper(?:ed)?|soft|hard|deep|high|low|neutral|dramatic|calm|angry|sad|happy)",
                    q, re.IGNORECASE
                )
                params["tone"] = tone_match.group(1) if tone_match else "neutral"

            # Extract speed factor
            elif intent == "speed_up_scene":
                if re.search(r"slow|slower", q):
                    params["speed_factor"] = 0.75
                    params["direction"] = "slower"
                else:
                    params["speed_factor"] = 1.5
                    params["direction"] = "faster"

            # Extract filters
            elif intent in ("apply_filter", "make_scene_darker", "make_scene_brighter"):
                filters = _extract_filters(query)
                if filters:
                    params["filters"] = filters
                    params["filter_presets"] = {f: _FILTER_PRESETS[f] for f in filters if f in _FILTER_PRESETS}

            # Subtitle toggle
            elif intent == "remove_subtitle":
                params["enable_subtitles"] = not bool(re.search(r"add|include|show|enable", q))

            return {
                "intent":     intent,
                "target":     target,
                "parameters": params,
                **scope_info,
            }
    return None


def classify_edit_intent(query: str) -> dict:
    """
    Classify a free-text edit query into a structured intent object.
    Tries rule-based first; falls back to LLM if unrecognised.

    Returns:
    {
        "intent":     str,
        "target":     "audio" | "video_frame" | "video" | "script",
        "scope":      str,
        "parameters": dict,
        "raw_query":  str,
    }
    """
    # 1. Try fast rule-based classification
    result = _rule_based_classify(query)
    if result:
        result["raw_query"] = query
        print(f"[EditAgent] Rule-based: {result['intent']} → {result['target']}")
        return result

    # 2. Fall back to LLM classification
    prompt = f"""You are an AI video editing assistant. Classify this edit request into a structured JSON intent.

Edit request: "{query}"

Available intents and targets:
- change_voice_tone → audio
- add_background_music → audio  
- remove_subtitle → video (enable_subtitles: true/false)
- speed_up_scene → video (speed_factor: float, direction: faster/slower)
- make_scene_darker → video_frame (filters: list)
- make_scene_brighter → video_frame (filters: list)
- change_character_design → video_frame (description: str)
- apply_filter → video_frame (filters: list, filter_presets: dict)
- regenerate_script → script (seed_changes: str)
- change_dialogue → script (character: str, new_text: str)
- recompose_video → video

Respond ONLY with valid JSON:
{{
  "intent": "intent_name",
  "target": "audio|video_frame|video|script",
  "scope": "all|scene:N|character:Name|all_scenes|all_characters",
  "parameters": {{}}
}}"""

    try:
        response = get_llm_response(prompt)
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            data["raw_query"] = query
            print(f"[EditAgent] LLM classified: {data.get('intent')} → {data.get('target')}")
            return data
    except Exception as e:
        print(f"[EditAgent] LLM classification failed: {e}")

    # 3. Ultimate fallback — generic video recompose
    return {
        "intent":     "recompose_video",
        "target":     "video",
        "scope":      "all",
        "parameters": {"description": query},
        "raw_query":  query,
    }


def get_filter_presets() -> dict:
    """Return all available filter presets."""
    return _FILTER_PRESETS.copy()