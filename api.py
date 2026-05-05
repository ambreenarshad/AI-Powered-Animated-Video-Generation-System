"""
Project Montage — FastAPI Backend
Wraps all existing pipeline agents and exposes REST + WebSocket endpoints.

KEY FIXES vs original:
  - execute_edit(intent, state) called with correct argument order
  - _persist_edit_to_files covers ALL targets (script, audio, video_frame, video)
  - _ensure_current_state rebuilds task_graph from manifest when state is empty
  - Edit snapshot taken correctly using utils/state_manager
"""

import sys
import os
import json
import re
import queue
import threading
import glob as _glob
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI(title="Project Montage API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Stage definitions ────────────────────────────────────────────────────────

_P1_STAGES = ["Scriptwriter", "Validator", "HITL Review", "Character Designer"]
_P2_STAGES = ["Scene Parser", "Voice Synthesis"]
_P3_STAGES = [
    "Manifest Loader",
    "Image Gen (wan2.5-t2i-preview)",
    "Video Gen (wan2.7-i2v-2026-04-25)",
    "A/V Sync",
    "Scene Merge",
    "Compositor",
]

# ─── Shared application state ─────────────────────────────────────────────────

class _AppState:
    def __init__(self):
        self.phase1: dict = {
            "status": "idle", "script": None, "characters": None,
            "error": None, "stages": {s: "idle" for s in _P1_STAGES},
        }
        self.phase2: dict = {
            "status": "idle", "task_graph": [], "audio_results": [],
            "error": None, "stages": {s: "idle" for s in _P2_STAGES},
        }
        self.phase3: dict = {
            "status": "idle", "error": None,
            "stages": {s: "idle" for s in _P3_STAGES},
        }
        self.phase4: dict = {"status": "idle", "last_intent": None, "error": None}
        self.current: dict = {}
        self.hitl_event: threading.Event = threading.Event()
        self.hitl_decision: dict = {}
        self.log_q: queue.Queue = queue.Queue()
        self.ws_clients: list = []

gs = _AppState()

# ─── Stdout → WebSocket log queue ─────────────────────────────────────────────

_orig_stdout = sys.__stdout__

class _LogStream:
    def write(self, text: str):
        if _orig_stdout:
            _orig_stdout.write(text)
        if text.strip():
            gs.log_q.put(text.rstrip())

    def flush(self):
        if _orig_stdout:
            _orig_stdout.flush()

sys.stdout = _LogStream()

# ─── WebSocket broadcaster ────────────────────────────────────────────────────

async def _broadcast_loop():
    while True:
        dead = []
        try:
            msg = gs.log_q.get_nowait()
            for ws in list(gs.ws_clients):
                try:
                    await ws.send_json({"type": "log", "message": msg})
                except Exception:
                    dead.append(ws)
        except queue.Empty:
            pass
        for ws in dead:
            if ws in gs.ws_clients:
                gs.ws_clients.remove(ws)
        await asyncio.sleep(0.05)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(_broadcast_loop())


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    await websocket.accept()
    gs.ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in gs.ws_clients:
            gs.ws_clients.remove(websocket)


# ─── Request/response models ──────────────────────────────────────────────────

class Phase1Req(BaseModel):
    prompt: str

class HITLReq(BaseModel):
    action: str           # "approve" | "reject"
    feedback: Optional[str] = ""

class Phase3Req(BaseModel):
    dashscope_api_key: str

class EditReq(BaseModel):
    edit_text: str


# ─── Input mode helpers ───────────────────────────────────────────────────────

def _detect_mode(text: str) -> str:
    s = text.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            json.loads(s)
            return "manual"
        except Exception:
            pass
    if re.match(r"Scene\s*\d+\s*:", s, re.IGNORECASE):
        return "manual"
    return "auto"


def _parse_screenplay(raw: str) -> dict:
    scenes, cur, last_d = [], None, None
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"Scene\s*(\d+):\s*(.*)", line, re.IGNORECASE)
        if m:
            if cur:
                scenes.append(cur)
            cur = {
                "scene_id": int(m.group(1)), "location": m.group(2).strip(),
                "characters": [], "dialogue": [],
            }
            last_d = None
            continue
        if ":" in line and not line.startswith("[") and cur:
            spk, txt = line.split(":", 1)
            d = {"speaker": spk.strip(), "line": txt.strip(), "visual_cue": ""}
            cur["dialogue"].append(d)
            last_d = d
            if spk.strip() not in cur["characters"]:
                cur["characters"].append(spk.strip())
            continue
        if line.startswith("[") and line.endswith("]") and cur and last_d:
            last_d["visual_cue"] = line[1:-1].strip()
    if cur:
        scenes.append(cur)
    return {"scenes": scenes}


