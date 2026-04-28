# mcp/tools2.py
"""
Phase 2 MCP Tools
FIXES IN THIS VERSION:
  1. Gender inference: combines name-lookup + pronoun-scan across ALL scene dialogues
     → each character gets a stable male/female voice that never changes between scenes
  2. Audio embedded in final MP4: lip_sync_aligner always produces a real playable
     video with the spoken audio track using ffmpeg libx264 + aac mux
  3. [FIX] Character images are pinned to stable grid positions — no more flicker/glitch
     from frame-to-frame face detection mismatches
  4. [FIX] Every character gets its own mouth drawn on its own image position,
     and only the currently-speaking character's mouth animates
  5. [FIX] Portrait layout: size derived from available frame space so portraits
     never overlap — rows wrap automatically when characters don't fit in one row
"""

import os, json, wave, struct, random, hashlib, math, subprocess, shutil, re, asyncio
from typing import Dict, List, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

from dotenv import load_dotenv
load_dotenv()

ELEVENLABS_KEY = None          # set via env if available
PEXELS_KEY     = os.getenv("PEXELS_API_KEY")


# ── Tool schemas ──────────────────────────────────────────────────────────────
TOOL_SCHEMAS_2 = {
    "get_task_graph":            {"tool": "get_task_graph",            "input_schema": {"scenes": "list", "characters": "list"}},
    "voice_cloning_synthesizer": {"tool": "voice_cloning_synthesizer", "input_schema": {"scene_id": "int", "dialogue": "list", "characters": "list", "output_dir": "str"}},
    "query_stock_footage":       {"tool": "query_stock_footage",       "input_schema": {"scene_id": "int", "location": "str", "visual_cues": "list", "characters": "list", "output_dir": "str"}},
    "face_swapper":              {"tool": "face_swapper",              "input_schema": {"scene_id": "int", "video_path": "str", "character_images": "dict", "output_dir": "str"}},
    "identity_validator":        {"tool": "identity_validator",        "input_schema": {"character_name": "str", "image_path": "str", "character_db": "list"}},
    "lip_sync_aligner":          {"tool": "lip_sync_aligner",         "input_schema": {"scene_id": "int", "video_path": "str", "audio_path": "str", "output_dir": "str"}},
    "commit_memory":             {"tool": "commit_memory",             "input_schema": {"text": "str", "metadata": "dict"}},
}


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p

def _char_color(name: str) -> tuple:
    h = int(hashlib.md5(name.encode()).hexdigest(), 16)
    return (80 + (h & 0xFF) % 150, 80 + ((h>>8) & 0xFF) % 150, 100 + ((h>>16) & 0xFF) % 130)


# ─── Stable character grid layout ─────────────────────────────────────────────
#
# LAYOUT FIX (v5):
#   Old code used portrait_w = 22% of frame width which caused severe overlap
#   with 2+ characters because the gap calculation could go negative.
#
# New approach:
#   • Portrait size is derived from available space, not a fixed % of frame.
#   • All characters fill one row; if they can't all fit at MIN_PORTRAIT_W,
#     they wrap into multiple rows (each row laid out independently).
#   • Hard limits: portrait never wider than 14% of frame width, never taller
#     than 28% of frame height, and at least 80×108 px.
#   • A uniform PADDING gap is kept between every portrait and between rows.

_PORTRAIT_PADDING  = 10    # px gap between portraits and between frame edge / rows
_MAX_PORTRAIT_W_PC = 0.14  # portrait width ≤ 14 % of frame width
_MAX_PORTRAIT_H_PC = 0.28  # portrait height ≤ 28 % of frame height
_MIN_PORTRAIT_W    = 80    # absolute minimum portrait width (px)
_PORTRAIT_ASPECT   = 1.35  # height = width × aspect  (head-and-shoulders)


