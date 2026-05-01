"""
PROJECT MONTAGE — Unified Launcher
Tabs: Phase 1 (Story Generation) · Phase 2 (Audio Synthesis)
Cinematic noir aesthetic throughout.
"""

import tkinter as tk
from tkinter import scrolledtext, font, filedialog, ttk
import threading
import json
import re
import sys
import queue
import os


# ── Stdout redirect ───────────────────────────────────────────────────────────
class QueueStream:
    def __init__(self, queues):
        self.queues = queues          # list of queues to broadcast to
        self._orig = sys.__stdout__
    def write(self, text):
        if text.strip():
            for q in self.queues:
                q.put(text)
    def flush(self):
        pass


# ── Colour palette ─────────────────────────────────────────────────────────────
BG     = "#0f0f0f"
BG2    = "#1a1a1a"
BG3    = "#242424"
BORDER = "#2e2e2e"
GOLD   = "#c9a84c"
GOLD2  = "#e8c96d"
CREAM  = "#f0e6cc"
MUTED  = "#7a7060"
GREEN  = "#4caf84"
RED    = "#c94c4c"
BLUE   = "#4c8caf"
WHITE  = "#f5f0e8"


# ── Phase 1 helpers ────────────────────────────────────────────────────────────
def parse_raw_script_to_json(raw_text: str) -> dict:
    scenes = []
    current_scene = None
    last_dialogue = None
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"Scene\s*(\d+):\s*(.*)", line, re.IGNORECASE)
        if m:
            if current_scene:
                scenes.append(current_scene)
            current_scene = {"scene_id": int(m.group(1)), "location": m.group(2).strip(),
                             "characters": [], "dialogue": []}
            last_dialogue = None
            continue
        if ":" in line and not line.startswith("[") and current_scene:
            speaker, text = line.split(":", 1)
            d = {"speaker": speaker.strip(), "line": text.strip(), "visual_cue": ""}
            current_scene["dialogue"].append(d)
            last_dialogue = d
            if speaker.strip() not in current_scene["characters"]:
                current_scene["characters"].append(speaker.strip())
            continue
        if line.startswith("[") and line.endswith("]") and current_scene and last_dialogue:
            last_dialogue["visual_cue"] = line[1:-1].strip()
    if current_scene:
        scenes.append(current_scene)
    return {"scenes": scenes}