# ─── Phase 1 pipeline ─────────────────────────────────────────────────────────

def _run_p1(mode: str, user_input: str, script: dict):
    import agents.scriptwriter as sw
    import agents.validator as vl
    import agents.hitl as hl
    import agents.character as ch

    orig_sw = sw.scriptwriter_agent
    orig_vl = vl.validator_agent
    orig_hl = hl.hitl_agent
    orig_ch = ch.character_agent

    try:
        from mcp.init import register_tools
        from graph import build_graph
        from utils.json_utils import save_outputs

        def _stage_wrap(orig, stage_label):
            def _inner(s):
                gs.phase1["stages"][stage_label] = "running"
                print(f"[Phase 1] ▶ {stage_label}")
                try:
                    r = orig(s)
                    gs.phase1["stages"][stage_label] = "done"
                    print(f"[Phase 1] ✅ {stage_label}")
                    return r
                except Exception as e:
                    gs.phase1["stages"][stage_label] = "error"
                    raise
            return _inner

        def _web_hitl(s):
            gs.phase1["stages"]["HITL Review"] = "running"
            gs.phase1["status"] = "hitl_pending"
            gs.phase1["script"] = s.get("script")
            gs.hitl_event.clear()
            print("[HITL] Awaiting human review…")
            gs.hitl_event.wait()
            dec = gs.hitl_decision
            if dec.get("approved"):
                s["status"] = "approved"
                s["hitl_feedback"] = ""
                gs.phase1["stages"]["HITL Review"] = "done"
                print("[HITL] ✅ Script approved — continuing.")
            else:
                s["status"] = "rejected"
                s["hitl_feedback"] = dec.get("feedback", "")
                gs.phase1["stages"]["HITL Review"] = "idle"
                gs.phase1["stages"]["Scriptwriter"] = "idle"
                gs.phase1["stages"]["Validator"] = "idle"
                print("[HITL] ↩ Script rejected — regenerating…")
            gs.phase1["status"] = "running"
            return s

        sw.scriptwriter_agent = _stage_wrap(orig_sw, "Scriptwriter")
        vl.validator_agent    = _stage_wrap(orig_vl, "Validator")
        hl.hitl_agent         = _web_hitl
        ch.character_agent    = _stage_wrap(orig_ch, "Character Designer")

        register_tools()
        result = build_graph().invoke({
            "input_mode": mode, "user_input": user_input, "script": script,
            "characters": [], "status": "processing", "hitl_feedback": "",
        })
        save_outputs(result)

        gs.phase1.update({
            "status": "completed",
            "script": result.get("script"),
            "characters": result.get("characters"),
            "error": None,
        })
        gs.current = result

        try:
            from state_manager import get_state_manager
            get_state_manager().snapshot(
                result,
                asset_paths=["outputs/scene_manifest.json", "outputs/character_db.json"],
                label="Phase 1 complete",
            )
        except Exception as e:
            print(f"  ⚠ Snapshot failed: {e}")

        print("✅ Phase 1 completed successfully!")

    except Exception as e:
        import traceback
        gs.phase1.update({"status": "error", "error": str(e)})
        print(f"❌ Phase 1 error: {e}\n{traceback.format_exc()}")
    finally:
        sw.scriptwriter_agent = orig_sw
        vl.validator_agent    = orig_vl
        hl.hitl_agent         = orig_hl
        ch.character_agent    = orig_ch


