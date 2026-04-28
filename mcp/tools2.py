# mcp/tools2.py
"""
Phase 2 MCP Tools  —  Audio Generation Only
─────────────────────────────────────────────
Tools:
  1. get_task_graph             — decompose scenes into tasks
  2. voice_cloning_synthesizer  — TTS per dialogue line (ElevenLabs / edge-tts / espeak-ng)
  3. commit_memory              — write entries to vector store
"""

import os, json, wave, struct, hashlib, subprocess, shutil, re, asyncio
from typing import Dict, List

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

ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY")


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
            capture_output=True, timeout=30,
        )
        return r.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ espeak-ng: {e}"); return False


def _synth_elevenlabs(text: str, voice_id: str, out_wav: str) -> bool:
    if not (HAS_REQUESTS and ELEVENLABS_KEY):
        return False
    try:
        resp = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key":    ELEVENLABS_KEY,
                "Content-Type":  "application/json",
                "Accept":        "audio/mpeg",
            },
            json={
                "text":     text,
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
            timeout=60,
        )
        if resp.status_code == 200 and len(resp.content) > 1024:
            mp3 = out_wav.replace(".wav", "_el.mp3")
            with open(mp3, "wb") as f:
                f.write(resp.content)
            subprocess.run(["ffmpeg", "-y", "-i", mp3, out_wav],
                           capture_output=True, check=True, timeout=30)
            if os.path.exists(mp3):
                os.remove(mp3)
            return os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ ElevenLabs: {e}")
    return False


async def _synth_edge_tts_async(text: str, out_mp3: str, voice: str) -> bool:
    if not HAS_EDGE_TTS:
        return False
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_mp3)
        return os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 512
    except Exception as e:
        print(f"  ⚠ edge-tts: {e}"); return False


def _synth_edge_tts(text: str, out_wav: str, voice: str) -> bool:
    if not HAS_EDGE_TTS:
        return False
    mp3 = out_wav.replace(".wav", "_et.mp3")
    try:
        try:
            loop = asyncio.get_event_loop()
            ok = (loop.run_until_complete(_synth_edge_tts_async(text, mp3, voice))
                  if not loop.is_running()
                  else asyncio.run(_synth_edge_tts_async(text, mp3, voice)))
        except RuntimeError:
            ok = asyncio.run(_synth_edge_tts_async(text, mp3, voice))
        if not ok:
            return False
        subprocess.run(["ffmpeg", "-y", "-i", mp3, out_wav],
                       capture_output=True, check=True, timeout=30)
        if os.path.exists(mp3):
            os.remove(mp3)
        return os.path.exists(out_wav) and os.path.getsize(out_wav) > 512
    except Exception as e:
        print(f"  ⚠ edge-tts ffmpeg: {e}"); return False


def _wav_duration_ms(wav_path: str) -> float:
    """Return duration of a WAV file in milliseconds."""
    try:
        with wave.open(wav_path, "r") as wf:
            return wf.getnframes() / wf.getframerate() * 1000.0
    except Exception:
        return 0.0


def _concat_wavs(paths: list, out: str) -> bool:
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

    # Assign a stable voice to every speaker appearing in this scene
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

    line_wavs   = []
    line_timing = []   # [{speaker, audio_file, start_ms, end_ms}]
    cursor_ms   = 0.0

    for idx, turn in enumerate(dialogue):
        speaker = turn.get("speaker", "Narrator")
        line    = turn.get("line", "").strip() or "..."
        vp      = char_voice_params.get(
            speaker,
            {"pitch": 50, "speed": 150,
             "el_voice":   _EL_FEMALE_VOICES[0],
             "edge_voice": _EDGE_FEMALE_VOICES[0]},
        )

        safe_spk = re.sub(r"[^A-Za-z0-9_]", "_", speaker)
        lw = os.path.join(output_dir,
                          f"scene_{scene_id:02d}_{safe_spk}_line_{idx:03d}.wav")

        ok = False
        if ELEVENLABS_KEY:
            ok = _synth_elevenlabs(line, vp["el_voice"], lw)
        if not ok and HAS_EDGE_TTS:
            ok = _synth_edge_tts(line, lw, vp["edge_voice"])
        if not ok:
            ok = _synth_espeak(line, lw, vp["pitch"], vp["speed"])
        if not ok:
            # silent fallback proportional to line length
            with wave.open(lw, "w") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050)
                wf.writeframes(b"\x00" * int(22050 * max(0.5, len(line) * 0.05)))

        dur_ms   = _wav_duration_ms(lw)
        end_ms   = cursor_ms + dur_ms
        line_timing.append({
            "speaker":    speaker,
            "line":       line,
            "audio_file": lw,
            "start_ms":   round(cursor_ms, 1),
            "end_ms":     round(end_ms,    1),
        })
        cursor_ms = end_ms
        line_wavs.append(lw)

    # Concatenate all lines into one scene-level WAV
    out_path = os.path.join(output_dir, f"scene_{scene_id:02d}.wav")
    _concat_wavs(line_wavs, out_path)

    try:
        with wave.open(out_path) as wf:
            duration = wf.getnframes() / wf.getframerate()
    except Exception:
        duration = cursor_ms / 1000.0

    genders_used = {s: p["gender"] for s, p in char_voice_params.items()}
    method = ("elevenlabs" if ELEVENLABS_KEY
              else ("edge-tts" if HAS_EDGE_TTS else "espeak-ng"))
    print(f"  🎙 [{method}] Scene {scene_id} → {out_path} "
          f"({duration:.1f}s | {genders_used})")

    return {
        "scene_id":    scene_id,
        "audio_path":  out_path,
        "duration":    duration,
        "method":      method,
        "genders":     genders_used,
        "line_wavs":   line_wavs,
        "line_timing": line_timing,   # ← per-line timing entries
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