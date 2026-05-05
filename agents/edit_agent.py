"""
agents/edit_agent.py
─────────────────────
Edit Intent Classification Agent
Classifies free-text edit queries into structured intent objects.
Uses rule-based classification only — no LLM/model calls needed.

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

try:
    from llm import get_llm_response
    _HAS_LLM = True
except ImportError:
    _HAS_LLM = False


# ── Filter presets (FFmpeg vf strings) ───────────────────────────────────────
# These are the canonical presets used by BOTH the agent AND the executor.
# Each value is a ready-to-use FFmpeg -vf filter string.

FILTER_PRESETS: dict[str, str] = {
    "sepia":       "colorchannelmixer=rr=0.393:rg=0.769:rb=0.189:gr=0.349:gg=0.686:gb=0.168:br=0.272:bg=0.534:bb=0.131",
    "noir":        "hue=s=0,curves=all='0/0 0.5/0.3 1/0.8'",
    "vintage":     "colorchannelmixer=rr=0.7:rg=0.2:rb=0.1:gr=0.1:gg=0.8:gb=0.1:br=0.1:bg=0.1:bb=0.6",
    "black_white": "hue=s=0",
    "grainy":      "noise=alls=20:allf=t",
    "cinematic":   "curves=all='0/0 0.3/0.2 0.7/0.8 1/1'",
    "darker":      "curves=all='0/0 0.5/0.3 1/0.75'",
    "brighter":    "curves=all='0/0 0.5/0.65 1/1'",
    "warm":        "colorchannelmixer=rr=1.1:rb=0:gr=0:gg=1.0:gb=0:br=0:bg=0:bb=0.85",
    "cold":        "colorchannelmixer=rr=0.85:rb=0:gr=0:gg=1.0:gb=0:br=0:bg=0:bb=1.1",
}

# ── Keyword rules ─────────────────────────────────────────────────────────────
# ORDER MATTERS: more-specific patterns first.
# "noir" must be caught by apply_filter BEFORE the generic "dark" rule fires.

_INTENT_RULES = [
    # (pattern, intent, target)
    # ── Specific filter names first ───────────────────────────────────────────
    (r"\b(sepia|noir|vintage|black[\s_]and[\s_]white|b&w|grayscale|grainy|cinematic|warm|cold)\b",
     "apply_filter", "video_frame"),

    # ── Audio ─────────────────────────────────────────────────────────────────
    (r"voice|tone|speech|speak|narrator|whisper|louder|softer|tts",
     "change_voice_tone", "audio"),
    (r"background\s*music|soundtrack|music|bgm|ambient|score",
     "add_background_music", "audio"),

    # ── Subtitle (toggle) ─────────────────────────────────────────────────────
    (r"subtitle|caption|closed[\s_]caption",
     "remove_subtitle", "video"),

    # ── Speed ─────────────────────────────────────────────────────────────────
    (r"speed\s*up|faster|slow\s*down|slower|pace|tempo",
     "speed_up_scene", "video"),

    # ── Brightness/darkness (generic — after named filters) ───────────────────
    (r"dark(?:er|en)|dim|shadow|moody|gloomy|sinister",
     "make_scene_darker", "video_frame"),
    (r"bright(?:er|en)|lighter|vivid|saturated|vibrant|sunny",
     "make_scene_brighter", "video_frame"),

    # ── Character / design ────────────────────────────────────────────────────
    (r"character.*design|redesign.*character|look.*different|appearance|outfit|costume",
     "change_character_design", "video_frame"),

    # ── Script ────────────────────────────────────────────────────────────────
    (r"regenerate.*script|rewrite.*script|new.*script|redo.*script|different.*story",
     "regenerate_script", "script"),
    (r"change.*dialogue|rewrite.*dialogue|different.*line|edit.*dialog",
     "change_dialogue", "script"),

    # ── Generic recompose (catch-all video) ───────────────────────────────────
    (r"recompose|re-render|render.*again|redo.*video|export.*again",
     "recompose_video", "video"),
]

_SCOPE_RULES = [
    (r"scene\s+(\d+)",                             "scene"),
    (r"character[:\s]+([A-Za-z\s]+?)(?:\s|$|,)",  "character"),
    (r"all\s+scenes?",                             "all_scenes"),
    (r"all\s+characters?",                         "all_characters"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_scope(query: str) -> dict:
    """Extract scope (scene/character) from query text."""
    q = query.lower()
    for pattern, scope_type in _SCOPE_RULES:
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            scope_value = m.group(1).strip() if m.lastindex and m.lastindex >= 1 else None
            return {"scope": f"{scope_type}:{scope_value}" if scope_value else scope_type}
    return {"scope": "all"}


def _extract_named_filters(query: str) -> list[str]:
    """Return a list of preset filter names found in the query."""
    q = query.lower()
    found = []
    for name in FILTER_PRESETS:
        readable = name.replace("_", " ")
        if readable in q or name in q:
            found.append(name)
    # Extra aliases
    if ("black and white" in q or "b&w" in q or "grayscale" in q) and "black_white" not in found:
        found.append("black_white")
    return found


# ── Rule-based classifier ─────────────────────────────────────────────────────

def _rule_based_classify(query: str) -> dict | None:
    q = query.lower().strip()

    for pattern, intent, target in _INTENT_RULES:
        if not re.search(pattern, q, re.IGNORECASE):
            continue

        scope_info = _detect_scope(query)
        params: dict = {}

        # ── Per-intent parameter extraction ──────────────────────────────────

        if intent == "change_voice_tone":
            m = re.search(
                r"(whisper(?:ed)?|soft|hard|deep|high|low|neutral|dramatic|calm|angry|sad|happy)",
                q, re.IGNORECASE,
            )
            params["tone"] = m.group(1).lower() if m else "neutral"

        elif intent == "speed_up_scene":
            if re.search(r"slow|slower", q):
                params["speed_factor"] = 0.75
                params["direction"]    = "slower"
            else:
                params["speed_factor"] = 1.5
                params["direction"]    = "faster"

        elif intent == "apply_filter":
            filters = _extract_named_filters(query)
            if not filters:
                # Grab the matched keyword itself as a filter name
                m = re.search(pattern, q, re.IGNORECASE)
                if m:
                    candidate = m.group(1).lower().replace(" ", "_")
                    if candidate in FILTER_PRESETS:
                        filters = [candidate]
            params["filters"] = filters

        elif intent == "make_scene_darker":
            filters = _extract_named_filters(query)
            if not filters:
                filters = ["darker"]
            params["filters"] = filters

        elif intent == "make_scene_brighter":
            filters = _extract_named_filters(query)
            if not filters:
                filters = ["brighter"]
            params["filters"] = filters

        elif intent == "remove_subtitle":
            # "add subtitle" → enable=True ; "remove subtitle" → enable=False
            params["enable_subtitles"] = bool(re.search(r"\b(add|include|show|enable)\b", q))

        return {
            "intent":     intent,
            "target":     target,
            "parameters": params,
            **scope_info,
        }

    return None


# ── Public API ────────────────────────────────────────────────────────────────

def classify_edit_intent(query: str) -> dict:
    """
    Classify a free-text edit query into a structured intent object.
    Rule-based first; optional LLM fallback if available.

    Returns:
    {
        "intent":     str,
        "target":     "audio" | "video_frame" | "video" | "script",
        "scope":      str,
        "parameters": dict,
        "raw_query":  str,
    }
    """
    result = _rule_based_classify(query)
    if result:
        result["raw_query"] = query
        print(f"[EditAgent] Rule-based: {result['intent']} → {result['target']}")
        return result

    # Optional LLM fallback (only if llm module is available)
    if _HAS_LLM:
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
- apply_filter → video_frame (filters: list of filter names from: sepia/noir/vintage/black_white/grainy/cinematic/warm/cold/darker/brighter)
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
            import json as _json, re as _re
            response = get_llm_response(prompt)
            match = _re.search(r'\{.*\}', response, _re.DOTALL)
            if match:
                data = _json.loads(match.group())
                data["raw_query"] = query
                print(f"[EditAgent] LLM classified: {data.get('intent')} → {data.get('target')}")
                return data
        except Exception as e:
            print(f"[EditAgent] LLM classification failed: {e}")

    # Ultimate fallback
    return {
        "intent":     "recompose_video",
        "target":     "video",
        "scope":      "all",
        "parameters": {"description": query},
        "raw_query":  query,
    }


def get_filter_presets() -> dict[str, str]:
    """Return all available filter presets (FFmpeg vf strings)."""
    return FILTER_PRESETS.copy()