@app.post("/api/phase1/run")
async def run_phase1(req: Phase1Req):
    if gs.phase1["status"] in ("running", "hitl_pending"):
        raise HTTPException(400, "Phase 1 is already running")
    mode = _detect_mode(req.prompt)
    if mode == "manual":
        try:
            script = json.loads(req.prompt)
        except Exception:
            script = _parse_screenplay(req.prompt)
        user_input = "Manual script provided"
    else:
        script, user_input = {}, req.prompt
    gs.phase1 = {
        "status": "running", "script": None, "characters": None, "error": None,
        "stages": {s: "idle" for s in _P1_STAGES},
    }
    threading.Thread(target=_run_p1, args=(mode, user_input, script), daemon=True).start()
    return {"status": "started", "input_mode": mode}


@app.get("/api/phase1/status")
async def phase1_status():
    return gs.phase1


@app.post("/api/phase1/hitl")
async def submit_hitl(req: HITLReq):
    if gs.phase1["status"] != "hitl_pending":
        raise HTTPException(400, "No HITL review pending")
    gs.hitl_decision = {"approved": req.action == "approve", "feedback": req.feedback or ""}
    gs.hitl_event.set()
    return {"status": "submitted"}


# ─── Phase 2 pipeline ─────────────────────────────────────────────────────────

def _run_p2():
    import agents2.scene_parser as sp
    import agents2.voice_synth as vs

    orig_sp = sp.scene_parser_agent
    orig_vs = vs.voice_synth_agent

    try:
        from mcp.init2 import register_tools_p2
        from graph2 import build_graph2
        from utils.json_utils2 import save_outputs_p2

        def _wrapped_sp(s):
            gs.phase2["stages"]["Scene Parser"] = "running"
            print("[Phase 2] ▶ Scene Parser")
            try:
                r = orig_sp(s)
                if r.get("task_graph"):
                    gs.phase2["task_graph"] = r["task_graph"]
                gs.phase2["stages"]["Scene Parser"] = "done"
                print("[Phase 2] ✅ Scene Parser")
                return r
            except Exception as e:
                gs.phase2["stages"]["Scene Parser"] = "error"
                raise

        def _wrapped_vs(s):
            gs.phase2["stages"]["Voice Synthesis"] = "running"
            print("[Phase 2] ▶ Voice Synthesis")
            try:
                r = orig_vs(s)
                if r.get("audio_results"):
                    gs.phase2["audio_results"] = r["audio_results"]
                gs.phase2["stages"]["Voice Synthesis"] = "done"
                print("[Phase 2] ✅ Voice Synthesis")
                return r
            except Exception as e:
                gs.phase2["stages"]["Voice Synthesis"] = "error"
                raise

        sp.scene_parser_agent = _wrapped_sp
        vs.voice_synth_agent  = _wrapped_vs

        register_tools_p2()
        result = build_graph2().invoke({
            "scene_manifest_path": "outputs/scene_manifest.json",
            "character_db_path":   "outputs/character_db.json",
            "scenes": [], "characters": [], "task_graph": [],
            "audio_results": [], "audio_tracks": [], "timing_manifest": [],
            "task_log": [], "status": "processing", "error": None,
        })
        save_outputs_p2(result)

        gs.phase2.update({
            "status": "completed",
            "task_graph": result.get("task_graph", []),
            "audio_results": result.get("audio_results", []),
            "error": None,
        })
        gs.current.update(result)

        try:
            from state_manager import get_state_manager
            assets = (
                _glob.glob("outputs/audio/*.wav") +
                ["outputs/timing_manifest.json", "outputs/phase2_manifest.json"]
            )
            get_state_manager().snapshot(result, asset_paths=assets, label="Phase 2 complete")
        except Exception as e:
            print(f"  ⚠ Snapshot failed: {e}")

        print("✅ Phase 2 completed successfully!")

    except Exception as e:
        import traceback
        gs.phase2.update({"status": "error", "error": str(e)})
        print(f"❌ Phase 2 error: {e}\n{traceback.format_exc()}")
    finally:
        sp.scene_parser_agent = orig_sp
        vs.voice_synth_agent  = orig_vs


