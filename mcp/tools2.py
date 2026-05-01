# mcp/tools2.py
"""
Phase 2 MCP Tools  —  Audio Generation Only
─────────────────────────────────────────────
Tools:
  1. get_task_graph             — decompose scenes into tasks
  2. voice_cloning_synthesizer  — TTS per dialogue line (edge-tts primary, espeak-ng fallback)
  3. commit_memory              — write entries to vector store

Backend priority: edge-tts → espeak-ng (fallback)
ElevenLabs removed; edge-tts is always attempted first.
"""

import os, json, wave, struct, hashlib, subprocess, shutil, re, asyncio
from typing import Dict, List

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

from dotenv import load_dotenv
load_dotenv()


# ── Tool schemas ──────────────────────────────────────────────────────────────
TOOL_SCHEMAS_2 = {
    "get_task_graph": {
        "tool": "get_task_graph",
        "input_schema": {"scenes": "list", "characters": "list"},
    },
    "voice_cloning_synthesizer": {
        "tool": "voice_cloning_synthesizer",
        "input_schema": {
            "scene_id":   "int",
            "dialogue":   "list",
            "characters": "list",
            "output_dir": "str",
        },
    },
    "commit_memory": {
        "tool": "commit_memory",
        "input_schema": {"text": "str", "metadata": "dict"},
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p


# ── Gender inference ──────────────────────────────────────────────────────────

_GENDER_CACHE: Dict[str, str] = {}

_MALE_NAMES = {
    'alex','james','john','michael','david','daniel','ryan','jack','mark','tom',
    'peter','paul','robert','william','henry','george','charles','richard','edward',
    'andrew','chris','sam','max','jake','luke','adam','ben','nick','matt','jason',
    'kevin','brian','eric','scott','jeff','gary','joe','steve','frank','bob','bill',
    'carlos','marco','leo','ivan','victor','oscar','nathan','ethan','liam','noah',
    'oliver','mason','logan','aiden','lucas','sebastian','finn','caleb','elijah',
    'cooper','hunter','dylan','cole','aaron','tristan','ian','derek','marcus','omar',
}
_FEMALE_NAMES = {
    'may','emma','lily','sarah','emily','anna','julia','kate','mary','jane','lisa',
    'laura','amy','jessica','jennifer','ashley','rachel','maria','diana','sophia',
    'olivia','isabella','mia','ella','grace','chloe','alice','eve','nina','rose',
    'claire','michelle','nicole','amber','hannah','zoe','victoria','helen','betty',
    'linda','carmen','elena','natasha','ava','charlotte','amelia','harper','evelyn',
    'abigail','scarlett','camila','aria','luna','penelope','layla','riley','nora',
    'zoey','leah','violet','aurora','savannah','audrey','brooklyn','bella','stella',
}
_MALE_PRONOUNS   = {'he', 'him', 'his', 'himself'}
_FEMALE_PRONOUNS = {'she', 'her', 'hers', 'herself'}
_MALE_TITLES     = {'mr','sir','brother','son','father','dad','uncle',
                    'husband','boyfriend','king','prince','lord','gentleman'}
_FEMALE_TITLES   = {'ms','mrs','miss','sister','daughter','mother','mom',
                    'aunt','wife','girlfriend','queen','princess','lady','madam'}


def _infer_gender(name: str, char_meta: dict, all_scene_dialogues: list) -> str:
    explicit = str(char_meta.get("gender") or "").lower().strip()
    if explicit in ("male", "female"):
        _GENDER_CACHE[name] = explicit
        return explicit
    if name in _GENDER_CACHE:
        return _GENDER_CACHE[name]
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


# ── Edge-TTS voice pools ──────────────────────────────────────────────────────
# Expanded pools ensure different characters get meaningfully distinct voices.
# Each voice has a different accent, pitch, and speaking style.
_EDGE_MALE_VOICES = [
    "en-US-GuyNeural",        # American, neutral/authoritative
    "en-GB-RyanNeural",       # British, warm
    "en-AU-WilliamNeural",    # Australian, relaxed
    "en-US-ChristopherNeural",# American, deep/confident
    "en-US-EricNeural",       # American, friendly
    "en-GB-ThomasNeural",     # British, formal
    "en-IE-ConnorNeural",     # Irish, distinctive lilt
    "en-US-RogerNeural",      # American, older/mature
    "en-NZ-MitchellNeural",   # New Zealand, casual
    "en-CA-LiamNeural",       # Canadian, measured
]

_EDGE_FEMALE_VOICES = [
    "en-US-JennyNeural",      # American, warm/conversational
    "en-GB-SoniaNeural",      # British, crisp
    "en-AU-NatashaNeural",    # Australian, bright
    "en-US-AriaNeural",       # American, expressive
    "en-US-MichelleNeural",   # American, professional
    "en-GB-LibbyNeural",      # British, friendly
    "en-IE-EmilyNeural",      # Irish, gentle lilt
    "en-US-MonicaNeural",     # American, warm/mature
    "en-NZ-MollyNeural",      # New Zealand, upbeat
    "en-CA-ClaraNeural",      # Canadian, clear/neutral
]

# espeak-ng fallback parameters: (pitch, speed) per gender slot
_MALE_VOICE_PARAMS   = [(28, 135), (32, 145), (25, 130), (35, 150),
                        (30, 140), (22, 128), (38, 155), (26, 132),
                        (33, 148), (20, 125)]
_FEMALE_VOICE_PARAMS = [(68, 150), (72, 140), (65, 155), (75, 145),
                        (70, 152), (78, 138), (62, 158), (80, 143),
                        (66, 150), (74, 147)]


def _voice_params_for(name: str, gender: str) -> dict:
    """
    Derive a stable, character-unique voice config from the character name hash.
    The hash index selects from the full voice pool so every character gets
    a distinct voice that never changes between runs.
    """
    pool_size = len(_EDGE_MALE_VOICES)   # both pools are the same length
    idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % pool_size

    if gender == "male":
        edge_voice       = _EDGE_MALE_VOICES[idx]
        pitch, speed     = _MALE_VOICE_PARAMS[idx % len(_MALE_VOICE_PARAMS)]
    else:
        edge_voice       = _EDGE_FEMALE_VOICES[idx]
        pitch, speed     = _FEMALE_VOICE_PARAMS[idx % len(_FEMALE_VOICE_PARAMS)]

    return {"pitch": pitch, "speed": speed, "edge_voice": edge_voice}


# ── Synthesis backends ────────────────────────────────────────────────────────

def _synth_espeak(text: str, out_wav: str, pitch: int, speed: int) -> bool:
    """Fallback: espeak-ng synthesis."""
    try:
        r = subprocess.run(
            ["espeak-ng", "-w", out_wav, "-p", str(pitch), "-s", str(speed), text],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ espeak-ng: {e}"); return False


async def _synth_edge_tts_async(text: str, out_mp3: str, voice: str) -> bool:
    """Async core for edge-tts synthesis."""
    if not HAS_EDGE_TTS:
        return False
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_mp3)
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 512
    except Exception as e:
        print(f"  ⚠ edge-tts: {e}"); return False


def _synth_edge_tts(text: str, out_wav: str, voice: str) -> bool:
    """
    Synchronous wrapper around the async edge-tts call.
    Converts the resulting MP3 to WAV via ffmpeg so the rest of the
    pipeline can treat all audio uniformly as WAV.
    """
    if not HAS_EDGE_TTS:
        return False

    mp3 = out_wav.replace(".wav", "_et.mp3")
    try:
        # Handle both running and non-running event loops gracefully
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                ok = asyncio.run(_synth_edge_tts_async(text, mp3, voice))
            else:
                ok = loop.run_until_complete(_synth_edge_tts_async(text, mp3, voice))
        except RuntimeError:
            ok = asyncio.run(_synth_edge_tts_async(text, mp3, voice))

        if not ok:
            return False

        # Convert MP3 → WAV
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3, out_wav],
            capture_output=True, check=True, timeout=30,
        )
        return os.path.exists(out_wav) and os.path.getsize(out_wav) > 512

    except Exception as e:
        print(f"  ⚠ edge-tts ffmpeg conversion: {e}")
        return False
    finally:
        if os.path.exists(mp3):
            try:
                os.remove(mp3)
            except OSError:
                pass