def detect_input_mode(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "manual"
        except Exception:
            pass
    if re.match(r"Scene\s*\d+\s*:", stripped, re.IGNORECASE):
        return "manual"
    return "auto"


# ══════════════════════════════════════════════════════════════════════════════
#  Root window + tab shell
# ══════════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PROJECT MONTAGE")
        self.geometry("1160x860")
        self.minsize(980, 720)
        self.configure(bg=BG)

        # One log queue per phase so stdout is broadcast to both
        self._q1 = queue.Queue()
        self._q2 = queue.Queue()
        sys.stdout = QueueStream([self._q1, self._q2])

        self._build_fonts()
        self._build_chrome()

        # Instantiate phase panels inside their tabs
        self.p1 = Phase1Panel(self.tab1, self._q1, self.f)
        self.p2 = Phase2Panel(self.tab2, self._q2, self.f)
        self.p1.pack(fill="both", expand=True)
        self.p2.pack(fill="both", expand=True)

    def _build_fonts(self):
        self.f = fonts = {}
        fonts["title"] = font.Font(family="Georgia",     size=20, weight="bold")
        fonts["sub"]   = font.Font(family="Georgia",     size=10, slant="italic")
        fonts["label"] = font.Font(family="Courier New", size=9,  weight="bold")
        fonts["body"]  = font.Font(family="Courier New", size=10)
        fonts["log"]   = font.Font(family="Courier New", size=9)
        fonts["btn"]   = font.Font(family="Georgia",     size=10, weight="bold")
        fonts["small"] = font.Font(family="Courier New", size=8)

    def _build_chrome(self):
        # ── Global header ──────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG, pady=14)
        hdr.pack(fill="x", padx=30)
        tk.Label(hdr, text="◈  PROJECT MONTAGE",
                 font=self.f["title"], fg=GOLD, bg=BG).pack(side="left")
        tk.Label(hdr, text="  autonomous story generation  ·  audio synthesis",
                 font=self.f["sub"], fg=MUTED, bg=BG).pack(side="left", pady=4)
        tk.Frame(self, bg=GOLD, height=1).pack(fill="x", padx=30)

        # ── Custom tab bar ─────────────────────────────────────────────────────
        tab_bar = tk.Frame(self, bg=BG2, pady=0)
        tab_bar.pack(fill="x", padx=30, pady=(0, 0))

        self._tab_btns = []
        self._active_tab = tk.IntVar(value=0)

        tab_defs = [
            ("  PHASE 1  ·  Story Generation  ", 0),
            ("  PHASE 2  ·  Audio Synthesis   ", 1),
        ]

        for label, idx in tab_defs:
            btn = tk.Button(
                tab_bar, text=label,
                font=self.f["label"],
                relief="flat", bd=0,
                padx=18, pady=10,
                cursor="hand2",
                command=lambda i=idx: self._switch_tab(i),
            )
            btn.pack(side="left")
            self._tab_btns.append(btn)

        # Accent line under tab bar
        self._tab_accent = tk.Frame(self, bg=BG3, height=2)
        self._tab_accent.pack(fill="x", padx=30)

        # ── Tab content frames ─────────────────────────────────────────────────
        self.tab1 = tk.Frame(self, bg=BG)
        self.tab2 = tk.Frame(self, bg=BG)
        self.tab1.pack(fill="both", expand=True)
        # tab2 starts hidden

        self._switch_tab(0)  # paint initial active state

    def _switch_tab(self, idx: int):
        self._active_tab.set(idx)
        tabs = [self.tab1, self.tab2]

        for i, (btn, tab) in enumerate(zip(self._tab_btns, tabs)):
            if i == idx:
                btn.config(bg=BG, fg=GOLD,  activebackground=BG,  activeforeground=GOLD2)
                tab.pack(fill="both", expand=True)
            else:
                btn.config(bg=BG2, fg=MUTED, activebackground=BG2, activeforeground=GOLD)
                tab.pack_forget()


# ══════════════════════════════════════════════════════════════════════════════
#  Phase 1 Panel
# ══════════════════════════════════════════════════════════════════════════════

class Phase1Panel(tk.Frame):
    def __init__(self, parent, log_queue: queue.Queue, fonts: dict):
        super().__init__(parent, bg=BG)
        self.f = fonts
        self._log_queue  = log_queue
        self._hitl_event = threading.Event()
        self._hitl_decision = {"approved": False, "feedback": ""}

        self._build_ui()
        self._poll_log()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _lbl(self, parent, text, fg=None):
        return tk.Label(parent, text=text, font=self.f["label"],
                        fg=fg or GOLD, bg=parent["bg"])

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=30, pady=12)
        body.columnconfigure(0, weight=55)
        body.columnconfigure(1, weight=45)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        self.status_var = tk.StringVar(value="Ready")
        sb = tk.Frame(self, bg=BG2, pady=7)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=GOLD, width=3).pack(side="left", fill="y")
        tk.Label(sb, textvariable=self.status_var, font=self.f["label"],
                 fg=GOLD, bg=BG2, padx=12).pack(side="left")

    def _build_left(self, parent):
        left_container = tk.Frame(parent, bg=BG)
        left_container.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left_container.columnconfigure(0, weight=1)
        left_container.rowconfigure(0, weight=1)

        canvas = tk.Canvas(left_container, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(left_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=BG)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw",
                              width=canvas.winfo_width())
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _configure_canvas(event):
            canvas.itemconfig(1, width=event.width)
        canvas.bind("<Configure>", _configure_canvas)

        left = scrollable_frame
        left.columnconfigure(0, weight=1)

        # Input
        inf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                       highlightbackground=BORDER, highlightthickness=1)
        inf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        inf.columnconfigure(0, weight=1)
        self._lbl(inf, "PROMPT  /  SCRIPT").grid(row=0, column=0, sticky="w")
        tk.Label(
            inf,
            text="Enter a plain prompt or paste a raw screenplay "
                 "(Scene 1: ...  Speaker: ...  [Visual] ...). Mode is detected automatically.",
            font=self.f["label"], fg=MUTED, bg=BG2, justify="left", wraplength=440
        ).grid(row=1, column=0, sticky="w", pady=(4, 8))

        self.prompt_text = scrolledtext.ScrolledText(
            inf, height=8, bg=BG3, fg=WHITE, font=self.f["body"],
            relief="flat", insertbackground=GOLD, wrap="word", padx=10, pady=8)
        self.prompt_text.grid(row=2, column=0, sticky="ew")
        self.prompt_text.insert(
            "1.0",
            "Write a 3-scene thriller in New York City. "
            "Two main characters planning a heist. "
            "Include tense dialogues and cinematic visual cues.")

        self.detected_var = tk.StringVar(value="")
        self.detected_lbl = tk.Label(
            inf, textvariable=self.detected_var,
            font=self.f["label"], fg=MUTED, bg=BG2, anchor="e")
        self.detected_lbl.grid(row=3, column=0, sticky="e", pady=(4, 0))
        self.prompt_text.bind("<KeyRelease>", self._on_input_change)
        self._on_input_change()

        # Run button
        self.run_btn = tk.Button(
            left, text="▶  RUN PIPELINE", font=self.f["btn"],
            bg=GOLD, fg="#0f0f0f", activebackground=GOLD2, activeforeground="#0f0f0f",
            relief="flat", padx=28, pady=11, cursor="hand2",
            command=self._run_pipeline)
        self.run_btn.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # HITL panel
        self.hitl_frame = tk.Frame(left, bg=BG2,
                                   highlightbackground=GOLD, highlightthickness=1)
        self.hitl_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.hitl_frame.grid_remove()

        ht = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=10)
        ht.pack(fill="x")
        self._lbl(ht, "⬡  HUMAN REVIEW CHECKPOINT").pack(anchor="w")

        self.script_preview = scrolledtext.ScrolledText(
            self.hitl_frame, height=8, bg=BG3, fg=CREAM,
            font=self.f["log"], relief="flat", padx=10, pady=8, state="disabled")
        self.script_preview.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        fb = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=8)
        fb.pack(fill="x")
        self._lbl(fb, "FEEDBACK (optional)").pack(anchor="w")
        self.feedback_entry = tk.Entry(
            fb, bg=BG3, fg=WHITE, font=self.f["body"],
            relief="flat", insertbackground=GOLD)
        self.feedback_entry.pack(fill="x", pady=(5, 0), ipady=6)

        hb = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=10)
        hb.pack(fill="x")
        tk.Button(hb, text="✓  APPROVE", font=self.f["btn"], bg=GREEN, fg="#0f0f0f",
                  relief="flat", padx=20, pady=8, cursor="hand2",
                  command=self._approve).pack(side="left", padx=(0, 8))
        tk.Button(hb, text="✗  REJECT & REGENERATE", font=self.f["btn"], bg=RED,
                  fg=WHITE, relief="flat", padx=20, pady=8, cursor="hand2",
                  command=self._reject).pack(side="left")

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self._lbl(right, "PIPELINE PROGRESS").grid(row=0, column=0, sticky="w", pady=(0, 8))
        pf = tk.Frame(right, bg=BG2, padx=14, pady=12,
                      highlightbackground=BORDER, highlightthickness=1)
        pf.grid(row=0, column=0, sticky="ew", pady=(18, 10))

        self.stages = ["Scriptwriter", "Validator", "HITL Review", "Character Designer"]
        self.stage_labels = {}
        for s in self.stages:
            row = tk.Frame(pf, bg=BG2)
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="○", font=self.f["body"], fg=MUTED, bg=BG2, width=2)
            dot.pack(side="left")
            lbl = tk.Label(row, text=s, font=self.f["label"], fg=MUTED, bg=BG2)
            lbl.pack(side="left")
            self.stage_labels[s] = (dot, lbl)

        self._lbl(right, "LIVE LOG").grid(row=1, column=0, sticky="w", pady=(10, 6))
        self.log_box = scrolledtext.ScrolledText(
            right, bg=BG2, fg="#8aad8a", font=self.f["log"],
            relief="flat", padx=10, pady=8, state="disabled")
        self.log_box.grid(row=2, column=0, sticky="nsew")
        self.log_box.tag_config("gold",  foreground=GOLD)
        self.log_box.tag_config("green", foreground=GREEN)
        self.log_box.tag_config("red",   foreground=RED)
        self.log_box.tag_config("dim",   foreground=MUTED)

        self._lbl(right, "OUTPUT FILES").grid(row=3, column=0, sticky="w", pady=(12, 6))
        of = tk.Frame(right, bg=BG2, padx=14, pady=10,
                      highlightbackground=BORDER, highlightthickness=1)
        of.grid(row=4, column=0, sticky="ew")
        self.out_labels = {}
        for name in ["scene_manifest.json", "character_db.json"]:
            r = tk.Frame(of, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="▸", fg=MUTED, bg=BG2, font=self.f["body"]).pack(side="left")
            lbl = tk.Label(r, text=name, fg=MUTED, bg=BG2, font=self.f["label"])
            lbl.pack(side="left", padx=4)
            self.out_labels[name] = lbl

    # ── Log ────────────────────────────────────────────────────────────────────
    def _log(self, text, tag=None):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag or "")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                tag = ("green" if "✅" in msg else
                       "gold"  if any(x in msg for x in
                                      ["[MCP]","[Script","[Charact","[Valida",
                                       "[HITL]","[Pipe","[Out"]) else
                       "dim"   if msg.startswith("  →") else None)
                self._log(msg.rstrip(), tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ── Stage indicators ───────────────────────────────────────────────────────
    def _set_stage(self, name, state):
        if name not in self.stage_labels:
            return
        dot, lbl = self.stage_labels[name]
        cfg = {"running": ("◉", GOLD), "done": ("●", GREEN),
               "error": ("✗", RED), "idle": ("○", MUTED)}
        sym, col = cfg.get(state, ("○", MUTED))
        dot.config(text=sym, fg=col)
        lbl.config(fg=col)

    def _reset_stages(self):
        for s in self.stages:
            self._set_stage(s, "idle")

    # ── HITL ───────────────────────────────────────────────────────────────────
    def _on_input_change(self, event=None):
        text = self.prompt_text.get("1.0", "end").strip()
        if not text:
            self.detected_var.set("")
            return
        mode = detect_input_mode(text)
        if mode == "manual":
            self.detected_var.set("⚙  detected: SCRIPT / JSON")
            self.detected_lbl.config(fg=GOLD)
        else:
            self.detected_var.set("⚡  detected: AUTO PROMPT")
            self.detected_lbl.config(fg=GREEN)

    def _show_hitl(self, script_json):
        self.script_preview.configure(state="normal")
        self.script_preview.delete("1.0", "end")
        self.script_preview.insert("1.0", json.dumps(script_json, indent=2))
        self.script_preview.configure(state="disabled")
        self.feedback_entry.delete(0, "end")
        self.hitl_frame.grid()

    def _hide_hitl(self):
        self.hitl_frame.grid_remove()

    def _approve(self):
        self._hitl_decision = {"approved": True, "feedback": ""}
        self._hide_hitl()
        self._hitl_event.set()

    def _reject(self):
        self._hitl_decision = {"approved": False,
                                "feedback": self.feedback_entry.get().strip()}
        self._hide_hitl()
        self._hitl_event.set()

    def _mark_output(self, name):
        if name in self.out_labels:
            self.out_labels[name].config(fg=GREEN)

    # ── Run ────────────────────────────────────────────────────────────────────
    def _run_pipeline(self):
        self.run_btn.config(state="disabled", text="⏳  RUNNING…")
        self.status_var.set("Pipeline running…")
        self._reset_stages()
        for lbl in self.out_labels.values():
            lbl.config(fg=MUTED)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        raw_input = self.prompt_text.get("1.0", "end").strip()
        mode = detect_input_mode(raw_input)

        threading.Thread(
            target=self._pipeline_thread,
            args=(mode, raw_input),
            daemon=True
        ).start()

    def _pipeline_thread(self, mode, raw_input):
        try:
            from mcp.init import register_tools
            from graph import build_graph
            from utils.json_utils import save_outputs

            register_tools()

            if mode == "manual":
                try:
                    script = json.loads(raw_input)
                    self._log_queue.put("[Auto-detected] JSON script input.")
                except Exception:
                    self._log_queue.put("[Auto-detected] Raw screenplay — converting to JSON…")
                    script = parse_raw_script_to_json(raw_input)
                user_input = "Manual script provided by user"
            else:
                self._log_queue.put("[Auto-detected] Plain prompt — running auto-generate.")
                user_input = raw_input
                script = {}

            state = {
                "input_mode": mode,
                "user_input": user_input,
                "script": script,
                "characters": [],
                "status": "processing",
                "hitl_feedback": ""
            }

            self._patch_agents()
            graph = build_graph()
            result = graph.invoke(state)

            save_outputs(result)

            self.after(0, lambda: self._mark_output("scene_manifest.json"))
            self.after(0, lambda: self._mark_output("character_db.json"))
            self.after(0, self._on_success)

        except Exception as e:
            self.after(0, lambda err=str(e): self._on_error(err))

    def _patch_agents(self):
        import agents.scriptwriter as sw
        import agents.validator   as vl
        import agents.hitl        as hl
        import agents.character   as ch

        orig_sw = sw.scriptwriter_agent
        orig_vl = vl.validator_agent
        orig_hl = hl.hitl_agent
        orig_ch = ch.character_agent
        app = self

        def wrap(orig, stage):
            def inner(state):
                app.after(0, lambda s=stage: app._set_stage(s, "running"))
                try:
                    r = orig(state)
                    app.after(0, lambda s=stage: app._set_stage(s, "done"))
                    return r
                except Exception:
                    app.after(0, lambda s=stage: app._set_stage(s, "error"))
                    raise
            return inner

        def gui_hitl(state):
            print("[DEBUG] GUI HITL ACTIVE")
            app.after(0, lambda: app._set_stage("HITL Review", "running"))
            app.after(0, lambda: app.status_var.set("Waiting for human review…"))
            app._hitl_event.clear()
            script_copy = dict(state.get("script", {}))
            app.after(0, lambda: app._show_hitl(script_copy))
            app._hitl_event.wait()

            dec = app._hitl_decision
            if dec["approved"]:
                state["status"] = "approved"
                state["hitl_feedback"] = ""
                app.after(0, lambda: app._set_stage("HITL Review", "done"))
                app.after(0, lambda: app.status_var.set("Approved — continuing…"))
            else:
                state["status"] = "rejected"
                state["hitl_feedback"] = dec["feedback"]
                app.after(0, lambda: app._set_stage("HITL Review", "idle"))
                app.after(0, lambda: app.status_var.set("Regenerating with feedback…"))
            return state

        sw.scriptwriter_agent = wrap(orig_sw, "Scriptwriter")
        vl.validator_agent    = wrap(orig_vl, "Validator")
        hl.hitl_agent         = gui_hitl
        ch.character_agent    = wrap(orig_ch, "Character Designer")

        import sys as _sys
        for _mod_name, _attr, _val in [
            ("agents.scriptwriter", "scriptwriter_agent", sw.scriptwriter_agent),
            ("agents.validator",    "validator_agent",    vl.validator_agent),
            ("agents.hitl",         "hitl_agent",         hl.hitl_agent),
            ("agents.character",    "character_agent",    ch.character_agent)
        ]:
            if _mod_name in _sys.modules:
                setattr(_sys.modules[_mod_name], _attr, _val)
            if "graph" in _sys.modules and hasattr(_sys.modules["graph"], _attr):
                setattr(_sys.modules["graph"], _attr, _val)

    def _on_success(self):
        self.run_btn.config(state="normal", text="▶  RUN PIPELINE")
        self.status_var.set("✅  Phase 1 Complete")
        self._log("═" * 48, "gold")
        self._log("✅  Phase 1 Completed Successfully!", "green")
        self._log("  outputs/scene_manifest.json", "green")
        self._log("  outputs/character_db.json",   "green")
        self._log("═" * 48, "gold")

    def _on_error(self, msg):
        self.run_btn.config(state="normal", text="▶  RUN PIPELINE")
        self.status_var.set("❌  Error — see log")
        self._log("❌  " + msg, "red")


# ══════════════════════════════════════════════════════════════════════════════
#  Phase 2 Panel
# ══════════════════════════════════════════════════════════════════════════════

class Phase2Panel(tk.Frame):
    def __init__(self, parent, log_queue: queue.Queue, fonts: dict):
        super().__init__(parent, bg=BG)
        self.f = fonts
        self._log_queue = log_queue

        self._build_ui()
        self._poll_log()

    # ── helpers ────────────────────────────────────────────────────────────────
    def _lbl(self, parent, text, fg=None):
        return tk.Label(parent, text=text, font=self.f["label"],
                        fg=fg or GOLD, bg=parent["bg"])

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=30, pady=12)
        body.columnconfigure(0, weight=50)
        body.columnconfigure(1, weight=50)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        self.status_var = tk.StringVar(value="Ready — load Phase 1 outputs to begin")
        sb = tk.Frame(self, bg=BG2, pady=7)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=GOLD, width=3).pack(side="left", fill="y")
        tk.Label(sb, textvariable=self.status_var, font=self.f["label"],
                 fg=GOLD, bg=BG2, padx=12).pack(side="left")

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)

        # Input paths
        pf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                      highlightbackground=BORDER, highlightthickness=1)
        pf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        pf.columnconfigure(1, weight=1)
        self._lbl(pf, "PHASE 1 OUTPUT PATHS").grid(row=0, column=0, columnspan=3,
                                                    sticky="w", pady=(0, 8))
        paths = [
            ("scene_manifest.json", "outputs/scene_manifest.json"),
            ("character_db.json",   "outputs/character_db.json"),
        ]
        self._path_vars = {}
        for i, (label, default) in enumerate(paths):
            tk.Label(pf, text=label, font=self.f["small"], fg=MUTED,
                     bg=BG2, width=20, anchor="w").grid(row=i+1, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            self._path_vars[label] = var
            tk.Entry(pf, textvariable=var, bg=BG3, fg=WHITE, font=self.f["small"],
                     relief="flat", insertbackground=GOLD).grid(
                         row=i+1, column=1, sticky="ew", padx=(8, 6), ipady=4)
            tk.Button(pf, text="…", font=self.f["small"], bg=BG3, fg=GOLD,
                      relief="flat", padx=4, cursor="hand2",
                      command=lambda l=label, v=var: self._browse(l, v)
                      ).grid(row=i+1, column=2)

        # Run button
        self.run_btn = tk.Button(
            left, text="▶  RUN PHASE 2 PIPELINE", font=self.f["btn"],
            bg=GOLD, fg="#0f0f0f", activebackground=GOLD2, activeforeground="#0f0f0f",
            relief="flat", padx=28, pady=12, cursor="hand2",
            command=self._run_pipeline)
        self.run_btn.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Pipeline progress
        sf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                      highlightbackground=BORDER, highlightthickness=1)
        sf.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self._lbl(sf, "PIPELINE PROGRESS").pack(anchor="w", pady=(0, 8))

        self.stages = ["Scene Parser", "Voice Synthesis"]
        self.stage_labels = {}
        for s in self.stages:
            row = tk.Frame(sf, bg=BG2)
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="○", font=self.f["body"], fg=MUTED, bg=BG2, width=2)
            dot.pack(side="left")
            lbl = tk.Label(row, text=s, font=self.f["label"], fg=MUTED, bg=BG2)
            lbl.pack(side="left")
            self.stage_labels[s] = (dot, lbl)

        # Output files
        of = tk.Frame(left, bg=BG2, padx=16, pady=12,
                      highlightbackground=BORDER, highlightthickness=1)
        of.grid(row=3, column=0, sticky="nsew")
        self._lbl(of, "OUTPUT FILES").pack(anchor="w", pady=(0, 8))

        self.out_files = [
            "outputs/audio/scene_*.wav",
            "outputs/timing_manifest.json",
            "outputs/logs/phase2_task_log.json",
            "outputs/phase2_manifest.json",
        ]
        self.out_labels = {}
        for name in self.out_files:
            r = tk.Frame(of, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="▸", fg=MUTED, bg=BG2, font=self.f["body"]).pack(side="left")
            lbl = tk.Label(r, text=name, fg=MUTED, bg=BG2, font=self.f["label"])
            lbl.pack(side="left", padx=4)
            self.out_labels[name] = lbl

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._lbl(right, "LIVE LOG").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.log_box = scrolledtext.ScrolledText(
            right, bg=BG2, fg="#8aad8a", font=self.f["log"],
            relief="flat", padx=10, pady=8, state="disabled")
        self.log_box.grid(row=1, column=0, sticky="nsew")
        self.log_box.tag_config("gold",  foreground=GOLD)
        self.log_box.tag_config("green", foreground=GREEN)
        self.log_box.tag_config("red",   foreground=RED)
        self.log_box.tag_config("blue",  foreground=BLUE)
        self.log_box.tag_config("dim",   foreground=MUTED)

        self._lbl(right, "SCENE STATUS").grid(row=2, column=0, sticky="w", pady=(12, 6))
        self.scene_frame = tk.Frame(right, bg=BG2, padx=14, pady=10,
                                    highlightbackground=BORDER, highlightthickness=1)
        self.scene_frame.grid(row=3, column=0, sticky="ew")
        self.scene_rows = {}

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _browse(self, label, var):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if path:
            var.set(path)

    def _log(self, text, tag=None):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag or "")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                tag = ("green" if "✅" in msg else
                       "red"   if "❌" in msg else
                       "gold"  if any(x in msg for x in
                                      ["[MCP", "[Scene", "[Voice", "[Output", "[Phase"]) else
                       "blue"  if "parallel" in msg.lower() or "branch" in msg.lower() else
                       "dim"   if msg.startswith("  →") or msg.startswith("  ✅") else None)
                self._log(msg.rstrip(), tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _set_stage(self, name, state):
        key = next((k for k in self.stage_labels if k.startswith(name) or name in k), None)
        if not key:
            return
        dot, lbl = self.stage_labels[key]
        cfg = {"running": ("◉", GOLD), "done": ("●", GREEN),
               "error":   ("✗", RED),  "idle": ("○", MUTED)}
        sym, col = cfg.get(state, ("○", MUTED))
        dot.config(text=sym, fg=col)
        lbl.config(fg=col)

    def _reset_stages(self):
        for s in self.stages:
            self._set_stage(s, "idle")

    def _update_scene_table(self, task_graph: list):
        for w in self.scene_frame.winfo_children():
            w.destroy()
        self.scene_rows = {}

        header = tk.Frame(self.scene_frame, bg=BG2)
        header.pack(fill="x", pady=(0, 4))
        for col, width, text in [(0, 8, "SCENE"), (1, 22, "LOCATION"), (2, 12, "AUDIO")]:
            tk.Label(header, text=text, font=self.f["small"], fg=GOLD,
                     bg=BG2, width=width, anchor="w").grid(row=0, column=col, padx=2)

        for task in task_graph:
            sid = task["scene_id"]
            row = tk.Frame(self.scene_frame, bg=BG3)
            row.pack(fill="x", pady=1)
            loc = task["location"][:20] + "…" if len(task["location"]) > 20 else task["location"]
            lbls = []
            for c, (width, text) in enumerate(zip([8, 22, 12], [str(sid), loc, "⏳"])):
                lbl = tk.Label(row, text=text, font=self.f["small"], fg=MUTED,
                               bg=BG3, width=width, anchor="w")
                lbl.grid(row=0, column=c, padx=2, pady=2)
                lbls.append(lbl)
            self.scene_rows[sid] = lbls

    def _update_scene_cell(self, scene_id: int, col_idx: int, text: str, color: str):
        if scene_id in self.scene_rows:
            self.scene_rows[scene_id][col_idx].config(text=text, fg=color)

    def _mark_output(self, key: str):
        if key in self.out_labels:
            self.out_labels[key].config(fg=GREEN)

    # ── Pipeline ───────────────────────────────────────────────────────────────
    def _run_pipeline(self):
        self.run_btn.config(state="disabled", text="⏳  RUNNING…")
        self.status_var.set("Phase 2 pipeline running…")
        self._reset_stages()
        for lbl in self.out_labels.values():
            lbl.config(fg=MUTED)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        config = {
            "scene_manifest_path": self._path_vars["scene_manifest.json"].get(),
            "character_db_path":   self._path_vars["character_db.json"].get(),
        }
        threading.Thread(target=self._pipeline_thread, args=(config,), daemon=True).start()

    def _pipeline_thread(self, config: dict):
        try:
            from mcp.init2 import register_tools_p2
            from graph2 import build_graph2
            from utils.json_utils2 import save_outputs_p2

            register_tools_p2()

            state = {
                "scene_manifest_path": config["scene_manifest_path"],
                "character_db_path":   config["character_db_path"],
                "scenes":              [],
                "characters":          [],
                "task_graph":          [],
                "audio_results":       [],
                "audio_tracks":        [],
                "timing_manifest":     [],
                "task_log":            [],
                "status":              "processing",
                "error":               None,
            }

            self._patch_agents()
            graph = build_graph2()
            result = graph.invoke(state)

            self.after(0, lambda tg=result.get("task_graph", []):
                       self._update_scene_table(tg))
            self._populate_scene_cells(result)
            save_outputs_p2(result)

            self.after(0, lambda: self._mark_output("outputs/audio/scene_*.wav"))
            self.after(0, lambda: self._mark_output("outputs/timing_manifest.json"))
            self.after(0, lambda: self._mark_output("outputs/logs/phase2_task_log.json"))
            self.after(0, lambda: self._mark_output("outputs/phase2_manifest.json"))
            self.after(0, self._on_success)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.after(0, lambda err=str(e), trace=tb: self._on_error(err, trace))

    def _populate_scene_cells(self, result: dict):
        audio_map = {r["scene_id"]: r for r in result.get("audio_results", [])}

        def _col(status):
            if status == "done":    return "✅", GREEN
            if status == "skipped": return "⏭", MUTED
            if status == "error":   return "❌", RED
            return "⏳", MUTED

        for task in result.get("task_graph", []):
            sid = task["scene_id"]
            at, ac = _col(audio_map.get(sid, {}).get("status", "pending"))
            self.after(0, lambda s=sid, t=at, c=ac: self._update_scene_cell(s, 2, t, c))

    def _patch_agents(self):
        import agents2.scene_parser as sp
        import agents2.voice_synth  as vs
        app = self

        def wrap(orig_mod, attr, stage):
            orig = getattr(orig_mod, attr)
            def inner(state):
                app.after(0, lambda s=stage: app._set_stage(s, "running"))
                app.after(0, lambda: app.status_var.set(f"Running: {stage}…"))
                try:
                    r = orig(state)
                    if attr == "scene_parser_agent" and r.get("task_graph"):
                        app.after(0, lambda tg=r["task_graph"]: app._update_scene_table(tg))
                    app.after(0, lambda s=stage: app._set_stage(s, "done"))
                    return r
                except Exception:
                    app.after(0, lambda s=stage: app._set_stage(s, "error"))
                    raise
            setattr(orig_mod, attr, inner)

        wrap(sp, "scene_parser_agent", "Scene Parser")
        wrap(vs, "voice_synth_agent",  "Voice Synthesis")

    def _on_success(self):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 2 PIPELINE")
        self.status_var.set("✅  Phase 2 Complete — The Studio Floor")
        self._log("═" * 52, "gold")
        self._log("✅  Phase 2 Completed Successfully!", "green")
        self._log("  outputs/audio/               — speech waveforms (.wav)", "green")
        self._log("  outputs/timing_manifest.json — per-line timings",        "green")
        self._log("  outputs/logs/                — task graph execution log","green")
        self._log("  outputs/phase2_manifest.json",                            "green")
        self._log("═" * 52, "gold")

    def _on_error(self, msg: str, trace: str = ""):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 2 PIPELINE")
        self.status_var.set("❌  Error — see log")
        self._log("❌  " + msg, "red")
        if trace:
            for line in trace.splitlines():
                self._log("  " + line, "dim")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    App().mainloop()