@app.post("/api/phase2/run")
async def run_phase2():
    if gs.phase2["status"] == "running":
        raise HTTPException(400, "Phase 2 already running")
    gs.phase2 = {
        "status": "running", "task_graph": [], "audio_results": [], "error": None,
        "stages": {s: "idle" for s in _P2_STAGES},
    }
    threading.Thread(target=_run_p2, daemon=True).start()
    return {"status": "started"}


@app.get("/api/phase2/status")
async def phase2_status():
    return gs.phase2


# ─── Phase 3 pipeline ─────────────────────────────────────────────────────────

def _run_p3(api_key: str):
    import agents3.manifest_loader as ml
    import agents3.image_gen as ig
    import agents3.ken_burns as kb
    import agents3.av_sync_agent as av
    import agents3.scene_merge_agent as sm
    import agents3.compositor_agent as ca

    originals = {
        "ml": ml.manifest_loader_agent,
        "ig": ig.image_gen_agent,
        "kb": kb.ken_burns_agent,
        "av": av.av_sync_agent,
        "sm": sm.scene_merge_agent,
        "ca": ca.compositor_agent,
    }

    try:
        from mcp.init3 import register_tools_p3
        from graph3 import build_graph3

        os.environ["DASHSCOPE_API_KEY"] = api_key

        stage_map = [
            ("ml", ml, "manifest_loader_agent", "Manifest Loader"),
            ("ig", ig, "image_gen_agent",        "Image Gen (wan2.5-t2i-preview)"),
            ("kb", kb, "ken_burns_agent",         "Video Gen (wan2.7-i2v-2026-04-25)"),
            ("av", av, "av_sync_agent",           "A/V Sync"),
            ("sm", sm, "scene_merge_agent",       "Scene Merge"),
            ("ca", ca, "compositor_agent",        "Compositor"),
        ]

        def _make_wrap(key, mod, attr, stage_name):
            orig = originals[key]
            def _inner(s):
                gs.phase3["stages"][stage_name] = "running"
                print(f"[Phase 3] ▶ {stage_name}")
                try:
                    r = orig(s)
                    gs.phase3["stages"][stage_name] = "done"
                    print(f"[Phase 3] ✅ {stage_name}")
                    return r
                except Exception as e:
                    gs.phase3["stages"][stage_name] = "error"
                    print(f"[Phase 3] ❌ {stage_name}: {e}")
                    raise
            setattr(mod, attr, _inner)

        for args in stage_map:
            _make_wrap(*args)

        register_tools_p3()
        result = build_graph3().invoke({
            "scene_manifest_path":  "outputs/scene_manifest.json",
            "timing_manifest_path": "outputs/timing_manifest.json",
            "character_db_path":    "outputs/character_db.json",
            "audio_dir":            "outputs/audio",
            "dashscope_api_key":    api_key,
            "enable_subtitles":     True,
            "scenes": [], "characters": [], "timing_manifest": [],
            "task_graph": [], "final_output": "", "subtitle_file": None,
            "status": "processing", "error": None, "task_log": [],
        })

        gs.phase3.update({"status": "completed", "error": None})
        gs.current.update(result)

        try:
            from state_manager import get_state_manager
            assets = (
                _glob.glob("outputs/video/final_output.mp4") +
                _glob.glob("outputs/video/synced/*.mp4") +
                _glob.glob("outputs/video/scenes/*.mp4") +
                _glob.glob("outputs/logs/phase3_task_log.json")
            )
            get_state_manager().snapshot(result, asset_paths=assets, label="Phase 3 complete")
        except Exception as e:
            print(f"  ⚠ Snapshot failed: {e}")

        print("✅ Phase 3 completed successfully!")

    except Exception as e:
        import traceback
        gs.phase3.update({"status": "error", "error": str(e)})
        print(f"❌ Phase 3 error: {e}\n{traceback.format_exc()}")
    finally:
        ml.manifest_loader_agent = originals["ml"]
        ig.image_gen_agent       = originals["ig"]
        kb.ken_burns_agent       = originals["kb"]
        av.av_sync_agent         = originals["av"]
        sm.scene_merge_agent     = originals["sm"]
        ca.compositor_agent      = originals["ca"]