# ── WAV utilities ─────────────────────────────────────────────────────────────

def _wav_duration_ms(wav_path: str) -> float:
    """Return duration of a WAV file in milliseconds."""
    try:
        with wave.open(wav_path, "r") as wf:
            return wf.getnframes() / wf.getframerate() * 1000.0
    except Exception:
        return 0.0


def _concat_wavs(paths: list, out: str) -> bool:
    """Concatenate a list of WAV files into a single output WAV."""
    frames, params = [], None
    for p in paths:
        if not os.path.exists(p) or os.path.getsize(p) < 100:
            continue
        try:
            with wave.open(p, "r") as wf:
                if params is None:
                    params = wf.getparams()
                frames.append(wf.readframes(wf.getnframes()))
        except Exception:
            pass
    if not frames or params is None:
        # Write a minimal silent WAV so downstream code never gets a missing file
        with wave.open(out, "w") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
            wf.writeframes(b"\x00" * 22050)
        return False
    with wave.open(out, "w") as wf:
        wf.setparams(params)
        for chunk in frames:
            wf.writeframes(chunk)
    return True


# ─── TOOL 1: Task Graph ───────────────────────────────────────────────────────

def get_task_graph(input_data: Dict) -> Dict:
    scenes     = input_data["scenes"]
    characters = input_data.get("characters", [])
    char_map   = {c["name"]: c for c in characters}

    task_graph = [
        {
            "scene_id":   s["scene_id"],
            "location":   s.get("location", "Unknown"),
            "characters": s.get("characters", []),
            "dialogue":   s.get("dialogue", []),
            "char_meta":  [char_map.get(n, {"name": n}) for n in s.get("characters", [])],
            "audio_path": None,
            "line_wavs":  [],
            "status":     "pending",
            "error":      None,
        }
        for s in scenes
    ]
    print(f"[MCP:get_task_graph] ✅ Built task graph — {len(task_graph)} scene tasks.")
    return {"task_graph": task_graph, "total_tasks": len(task_graph)}