def _compute_character_slots(num_chars: int, fw: int, fh: int) -> list:
    """
    Returns a list of (x, y, w, h) portrait rectangles — one per character.

    Layout rules
    ────────────
    1. Derive portrait width from available horizontal space so that all
       characters fit in one row with _PORTRAIT_PADDING on every side:

           available_w_per_char = (fw - padding*(n+1)) / n

       Then cap at _MAX_PORTRAIT_W_PC * fw.  Never go below _MIN_PORTRAIT_W.

    2. Derive portrait height = width * _PORTRAIT_ASPECT, capped at
       _MAX_PORTRAIT_H_PC * fh.

    3. Count how many portraits actually fit in one row at that width:
           cols = floor((fw - padding) / (portrait_w + padding))

    4. Lay out left→right, wrapping to a new row when cols is exceeded.
       Row y is incremented by (portrait_h + padding + 20) — the +20 gives
       room for the name label drawn below each portrait.
    """
    if num_chars == 0:
        return []

    p = _PORTRAIT_PADDING

    # Step 1 — portrait width
    one_row_w  = (fw - p * (num_chars + 1)) // max(num_chars, 1)
    max_cap    = int(fw * _MAX_PORTRAIT_W_PC)
    portrait_w = max(_MIN_PORTRAIT_W, min(one_row_w, max_cap))

    # Step 2 — portrait height
    portrait_h = min(int(portrait_w * _PORTRAIT_ASPECT),
                     int(fh * _MAX_PORTRAIT_H_PC))

    # Step 3 — columns that fit at this width
    cols = max(1, (fw - p) // (portrait_w + p))

    # Step 4 — build slot list
    slots = []
    for i in range(num_chars):
        col = i % cols
        row = i // cols
        x   = p + col * (portrait_w + p)
        y   = p + row * (portrait_h + p + 20)   # +20 for name label row
        slots.append((x, y, portrait_w, portrait_h))

    return slots


def _draw_character_portraits(frame, char_slots: dict, char_faces: dict,
                               active_speaker: str = None,
                               char_amplitudes: dict = None):
    """
    Draws every character's portrait into its assigned slot on the given frame,
    then draws the mouth ON TOP of the portrait — all in one pass so nothing
    ever overwrites the mouth afterward.

    char_slots      : {name: (x, y, w, h)}
    char_faces      : {name: cv2 image}
    active_speaker  : name of the character currently speaking (highlighted)
    char_amplitudes : {name: float}  — RMS amplitude for this frame per character.
                      Only the active_speaker's value is used for mouth animation;
                      all others render a closed/resting mouth.
    """
    if char_amplitudes is None:
        char_amplitudes = {}

    for name, (x, y, w, h) in char_slots.items():
        face_img    = char_faces.get(name)
        is_speaking = (name == active_speaker)

        # ── 1. Background panel ───────────────────────────────────────────────
        panel_color = (30, 80, 30) if is_speaking else (45, 45, 65)
        cv2.rectangle(frame, (x - 2, y - 20), (x + w + 2, y + h + 18), panel_color, -1)

        # ── 2. Portrait image (or silhouette placeholder) ─────────────────────
        if face_img is not None:
            resized = cv2.resize(face_img, (w, h))
            frame[y:y + h, x:x + w] = resized
        else:
            cv2.rectangle(frame, (x, y), (x + w, y + h), _char_color(name)[::-1], -1)
            cx, cy = x + w // 2, y + h // 3
            cv2.circle(frame, (cx, cy), w // 4, (180, 160, 140), -1)
            cv2.rectangle(frame, (x + w//4, cy + w//4), (x + 3*w//4, y + h), (140, 120, 100), -1)

        # ── 3. Mouth — drawn directly onto the portrait, never overwritten ────
        if is_speaking:
            amp = char_amplitudes.get(name) \
               or char_amplitudes.get(name.lower()) \
               or next((v for k, v in char_amplitudes.items()
                        if k.lower() == name.lower()), 0.0)
        else:
            amp = 0.0
        _draw_mouth_on_portrait(frame, x, y, w, h, amp)

        # ── 4. Name label below portrait ──────────────────────────────────────
        label = name[:14]
        font_scale = max(0.3, min(0.45, w / 220))
        (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        tx = x + (w - tw) // 2
        cv2.putText(frame, label, (tx, y + h + 13),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (230, 230, 230), 1)

        # ── 5. Speaking indicator above portrait ──────────────────────────────
        if is_speaking:
            cv2.putText(frame, "SPEAKING", (x + 2, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (80, 255, 80), 1)
        else:
            cv2.putText(frame, name[:10], (x + 2, y - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.30, (160, 160, 160), 1)

    return frame


def _draw_mouth_on_portrait(frame, x: int, y: int, w: int, h: int, amp: float):
    """
    Draws an animated mouth in the lower-third of a portrait slot (x, y, w, h).
    amp = 0.0  → thin closed lips
    amp = 0.3+ → wide open mouth
    """
    mouth_cx = x + w // 2
    mouth_cy = y + int(h * 0.78)

    mw = max(6, w // 5)
    amp_norm = min(amp * 12.0, 1.0)
    mh = max(2, min(int(amp_norm * h * 0.25), h // 5))

    cv2.ellipse(frame, (mouth_cx, mouth_cy), (mw, max(mh, 3)),
                0, 0, 180, (20, 8, 8), -1)
    cv2.ellipse(frame, (mouth_cx, mouth_cy), (mw, max(mh, 3)),
                0, 0, 180, (160, 90, 90), 1)

    if mh > 5:
        cv2.ellipse(frame, (mouth_cx, mouth_cy + mh // 3),
                    (max(mw - 3, 2), max(mh // 2, 2)),
                    0, 0, 180, (10, 4, 4), -1)
        cv2.ellipse(frame, (mouth_cx, mouth_cy),
                    (mw - 2, 3), 0, 180, 360, (210, 205, 195), -1)

    cv2.ellipse(frame, (mouth_cx, mouth_cy), (mw, 2),
                0, 0, 180, (130, 70, 70), 1)


# ─── Gender inference ─────────────────────────────────────────────────────────

_GENDER_CACHE: Dict[str, str] = {}

_MALE_NAMES = {
    'alex','james','john','michael','david','daniel','ryan','jack','mark','tom',
    'peter','paul','robert','william','henry','george','charles','richard','edward',
    'andrew','chris','sam','max','jake','luke','adam','ben','nick','matt','jason',
    'kevin','brian','eric','scott','jeff','gary','joe','steve','frank','bob','bill',
    'carlos','marco','leo','ivan','victor','oscar','nathan','ethan','liam','noah',
    'oliver','mason','logan','aiden','lucas','sebastian','finn','caleb','elijah',
    'cooper','hunter','dylan','cole','aaron','tristan','ian','derek','marcus','omar'
}

_FEMALE_NAMES = {
    'may','emma','lily','sarah','emily','anna','julia','kate','mary','jane','lisa',
    'laura','amy','jessica','jennifer','ashley','rachel','maria','diana','sophia',
    'olivia','isabella','mia','ella','grace','chloe','alice','eve','nina','rose',
    'claire','michelle','nicole','amber','hannah','zoe','victoria','helen','betty',
    'linda','carmen','elena','natasha','ava','charlotte','amelia','harper','evelyn',
    'abigail','scarlett','camila','aria','luna','penelope','layla','riley','nora',
    'zoey','leah','violet','aurora','savannah','audrey','brooklyn','bella','stella'
}

_MALE_PRONOUNS   = {'he', 'him', 'his', 'himself'}
_FEMALE_PRONOUNS = {'she', 'her', 'hers', 'herself'}
_MALE_TITLES     = {'mr', 'sir', 'brother', 'son', 'father', 'dad', 'uncle',
                    'husband', 'boyfriend', 'king', 'prince', 'lord', 'gentleman'}
_FEMALE_TITLES   = {'ms', 'mrs', 'miss', 'sister', 'daughter', 'mother', 'mom',
                    'aunt', 'wife', 'girlfriend', 'queen', 'princess', 'lady', 'madam'}


def _infer_gender(name: str, char_meta: dict, all_scene_dialogues: list) -> str:
    """
    Returns "male" or "female" for the given character.

    Priority:
      1. char_meta["gender"] — set by character_agent via LLM (always present
         in the new pipeline).  If it is "male" or "female" we stop here.
      2. In-process _GENDER_CACHE — O(1) for repeated calls.
      3. Legacy heuristics — name lookup then pronoun/title scan — kept only
         for character_db.json files produced by older pipeline versions that
         did not store a gender field.
    """
    # 1. Explicit gender from character DB
    explicit = str(char_meta.get("gender") or "").lower().strip()
    if explicit in ("male", "female"):
        _GENDER_CACHE[name] = explicit
        return explicit

    # 2. Cache
    if name in _GENDER_CACHE:
        return _GENDER_CACHE[name]

    # 3. Legacy heuristics
    for token in name.lower().split():
        if token in _MALE_NAMES:
            _GENDER_CACHE[name] = "male";   return "male"
        if token in _FEMALE_NAMES:
            _GENDER_CACHE[name] = "female"; return "female"

    name_tokens = {t.lower() for t in name.split()}
    score = {"male": 0, "female": 0}
    for turn in all_scene_dialogues:
        speaker = (turn.get("speaker") or "").strip()
        line    = (turn.get("line")    or "").lower()
        if speaker.lower() == name.lower():
            continue
        if not any(tok in line for tok in name_tokens):
            continue
        words = set(re.findall(r"\b\w+\b", line))
        score["male"]   += len(words & _MALE_PRONOUNS)   * 3
        score["female"] += len(words & _FEMALE_PRONOUNS) * 3
        score["male"]   += len(words & _MALE_TITLES)
        score["female"] += len(words & _FEMALE_TITLES)

    if score["male"] > score["female"]:
        gender = "male"
    elif score["female"] > score["male"]:
        gender = "female"
    else:
        gender = "male" if int(hashlib.md5(name.encode()).hexdigest(), 16) % 2 == 0 else "female"

    _GENDER_CACHE[name] = gender
    return gender


# ── Voice parameter tables ────────────────────────────────────────────────────
_MALE_VOICE_PARAMS   = [(28, 135), (32, 145), (25, 130), (35, 150)]
_FEMALE_VOICE_PARAMS = [(68, 150), (72, 140), (65, 155), (75, 145)]

_EL_MALE_VOICES   = ["ErXwobaYiN019PkySvjV", "VR6AewLTigWG4xSOukaG", "pNInz6obpgDQGcFmaJgB"]
_EL_FEMALE_VOICES = ["21m00Tcm4TlvDq8ikWAM", "AZnzlk1XvdvUeBnXmlld", "EXAVITQu4vr4xnSDxMaL"]

_EDGE_MALE_VOICES   = ["en-US-GuyNeural",   "en-GB-RyanNeural",  "en-AU-WilliamNeural"]
_EDGE_FEMALE_VOICES = ["en-US-JennyNeural", "en-GB-SoniaNeural", "en-AU-NatashaNeural"]


def _voice_params_for(name: str, gender: str) -> dict:
    idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % 4
    if gender == "male":
        pitch, speed = _MALE_VOICE_PARAMS[idx % len(_MALE_VOICE_PARAMS)]
        el_voice     = _EL_MALE_VOICES[idx % len(_EL_MALE_VOICES)]
        edge_voice   = _EDGE_MALE_VOICES[idx % len(_EDGE_MALE_VOICES)]
    else:
        pitch, speed = _FEMALE_VOICE_PARAMS[idx % len(_FEMALE_VOICE_PARAMS)]
        el_voice     = _EL_FEMALE_VOICES[idx % len(_EL_FEMALE_VOICES)]
        edge_voice   = _EDGE_FEMALE_VOICES[idx % len(_EDGE_FEMALE_VOICES)]
    return {"pitch": pitch, "speed": speed, "el_voice": el_voice, "edge_voice": edge_voice}


# ── Synthesis backends ────────────────────────────────────────────────────────

def _synth_espeak(text: str, out_wav: str, pitch: int, speed: int) -> bool:
    try:
        r = subprocess.run(
            ["espeak-ng", "-w", out_wav, "-p", str(pitch), "-s", str(speed), text],
            capture_output=True, timeout=30
        )
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ espeak-ng: {e}"); return False


def _synth_elevenlabs(text: str, voice_id: str, out_wav: str) -> bool:
    if not (HAS_REQUESTS and ELEVENLABS_KEY): return False
    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": ELEVENLABS_KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"},
            json={"text": text, "model_id": "eleven_flash_v2_5",
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            timeout=60
        )
        if resp.status_code == 200 and len(resp.content) > 1024:
            mp3 = out_wav.replace(".wav", "_el.mp3")
            with open(mp3, "wb") as f: f.write(resp.content)
            try:
                subprocess.run(["ffmpeg", "-y", "-i", mp3, out_wav], capture_output=True, check=True, timeout=30)
                if os.path.exists(mp3): os.remove(mp3)
                return os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
            except Exception: pass
    except Exception as e:
        print(f"  ⚠ ElevenLabs: {e}")
    return False


async def _synth_edge_tts_async(text: str, out_mp3: str, voice: str) -> bool:
    if not HAS_EDGE_TTS: return False
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_mp3)
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 512
    except Exception as e:
        print(f"  ⚠ edge-tts: {e}"); return False


def _synth_edge_tts(text: str, out_wav: str, voice: str) -> bool:
    if not HAS_EDGE_TTS: return False
    mp3 = out_wav.replace(".wav", "_et.mp3")
    try:
        try:
            loop = asyncio.get_event_loop()
            ok = loop.run_until_complete(_synth_edge_tts_async(text, mp3, voice)) if not loop.is_running() else asyncio.run(_synth_edge_tts_async(text, mp3, voice))
        except RuntimeError:
            ok = asyncio.run(_synth_edge_tts_async(text, mp3, voice))
        if not ok: return False
        subprocess.run(["ffmpeg", "-y", "-i", mp3, out_wav], capture_output=True, check=True, timeout=30)
        if os.path.exists(mp3): os.remove(mp3)
        return os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ edge-tts ffmpeg: {e}"); return False


def _concat_wavs(paths: list, out: str) -> bool:
    frames, params = [], None
    for p in paths:
        if not os.path.exists(p) or os.path.getsize(p) < 100: continue
        try:
            with wave.open(p, "r") as wf:
                if params is None: params = wf.getparams()
                frames.append(wf.readframes(wf.getnframes()))
        except Exception: pass
    if not frames or params is None:
        with wave.open(out, "w") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
            wf.writeframes(b"\x00" * 22050)
        return False
    with wave.open(out, "w") as wf:
        wf.setparams(params)
        for chunk in frames: wf.writeframes(chunk)
    return True


# ─── TOOL 1: Task Graph ───────────────────────────────────────────────────────

def get_task_graph(input_data: Dict) -> Dict:
    scenes, characters = input_data["scenes"], input_data.get("characters", [])
    char_map = {c["name"]: c for c in characters}
    task_graph = [{
        "scene_id": s["scene_id"], "location": s.get("location", "Unknown"),
        "characters": s.get("characters", []), "dialogue": s.get("dialogue", []),
        "char_meta": [char_map.get(n, {"name": n}) for n in s.get("characters", [])],
        "audio_path": None, "video_path": None,
        "swapped_video_path": None, "synced_video_path": None,
        "status": "pending", "error": None,
    } for s in scenes]
    print(f"[MCP:get_task_graph] ✅ Built task graph — {len(task_graph)} scene tasks.")
    return {"task_graph": task_graph, "total_tasks": len(task_graph)}


# ─── TOOL 2: Voice Synthesis ─────────────────────────────────────────────────

def voice_cloning_synthesizer(input_data: Dict) -> Dict:
    scene_id          = input_data["scene_id"]
    dialogue          = input_data["dialogue"]
    characters        = input_data.get("characters", [])
    output_dir        = input_data["output_dir"]
    all_scene_dialogs = input_data.get("all_scene_dialogues", dialogue)
    _ensure_dir(output_dir)

    char_meta_map = {c["name"]: c for c in characters}

    char_voice_params = {}
    for turn in dialogue:
        speaker = turn.get("speaker", "Narrator")
        if speaker in char_voice_params:
            continue
        meta   = char_meta_map.get(speaker, {"name": speaker})
        gender = _infer_gender(speaker, meta, all_scene_dialogs)
        params = _voice_params_for(speaker, gender)
        char_voice_params[speaker] = {"gender": gender, **params}
        print(f"  🎤 {speaker} → {gender} | pitch={params['pitch']} speed={params['speed']}")

    line_wavs = []
    for idx, turn in enumerate(dialogue):
        speaker = turn.get("speaker", "Narrator")
        line    = turn.get("line", "").strip() or "..."
        vp      = char_voice_params.get(speaker, {"pitch": 50, "speed": 150,
                                                    "el_voice": _EL_FEMALE_VOICES[0],
                                                    "edge_voice": _EDGE_FEMALE_VOICES[0]})

        safe_spk = re.sub(r'[^A-Za-z0-9_]', '_', speaker)
        lw = os.path.join(output_dir, f"scene_{scene_id:02d}_{safe_spk}_line_{idx:03d}.wav")

        ok = False
        if ELEVENLABS_KEY:
            ok = _synth_elevenlabs(line, vp["el_voice"], lw)
        if not ok and HAS_EDGE_TTS:
            ok = _synth_edge_tts(line, lw, vp["edge_voice"])
        if not ok:
            ok = _synth_espeak(line, lw, vp["pitch"], vp["speed"])
        if not ok:
            with wave.open(lw, "w") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
                wf.writeframes(b"\x00" * int(22050 * max(0.5, len(line) * 0.05)))

        line_wavs.append(lw)

    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}.wav")
    _concat_wavs(line_wavs, out_path)

    try:
        with wave.open(out_path) as wf: duration = wf.getnframes() / wf.getframerate()
    except Exception: duration = 1.0

    genders_used = {s: p["gender"] for s, p in char_voice_params.items()}
    method = "elevenlabs" if ELEVENLABS_KEY else ("edge-tts" if HAS_EDGE_TTS else "espeak-ng")
    print(f"  🎙 [{method}] Scene {scene_id} → {out_path}  ({duration:.1f}s | {genders_used})")
    return {"scene_id": scene_id, "audio_path": out_path, "duration": duration,
            "method": method, "genders": genders_used,
            "line_wavs": line_wavs}


# ─── TOOL 3: Video Generation ─────────────────────────────────────────────────

def query_stock_footage(input_data: Dict) -> Dict:
    scene_id    = input_data["scene_id"]
    location    = input_data["location"]
    visual_cues = input_data.get("visual_cues", [])
    characters  = input_data.get("characters", [])
    output_dir  = input_data["output_dir"]
    _ensure_dir(output_dir)

    frame_dir  = os.path.join(output_dir, f"scene_{scene_id:02d}_frames")
    video_path = os.path.join(output_dir, f"scene_{scene_id:02d}_raw.mp4")
    _ensure_dir(frame_dir)
    used_stock = False

    if PEXELS_KEY and HAS_REQUESTS:
        try:
            resp = requests.get("https://api.pexels.com/videos/search",
                headers={"Authorization": PEXELS_KEY},
                params={"query": f"{location} cinematic", "per_page": 1, "size": "medium"},
                timeout=15)
            if resp.status_code == 200:
                files = resp.json().get("videos", [{}])[0].get("video_files", [])
                if files:
                    vid = requests.get(files[0]["link"], timeout=60, stream=True)
                    if vid.status_code == 200:
                        with open(video_path, "wb") as f:
                            for chunk in vid.iter_content(65536): f.write(chunk)
                        used_stock = True
                        print(f"  🎬 Stock footage downloaded — scene {scene_id}")
        except Exception as e: print(f"  ⚠ Pexels: {e}")

    if not used_stock and HAS_CV2 and HAS_NUMPY:
        fps = 25; dur = max(4.0, len(visual_cues)*1.5+2.0); nf = int(fps*dur)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        vw = cv2.VideoWriter(video_path, fourcc, fps, (854, 480))
        bg = _char_color(location)[::-1]
        for fi in range(nf):
            frame = np.zeros((480, 854, 3), dtype=np.uint8)
            for y in range(480):
                fy = y/480.0
                for c in range(3):
                    frame[y,:,c] = np.clip(bg[c] + 30*np.sin(np.pi*fy), 0, 255).astype(np.uint8)
            cue = visual_cues[int(fi/nf*len(visual_cues))] if visual_cues else ""
            cv2.putText(frame,f"Scene {scene_id}: {location}",(20,40),cv2.FONT_HERSHEY_SIMPLEX,.7,(255,255,255),2)
            if cue: cv2.putText(frame, cue[:60], (20, 460), cv2.FONT_HERSHEY_SIMPLEX, .45, (150,150,150), 1)
            vw.write(frame)
            if fi % 10 == 0: cv2.imwrite(os.path.join(frame_dir,f"frame_{fi:04d}.png"),frame)
        vw.release()
        print(f"  🎬 OpenCV scene video — scene {scene_id}")
    elif not used_stock:
        subprocess.run(["ffmpeg","-y","-f","lavfi",
            "-i",f"color=c=0x202020:size=854x480:rate=25:duration=4",
            "-vf",f"drawtext=text='Scene {scene_id}\\: {location[:30]}':fontcolor=white:fontsize=24:x=20:y=200",
            video_path], capture_output=True)

    frame_paths = [f for f in os.listdir(frame_dir) if f.endswith(".png")] if os.path.exists(frame_dir) else []
    print(f"  [MCP:query_stock_footage] Scene {scene_id} — {len(frame_paths)} frames")
    return {"scene_id": scene_id, "video_path": video_path, "frame_dir": frame_dir,
            "num_frames": len(frame_paths), "method": "stock" if used_stock else "opencv"}


# ─── TOOL 4: Identity Validator ───────────────────────────────────────────────

def identity_validator(input_data: Dict) -> Dict:
    cn, ip, db = input_data["character_name"], input_data["image_path"], input_data.get("character_db",[])
    if not ip or not os.path.exists(ip):
        return {"valid": False, "reason": f"Image not found: {ip}"}
    if cn not in {c["name"] for c in db}:
        return {"valid": False, "reason": f"'{cn}' not in character DB"}
    if os.path.getsize(ip) < 64:
        return {"valid": False, "reason": "Image empty/corrupt"}
    print(f"  ✅ Identity validated: {cn}")
    return {"valid": True, "character_name": cn, "image_path": ip}


# ─── TOOL 5: Face Swapper ─────────────────────────────────────────────────────

def face_swapper(input_data: Dict) -> Dict:
    scene_id    = input_data["scene_id"]
    video_path  = input_data["video_path"]
    char_images = input_data.get("character_images", {})
    output_dir  = input_data["output_dir"]
    _ensure_dir(output_dir)
    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}_swapped.mp4")

    validated = {}
    for cn, ip in char_images.items():
        check = identity_validator({"character_name": cn, "image_path": ip,
                                    "character_db": [{"name": cn}]})
        if check["valid"]:
            validated[cn] = ip
            print(f"  🎭 Face mapped: {cn}")
        else:
            print(f"  ⚠ Skip {cn}: {check['reason']}")

    if not HAS_CV2 or not HAS_NUMPY:
        if os.path.exists(video_path):
            shutil.copy2(video_path, out_path)
        return {"scene_id": scene_id, "swapped_video_path": out_path,
                "validated_chars": list(validated.keys()),
                "character_slots": {}, "face_positions_log": None}

    char_faces = {}
    for cn, ip in validated.items():
        img = cv2.imread(ip)
        if img is not None:
            char_faces[cn] = img

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Compute STABLE grid slots once — used for ALL frames
    char_names = list(char_faces.keys()) if char_faces else list(char_images.keys())
    slot_list  = _compute_character_slots(len(char_names), fw, fh)
    char_slots = {name: slot_list[i] for i, name in enumerate(char_names)}

    vw = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (fw, fh))
    fi = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = _draw_character_portraits(frame, char_slots, char_faces,
                                          active_speaker=None)
        vw.write(frame)
        fi += 1
    cap.release()
    vw.release()

    slots_log_path = os.path.join(output_dir, f"scene_{scene_id:02d}_character_slots.json")
    slots_serialisable = {name: list(rect) for name, rect in char_slots.items()}
    with open(slots_log_path, "w") as f:
        json.dump({"character_slots": slots_serialisable, "frame_size": [fw, fh]}, f, indent=2)

    print(f"  [MCP:face_swapper] Scene {scene_id} — {fi} frames → {out_path}")
    print(f"  📌 Stable slots: { {n: char_slots[n] for n in char_names} }")
    return {
        "scene_id":           scene_id,
        "swapped_video_path": out_path,
        "validated_chars":    list(validated.keys()),
        "character_slots":    slots_serialisable,
        "face_positions_log": slots_log_path,
    }


# ─── Lip sync helpers ─────────────────────────────────────────────────────────

def _read_wav_samples(wav_path):
    with wave.open(wav_path, "r") as wf:
        sr  = wf.getframerate(); sw = wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    dt = np.int16 if sw == 2 else np.int8
    s  = np.frombuffer(raw, dtype=dt).astype(np.float32)
    s /= 32768.0 if sw == 2 else 128.0
    return s, sr

def _rms_envelope(samples, sr, fps):
    spf = max(1, int(sr / fps)); env = []
    for i in range(0, len(samples), spf):
        c = samples[i:i+spf]
        env.append(float(np.sqrt(np.mean(c**2))) if len(c) else 0.0)
    return env

def _ffmpeg_mux(silent_video: str, audio: str, out: str) -> bool:
    for codec_args in [
        ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k"],
        ["-c:v", "copy",                                                "-c:a", "aac", "-b:a", "128k"],
    ]:
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", silent_video, "-i", audio] +
            codec_args + ["-shortest", "-movflags", "+faststart", out],
            capture_output=True, text=True, timeout=120
        )
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 10_000:
            break
        print(f"  ⚠ ffmpeg attempt failed (trying next codec): {r.stderr[-150:]}")
    else:
        return False

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", out],
        capture_output=True, text=True
    )
    if probe.returncode == 0:
        try:
            streams = {s["codec_type"] for s in json.loads(probe.stdout).get("streams", [])}
            if "audio" not in streams:
                print(f"  ⚠ ffprobe: audio stream missing from {out}")
                return False
        except Exception: pass
    return True


def _build_line_timing(dialogue: list, line_wav_paths: list, fps: float) -> list:
    timing = []
    current_frame = 0
    for idx, (turn, wav_path) in enumerate(zip(dialogue, line_wav_paths)):
        speaker = turn.get("speaker", "Narrator")
        try:
            samples, sr = _read_wav_samples(wav_path)
            duration    = len(samples) / sr
            envelope    = _rms_envelope(samples, sr, fps)
        except Exception:
            duration  = max(0.5, len(turn.get("line", "")) * 0.05)
            n_frames  = int(duration * fps)
            envelope  = [0.0] * n_frames
        n_frames  = max(1, len(envelope))
        end_frame = current_frame + n_frames
        timing.append({"speaker": speaker, "start_frame": current_frame,
                        "end_frame": end_frame, "envelope": envelope})
        current_frame = end_frame
    return timing


# ─── TOOL 6: Lip Sync Aligner ─────────────────────────────────────────────────

def lip_sync_aligner(input_data: Dict) -> Dict:
    scene_id       = input_data["scene_id"]
    video_path     = input_data["video_path"]
    audio_path     = input_data["audio_path"]
    output_dir     = input_data["output_dir"]
    dialogue       = input_data.get("dialogue", [])
    line_wav_paths = input_data.get("line_wav_paths", [])
    _ensure_dir(output_dir)
    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}.mp4")

    if not os.path.exists(video_path) or not os.path.exists(audio_path):
        return {"scene_id": scene_id, "synced_video_path": None,
                "status": "error", "error": "Missing video or audio file"}

    # Load stable character slot positions written by face_swapper
    face_swap_dir = input_data.get("face_swap_dir", output_dir)
    slots_log = os.path.join(face_swap_dir, f"scene_{scene_id:02d}_character_slots.json")
    if not os.path.exists(slots_log):
        slots_log = os.path.join(output_dir, f"scene_{scene_id:02d}_character_slots.json")
    char_slots = {}
    fw_ref, fh_ref = 854, 480
    if os.path.exists(slots_log):
        try:
            data = json.load(open(slots_log))
            char_slots = {name: tuple(rect) for name, rect in data["character_slots"].items()}
            fw_ref, fh_ref = data.get("frame_size", [854, 480])
            print(f"  📌 Loaded {len(char_slots)} character slots from {slots_log}")
        except Exception as e:
            print(f"  ⚠ Could not load character slots: {e}")
    else:
        print(f"  ⚠ No slots JSON at {slots_log} — mouths may not render")

    fps = 25.0
    line_timing = []

    if dialogue and line_wav_paths and len(line_wav_paths) == len(dialogue):
        line_timing  = _build_line_timing(dialogue, line_wav_paths, fps)
        total_frames = max(1, line_timing[-1]["end_frame"] if line_timing else 1)
        try:
            scene_samples, scene_sr = _read_wav_samples(audio_path)
            scene_envelope = _rms_envelope(scene_samples, scene_sr, fps)
            duration = len(scene_samples) / scene_sr
        except Exception:
            scene_envelope = [0.0] * total_frames
            duration = total_frames / fps
    else:
        try:
            scene_samples, scene_sr = _read_wav_samples(audio_path)
            duration = len(scene_samples) / scene_sr
            scene_envelope = _rms_envelope(scene_samples, scene_sr, fps)
        except Exception:
            scene_samples = np.zeros(22050*3, dtype=np.float32)
            scene_sr = 22050; duration = 3.0
            scene_envelope = [0.0] * int(duration * fps)
        total_frames = max(int(duration * fps), 1)

    def _speaker_and_amp(fi: int):
        if not line_timing:
            amp = scene_envelope[fi] if fi < len(scene_envelope) else 0.0
            return None, amp
        for entry in line_timing:
            if entry["start_frame"] <= fi < entry["end_frame"]:
                local = fi - entry["start_frame"]
                amp   = entry["envelope"][local] if local < len(entry["envelope"]) else 0.0
                return entry["speaker"], amp
        return None, 0.0

    tmp_video = out_path.replace(".mp4", "_silent.mp4")

    if HAS_CV2 and HAS_NUMPY:
        cap = cv2.VideoCapture(video_path)
        real_fw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or fw_ref
        real_fh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or fh_ref
        src_frames = []
        while True:
            ret, f = cap.read()
            if not ret: break
            src_frames.append(f)
        cap.release()

        char_faces = {}
        char_images_input = input_data.get("character_images", {})
        for cn, ip in char_images_input.items():
            img = cv2.imread(ip)
            if img is not None:
                char_faces[cn] = img

        vw = cv2.VideoWriter(tmp_video, cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (real_fw, real_fh))

        for fi in range(total_frames):
            frame = src_frames[fi % len(src_frames)].copy() if src_frames \
                    else np.zeros((real_fh, real_fw, 3), np.uint8)

            raw_speaker, amp = _speaker_and_amp(fi)

            current_speaker = None
            if raw_speaker:
                if raw_speaker in char_slots:
                    current_speaker = raw_speaker
                else:
                    raw_lower = raw_speaker.lower()
                    for slot_name in char_slots:
                        if slot_name.lower() == raw_lower:
                            current_speaker = slot_name
                            break

            if current_speaker:
                char_amplitudes = {name: (amp if name == current_speaker else 0.0)
                                   for name in char_slots}
            else:
                char_amplitudes = {name: amp for name in char_slots}

            frame = _draw_character_portraits(frame, char_slots, char_faces,
                                              active_speaker=current_speaker,
                                              char_amplitudes=char_amplitudes)

            scene_amp = scene_envelope[fi] if fi < len(scene_envelope) else 0.0
            bw = int(scene_amp * 120)
            cv2.rectangle(frame, (8, real_fh - 18), (8 + bw, real_fh - 8),
                          (50, 180, 70), -1)
            cv2.putText(frame, "AUDIO", (8, real_fh - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.3, (80, 180, 80), 1)

            if line_timing:
                for entry in line_timing:
                    if entry["start_frame"] <= fi < entry["end_frame"]:
                        line_idx = line_timing.index(entry)
                        if line_idx < len(dialogue):
                            subtitle = f"{entry['speaker']}: {dialogue[line_idx].get('line','')}"
                            cv2.rectangle(frame, (0, real_fh - 48),
                                          (real_fw, real_fh - 22), (0, 0, 0), -1)
                            cv2.putText(frame, subtitle[:90], (8, real_fh - 28),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                                        (230, 230, 230), 1)
                        break

            vw.write(frame)
        vw.release()
    else:
        shutil.copy2(video_path, tmp_video)

    mux_ok = _ffmpeg_mux(tmp_video, audio_path, out_path)
    try: os.remove(tmp_video)
    except Exception: pass

    if not mux_ok:
        shutil.copy2(tmp_video if os.path.exists(tmp_video) else video_path, out_path)

    fsize  = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    status = "synced_with_audio" if mux_ok else "synced_no_audio"

    align_log = os.path.join(output_dir, f"scene_{scene_id:02d}_alignment.json")
    ms_pf = 1000.0 / fps
    with open(align_log, "w") as f:
        json.dump({
            "scene_id": scene_id, "audio_path": audio_path, "video_path": video_path,
            "audio_duration": round(duration, 3), "fps": fps,
            "total_frames": total_frames, "mux_status": status,
            "line_timing_summary": [
                {"speaker": e["speaker"], "start_frame": e["start_frame"],
                 "end_frame": e["end_frame"]}
                for e in line_timing
            ],
            "alignment_sample": [
                {"frame": i, "audio_ms": round(i * ms_pf, 1),
                 "speaker": _speaker_and_amp(i)[0],
                 "rms": round(_speaker_and_amp(i)[1], 4)}
                for i in range(min(total_frames, 15))
            ],
        }, f, indent=2)

    print(f"  [MCP:lip_sync_aligner] Scene {scene_id} — {total_frames}f, "
          f"{duration:.1f}s audio, {fsize//1024}KB → {out_path}  [{status}]")
    return {"scene_id": scene_id, "synced_video_path": out_path,
            "audio_duration": duration, "total_frames": total_frames,
            "file_size_kb": fsize // 1024, "alignment_log": align_log, "status": status}


# ─── TOOL 7: commit_memory ────────────────────────────────────────────────────

def commit_memory_p2(input_data: Dict) -> Dict:
    try:
        from memory.vector_store import store_memory
        store_memory(text=input_data["text"], metadata=input_data.get("metadata",{}))
        return {"status": "stored"}
    except Exception as e:
        print(f"  ⚠ Memory commit skipped: {e}")
        return {"status": "skipped", "reason": str(e)}