@app.post("/api/phase3/run")
async def run_phase3(req: Phase3Req):
    if gs.phase3["status"] == "running":
        raise HTTPException(400, "Phase 3 already running")
    api_key = req.dashscope_api_key.strip() or os.getenv("DASHSCOPE_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "DASHSCOPE_API_KEY not found — provide it in the field or add it to .env")
    gs.phase3 = {
        "status": "running",
        "stages": {s: "idle" for s in _P3_STAGES},
        "error": None,
    }
    threading.Thread(target=_run_p3, args=(api_key,), daemon=True).start()
    return {"status": "started"}


@app.get("/api/phase3/status")
async def phase3_status():
    return gs.phase3


# ─── Phase 4: Edit & Undo ─────────────────────────────────────────────────────

def _rebuild_task_graph_from_manifest(script: dict) -> list:
    """
    Build a minimal task_graph from a script dict so executors that iterate
    task_graph have something to work with even if Phase 2 hasn't run yet.
    """
    task_graph = []
    for scene in script.get("scenes", []):
        sid = scene.get("scene_id", len(task_graph) + 1)
        task_graph.append({
            "scene_id":        sid,
            "location":        scene.get("location", ""),
            "dialogue":        scene.get("dialogue", []),
            "characters":      scene.get("characters", []),
            "character_clips": [
                {
                    "character_name": char,
                    "image_path":     None,
                    "status":         "pending",
                }
                for char in scene.get("characters", [])
            ],
        })
    return task_graph


def _ensure_current_state() -> bool:
    """
    Load or reconstruct pipeline state into gs.current.
    Priority:
      1. gs.current already populated (from a completed pipeline run this session)
      2. Latest edit snapshot (utils/state_manager)
      3. Latest pipeline snapshot (root state_manager)
      4. Reconstruct from output JSON files on disk
    Returns True if gs.current is usable (has at least a 'script' key).
    """
    # 1. Already have state
    if gs.current and gs.current.get("script"):
        return True

    # 2. Edit snapshot store
    try:
        from utils.state_manager import get_state_manager as get_edit_sm
        mgr = get_edit_sm()
        latest = mgr.latest_id()
        if latest is not None:
            v = mgr.get_version(latest)
            if v and v.get("state") and v["state"].get("script"):
                candidate = v["state"]
                # Rebuild task_graph if missing
                if not candidate.get("task_graph"):
                    candidate["task_graph"] = _rebuild_task_graph_from_manifest(
                        candidate["script"]
                    )
                gs.current = candidate
                print(f"[Phase 4] Loaded state from edit snapshot v{latest}")
                return True
    except Exception as e:
        print(f"[Phase 4] Edit snapshot load failed: {e}")

    # 3. Pipeline snapshot store
    try:
        from state_manager import get_state_manager
        mgr = get_state_manager()
        latest_id = mgr.current_version()
        if latest_id is not None:
            record = mgr.get_version(latest_id)
            if record:
                candidate = json.loads(record.state_json)
                if not candidate.get("task_graph") and candidate.get("script"):
                    candidate["task_graph"] = _rebuild_task_graph_from_manifest(
                        candidate["script"]
                    )
                gs.current = candidate
                print(f"[Phase 4] Loaded state from pipeline snapshot v{latest_id}")
                return True
    except Exception as e:
        print(f"[Phase 4] Pipeline snapshot load failed: {e}")

    # 4. Reconstruct from disk files
    try:
        minimal: dict = {}
        for path, key in [
            ("outputs/scene_manifest.json", "script"),
            ("outputs/character_db.json",   "characters"),
            ("outputs/timing_manifest.json", "timing_manifest"),
        ]:
            if os.path.exists(path):
                with open(path) as f:
                    minimal[key] = json.load(f)

        if minimal.get("script"):
            # Rebuild task_graph so executors can operate
            minimal["task_graph"] = _rebuild_task_graph_from_manifest(minimal["script"])
            # Try to load phase2 audio results into task_graph dialogue
            for wav in _glob.glob("outputs/audio/*.wav"):
                print(f"[Phase 4]   Found audio asset: {wav}")
            gs.current = minimal
            print("[Phase 4] Reconstructed state from manifest files")
            print(f"[Phase 4]   task_graph has {len(minimal['task_graph'])} scene(s)")
            return True
    except Exception as e:
        print(f"[Phase 4] Manifest reconstruction failed: {e}")

    return False


def _persist_edit_to_files(state: dict, intent: dict):
    """
    Write updated state back to the output files that downstream phases read.
    This is the critical step that makes edits visible on disk.
    Called for ALL target types.
    """
    os.makedirs("outputs", exist_ok=True)
    target = intent.get("target", "")

    # ── Always write scene_manifest if script changed ─────────────────────────
    script = state.get("script")
    if script:
        try:
            with open("outputs/scene_manifest.json", "w", encoding="utf-8") as f:
                json.dump(script, f, indent=2, ensure_ascii=False)
            print("[Edit] ✅ Wrote outputs/scene_manifest.json")
        except Exception as e:
            print(f"[Edit] ⚠ Failed to write scene_manifest.json: {e}")

    # ── Always write character_db if characters changed ───────────────────────
    chars = state.get("characters")
    if chars:
        try:
            with open("outputs/character_db.json", "w", encoding="utf-8") as f:
                json.dump(chars, f, indent=2, ensure_ascii=False)
            print("[Edit] ✅ Wrote outputs/character_db.json")
        except Exception as e:
            print(f"[Edit] ⚠ Failed to write character_db.json: {e}")

    # ── Target-specific persistence ───────────────────────────────────────────
    if target == "audio":
        timing = state.get("timing_manifest")
        if timing:
            try:
                with open("outputs/timing_manifest.json", "w", encoding="utf-8") as f:
                    json.dump(timing, f, indent=2, ensure_ascii=False)
                print("[Edit] ✅ Wrote outputs/timing_manifest.json")
            except Exception as e:
                print(f"[Edit] ⚠ Failed to write timing_manifest.json: {e}")

        audio_results = state.get("audio_results", [])
        if audio_results:
            try:
                with open("outputs/audio_edit_results.json", "w", encoding="utf-8") as f:
                    json.dump(audio_results, f, indent=2, ensure_ascii=False)
                print("[Edit] ✅ Wrote outputs/audio_edit_results.json")
            except Exception as e:
                print(f"[Edit] ⚠ Failed to write audio_edit_results.json: {e}")

    elif target == "video_frame":
        # Persist aesthetic modifiers embedded in task_graph back into manifest
        task_graph = state.get("task_graph", [])
        if task_graph:
            try:
                with open("outputs/task_graph_edit.json", "w", encoding="utf-8") as f:
                    json.dump(task_graph, f, indent=2, ensure_ascii=False)
                print("[Edit] ✅ Wrote outputs/task_graph_edit.json")
            except Exception as e:
                print(f"[Edit] ⚠ Failed to write task_graph_edit.json: {e}")

    elif target == "video":
        # Write updated subtitle preference and speed factors
        video_config = {
            "enable_subtitles": state.get("enable_subtitles", True),
            "task_speed_factors": {
                str(t.get("scene_id")): t.get("_speed_factor", 1.0)
                for t in state.get("task_graph", [])
                if "_speed_factor" in t
            },
        }
        try:
            with open("outputs/video_edit_config.json", "w", encoding="utf-8") as f:
                json.dump(video_config, f, indent=2, ensure_ascii=False)
            print("[Edit] ✅ Wrote outputs/video_edit_config.json")
        except Exception as e:
            print(f"[Edit] ⚠ Failed to write video_edit_config.json: {e}")

    # ── Always update manifest files ──────────────────────────────────────────
    for key, path in [
        ("phase2_manifest", "outputs/phase2_manifest.json"),
        ("phase3_manifest", "outputs/phase3_manifest.json"),
    ]:
        if key in state:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(state[key], f, indent=2, ensure_ascii=False)
                print(f"[Edit] ✅ Wrote {path}")
            except Exception as e:
                print(f"[Edit] ⚠ Failed to write {path}: {e}")

    # ── Write a full edit_state.json for debugging / downstream use ───────────
    try:
        # Exclude non-serialisable keys
        safe_state = {k: v for k, v in state.items() if not k.startswith("_")}
        with open("outputs/edit_state.json", "w", encoding="utf-8") as f:
            json.dump(safe_state, f, indent=2, ensure_ascii=False, default=str)
        print("[Edit] ✅ Wrote outputs/edit_state.json")
    except Exception as e:
        print(f"[Edit] ⚠ Failed to write edit_state.json: {e}")


@app.post("/api/phase4/edit")
async def submit_edit(req: EditReq):
    if gs.phase4["status"] == "running":
        raise HTTPException(400, "Edit already in progress")

    def _edit():
        try:
            gs.phase4.update({"status": "running", "error": None})

            if not _ensure_current_state():
                raise RuntimeError(
                    "No pipeline state available. Run Phase 1 first, "
                    "or ensure outputs/scene_manifest.json exists."
                )

            from agents.edit_agent    import classify_edit_intent
            from agents.edit_executor import execute_edit

            # 1. Classify the edit request
            intent = classify_edit_intent(req.edit_text)
            intent_name = intent.get("intent", "unknown") if isinstance(intent, dict) else str(intent)
            gs.phase4["last_intent"] = intent_name
            print(f"[Edit] Classified: intent={intent_name}  target={intent.get('target')}  scope={intent.get('scope')}")

            # 2. Snapshot the BEFORE state
            try:
                from utils.state_manager import get_state_manager as get_edit_sm
                edit_mgr = get_edit_sm()
                before_assets = _collect_edit_assets()
                edit_mgr.snapshot(
                    gs.current,
                    label=f"Before: {req.edit_text[:60]}",
                    asset_paths=before_assets,
                    edit_query=req.edit_text,
                    intent=intent_name,
                    target=intent.get("target", ""),
                )
            except Exception as e:
                print(f"[Edit] ⚠ Pre-edit snapshot failed: {e}")

            # 3. Execute — correct signature is execute_edit(state, intent) → (state, files, label)
            print(f"[Edit] Executing '{intent_name}'…")
            updated_state, modified_files, exec_label = execute_edit(gs.current, intent)

            # 4. Check for executor-level errors
            if exec_label.startswith("❌"):
                gs.phase4.update({"status": "error", "error": exec_label})
                print(f"[Edit] {exec_label}")
                return

            # 5. Persist ALL changes to disk
            _persist_edit_to_files(updated_state, intent)

            # 6. Snapshot the AFTER state
            try:
                from utils.state_manager import get_state_manager as get_edit_sm
                edit_mgr = get_edit_sm()
                after_assets = _collect_edit_assets()
                edit_mgr.snapshot(
                    updated_state,
                    label=f"Edit: {exec_label}",
                    asset_paths=after_assets,
                    edit_query=req.edit_text,
                    intent=intent_name,
                    target=intent.get("target", ""),
                )
            except Exception as e:
                print(f"[Edit] ⚠ Post-edit snapshot failed: {e}")

            # 7. Update live state
            gs.current = updated_state
            gs.phase4["status"] = "completed"
            print(f"[Edit] ✅ {exec_label}")

        except Exception as e:
            import traceback
            gs.phase4.update({"status": "error", "error": str(e)})
            print(f"[Edit] ❌ {e}\n{traceback.format_exc()}")

    threading.Thread(target=_edit, daemon=True).start()
    return {"status": "started"}


def _collect_edit_assets() -> list[str]:
    """Gather all current output asset paths for snapshotting."""
    assets: list[str] = []
    patterns = [
        "outputs/audio/*.wav",
        "outputs/images/characters/*.png",
        "outputs/clips/*.mp4",
        "outputs/video/synced/*.mp4",
        "outputs/video/scenes/*.mp4",
        "outputs/video/final_output.mp4",
        "outputs/scene_manifest.json",
        "outputs/character_db.json",
        "outputs/timing_manifest.json",
        "outputs/task_graph_edit.json",
        "outputs/video_edit_config.json",
        "outputs/audio_edit_results.json",
        "outputs/edit_state.json",
    ]
    for pat in patterns:
        assets.extend(_glob.glob(pat))
    return assets


def _unified_history() -> list[dict]:
    """Return combined version history from both state managers, newest first."""
    versions: list[dict] = []

    try:
        from utils.state_manager import get_state_manager as get_edit_sm
        for v in get_edit_sm().history():
            versions.append({
                "version_id":   v["id"],
                "label":        v["label"],
                "timestamp":    v.get("time_str", str(v.get("timestamp", ""))),
                "diff_summary": f"{v.get('intent', '')} — {v.get('edit_query', '')}".strip(" —"),
                "asset_paths":  [],
                "source":       "edit",
            })
    except Exception as e:
        print(f"[History] Edit SM error: {e}")

    try:
        from state_manager import get_state_manager
        for r in get_state_manager().history():
            d = r.to_dict()
            d["source"] = "pipeline"
            versions.append(d)
    except Exception as e:
        print(f"[History] Pipeline SM error: {e}")

    versions.sort(key=lambda v: v.get("timestamp", ""), reverse=True)
    return versions


@app.get("/api/phase4/history")
async def get_history():
    try:
        return {"versions": _unified_history()}
    except Exception as e:
        return {"versions": [], "error": str(e)}


@app.post("/api/phase4/revert/{version_id}")
async def revert_version(version_id: int):
    # Try edit snapshot store first
    try:
        from utils.state_manager import get_state_manager as get_edit_sm
        edit_mgr = get_edit_sm()
        version = edit_mgr.get_version(version_id)
        state, _ = edit_mgr.revert(version_id)
        if not state.get("task_graph") and state.get("script"):
            state["task_graph"] = _rebuild_task_graph_from_manifest(state["script"])
        gs.current = state
        gs.phase1.update({
            "status": "completed",
            "script": state.get("script"),
            "characters": state.get("characters"),
        })
        target = version.get("target", "script") if version else "script"
        _persist_edit_to_files(state, {"target": target})
        return {"status": "reverted", "version_id": version_id, "source": "edit"}
    except Exception:
        pass

    # Fall back to pipeline snapshot store
    try:
        from state_manager import get_state_manager
        restored = get_state_manager().revert(version_id)
        if not restored.get("task_graph") and restored.get("script"):
            restored["task_graph"] = _rebuild_task_graph_from_manifest(restored["script"])
        gs.current = restored
        gs.phase1.update({
            "status": "completed",
            "script": restored.get("script"),
            "characters": restored.get("characters"),
        })
        _persist_edit_to_files(restored, {"target": "script"})
        return {"status": "reverted", "version_id": version_id, "source": "pipeline"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/phase4/status")
async def phase4_status():
    return gs.phase4


# ─── Output file endpoints ────────────────────────────────────────────────────

@app.get("/api/outputs/video")
async def get_video():
    path = Path("outputs/video/final_output.mp4")
    if not path.exists():
        raise HTTPException(404, "Final video not found. Run Phase 3 first.")
    return FileResponse(str(path), media_type="video/mp4", filename="final_output.mp4")


@app.get("/api/outputs/list")
async def list_outputs():
    files = []
    for pattern in [
        "outputs/video/final_output.mp4",
        "outputs/audio/*.wav",
        "outputs/*.json",
        "outputs/video/scenes/*.mp4",
    ]:
        for f in _glob.glob(pattern):
            try:
                files.append({
                    "path": f,
                    "name": Path(f).name,
                    "size": os.path.getsize(f),
                    "type": Path(f).suffix.lstrip("."),
                })
            except OSError:
                pass
    return {"files": files}


@app.get("/api/config")
async def get_config():
    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
    return {
        "dashscope_api_key_set": bool(dashscope_key),
        "dashscope_api_key_hint": (dashscope_key[:8] + "…" + dashscope_key[-4:]) if len(dashscope_key) > 12 else ("*" * len(dashscope_key)),
        "groq_api_key_set": bool(os.getenv("GROQ_API_KEY", "")),
    }


@app.get("/api/status")
async def overall_status():
    return {
        "phase1": gs.phase1["status"],
        "phase2": gs.phase2["status"],
        "phase3": gs.phase3["status"],
        "phase4": gs.phase4["status"],
    }