# ─── TOOL 2: Voice Synthesis ──────────────────────────────────────────────────

def voice_cloning_synthesizer(input_data: Dict) -> Dict:
    scene_id          = input_data["scene_id"]
    dialogue          = input_data["dialogue"]
    characters        = input_data.get("characters", [])
    output_dir        = input_data["output_dir"]
    all_scene_dialogs = input_data.get("all_scene_dialogues", dialogue)
    _ensure_dir(output_dir)

    char_meta_map = {c["name"]: c for c in characters}

    # ── Assign a stable, unique voice to every speaker in this scene ──────────
    char_voice_params = {}
    for turn in dialogue:
        speaker = turn.get("speaker", "Narrator")
        if speaker in char_voice_params:
            continue
        meta   = char_meta_map.get(speaker, {"name": speaker})
        gender = _infer_gender(speaker, meta, all_scene_dialogs)
        params = _voice_params_for(speaker, gender)
        char_voice_params[speaker] = {"gender": gender, **params}
        print(f"  🎤 {speaker} → {gender} | voice={params['edge_voice']}")

    line_wavs   = []
    line_timing = []   # [{speaker, line, audio_file, start_ms, end_ms}]
    cursor_ms   = 0.0

    for idx, turn in enumerate(dialogue):
        speaker = turn.get("speaker", "Narrator")
        line    = turn.get("line", "").strip() or "..."
        vp      = char_voice_params.get(
            speaker,
            {
                "pitch":      50,
                "speed":      150,
                "edge_voice": _EDGE_FEMALE_VOICES[0],
            },
        )

        safe_spk = re.sub(r"[^A-Za-z0-9_]", "_", speaker)
        lw = os.path.join(
            output_dir,
            f"scene_{scene_id:02d}_{safe_spk}_line_{idx:03d}.wav",
        )

        # ── Try edge-tts first, fall back to espeak-ng ────────────────────────
        ok = _synth_edge_tts(line, lw, vp["edge_voice"])
        if not ok:
            print(f"  ⚠ edge-tts failed for scene {scene_id} line {idx} "
                  f"({speaker}) — falling back to espeak-ng")
            ok = _synth_espeak(line, lw, vp["pitch"], vp["speed"])

        if not ok:
            # Last-resort: silent WAV proportional to line length
            print(f"  ⚠ All TTS backends failed for scene {scene_id} line {idx} "
                  f"({speaker}) — writing silent placeholder")
            with wave.open(lw, "w") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
                wf.writeframes(b"\x00" * int(22050 * max(0.5, len(line) * 0.05)))

        dur_ms  = _wav_duration_ms(lw)
        end_ms  = cursor_ms + dur_ms
        line_timing.append({
            "speaker":    speaker,
            "line":       line,
            "audio_file": lw,
            "start_ms":   round(cursor_ms, 1),
            "end_ms":     round(end_ms,    1),
        })
        cursor_ms = end_ms
        line_wavs.append(lw)

    # ── Concatenate all per-line WAVs into one scene-level WAV ────────────────
    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}.wav")
    _concat_wavs(line_wavs, out_path)

    try:
        with wave.open(out_path) as wf:
            duration = wf.getnframes() / wf.getframerate()
    except Exception:
        duration = cursor_ms / 1000.0

    genders_used = {s: p["gender"] for s, p in char_voice_params.items()}
    voices_used  = {s: p["edge_voice"] for s, p in char_voice_params.items()}
    method = "edge-tts" if HAS_EDGE_TTS else "espeak-ng"

    print(f"  🎙 [{method}] Scene {scene_id} → {out_path} "
          f"({duration:.1f}s | {genders_used})")
    print(f"       voices assigned: {voices_used}")

    return {
        "scene_id":    scene_id,
        "audio_path":  out_path,
        "duration":    duration,
        "method":      method,
        "genders":     genders_used,
        "voices":      voices_used,
        "line_wavs":   line_wavs,
        "line_timing": line_timing,
    }


# ─── TOOL 3: commit_memory ────────────────────────────────────────────────────

def commit_memory_p2(input_data: Dict) -> Dict:
    try:
        from memory.vector_store import store_memory
        store_memory(text=input_data["text"], metadata=input_data.get("metadata", {}))
        return {"status": "stored"}
    except Exception as e:
        print(f"  ⚠ Memory commit skipped: {e}")
        return {"status": "skipped", "reason": str(e)}