#main.py
"""
PROJECT MONTAGE — Phase 1
GUI Entry Point (Tkinter)
Cinematic noir aesthetic: deep charcoal + amber gold
"""

import tkinter as tk
from tkinter import scrolledtext, font
import threading
import json
import re
import sys
import queue


# ── Redirect stdout so print() appears in the GUI log ─────────────────────────
class QueueStream:
    def __init__(self, q):
        self.q = q
    def write(self, text):
        if text.strip():
            self.q.put(text)
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
WHITE  = "#f5f0e8"


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
    """
    Auto-detects whether the input is a manual script/JSON or a plain prompt.
    Returns 'manual' or 'auto'.
    """
    stripped = text.strip()
    # JSON detection
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            json.loads(stripped)
            return "manual"
        except Exception:
            pass
    # Raw screenplay detection: starts with "Scene N:"
    if re.match(r"Scene\s*\d+\s*:", stripped, re.IGNORECASE):
        return "manual"
    return "auto"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PROJECT MONTAGE  ·  Phase 1")
        self.geometry("1140x820")
        self.minsize(960, 700)
        self.configure(bg=BG)

        self._log_queue = queue.Queue()
        self._hitl_event = threading.Event()
        self._hitl_decision = {"approved": False, "feedback": ""}

        sys.stdout = QueueStream(self._log_queue)

        self._build_fonts()
        self._build_ui()
        self._poll_log()

    def _build_fonts(self):
        self.f_title = font.Font(family="Georgia", size=22, weight="bold")
        self.f_sub   = font.Font(family="Georgia", size=11, slant="italic")
        self.f_label = font.Font(family="Courier New", size=9, weight="bold")
        self.f_body  = font.Font(family="Courier New", size=10)
        self.f_log   = font.Font(family="Courier New", size=9)
        self.f_btn   = font.Font(family="Georgia", size=10, weight="bold")

    def _lbl(self, parent, text, fg=None):
        return tk.Label(parent, text=text, font=self.f_label,
                        fg=fg or GOLD, bg=parent["bg"])

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self, bg=BG, pady=16)
        hdr.pack(fill="x", padx=30)
        tk.Label(hdr, text="◈  PROJECT MONTAGE", font=self.f_title,
                 fg=GOLD, bg=BG).pack(side="left")
        tk.Label(hdr, text="  autonomous story & image generation",
                 font=self.f_sub, fg=MUTED, bg=BG).pack(side="left", pady=6)
        tk.Frame(self, bg=GOLD, height=1).pack(fill="x", padx=30)

        # ── Body ──
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=30, pady=14)
        body.columnconfigure(0, weight=55)
        body.columnconfigure(1, weight=45)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        # ── Status bar ──
        self.status_var = tk.StringVar(value="Ready")
        sb = tk.Frame(self, bg=BG2, pady=7)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=GOLD, width=3).pack(side="left", fill="y")
        tk.Label(sb, textvariable=self.status_var, font=self.f_label,
                 fg=GOLD, bg=BG2, padx=12).pack(side="left")

    def _build_left(self, parent):
        # Create a canvas with scrollbar for the left panel
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

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=canvas.winfo_width())
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

        # ── Input box (single unified area) ──
        inf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                       highlightbackground=BORDER, highlightthickness=1)
        inf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        inf.columnconfigure(0, weight=1)

        self._lbl(inf, "PROMPT  /  SCRIPT").grid(row=0, column=0, sticky="w")

        # Subtle hint label replacing the old mode buttons
        hint = tk.Label(
            inf,
            text="Enter a plain prompt or paste a raw screenplay(Scene 1: ...  Speaker: ...  [Visual] ...). Mode is detected automatically.",
            font=self.f_label, fg=MUTED, bg=BG2, justify="left", wraplength=440)
        hint.grid(row=1, column=0, sticky="w", pady=(4, 8))

        self.prompt_text = scrolledtext.ScrolledText(
            inf, height=8, bg=BG3, fg=WHITE, font=self.f_body,
            relief="flat", insertbackground=GOLD, wrap="word", padx=10, pady=8)
        self.prompt_text.grid(row=2, column=0, sticky="ew")
        self.prompt_text.insert("1.0",
            "Write a 3-scene thriller in New York City. "
            "Two main characters planning a heist. "
            "Include tense dialogues and cinematic visual cues.")

        # ── Detected mode indicator ──
        self.detected_var = tk.StringVar(value="")
        self.detected_lbl = tk.Label(
            inf, textvariable=self.detected_var,
            font=self.f_label, fg=MUTED, bg=BG2, anchor="e")
        self.detected_lbl.grid(row=3, column=0, sticky="e", pady=(4, 0))

        # Update indicator as user types
        self.prompt_text.bind("<KeyRelease>", self._on_input_change)
        self._on_input_change()  # run once on startup

        # ── Run button ──
        self.run_btn = tk.Button(
            left, text="▶  RUN PIPELINE", font=self.f_btn,
            bg=GOLD, fg="#0f0f0f", activebackground=GOLD2, activeforeground="#0f0f0f",
            relief="flat", padx=28, pady=11, cursor="hand2",
            command=self._run_pipeline)
        self.run_btn.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # ── HITL panel (hidden until needed) ──
        self.hitl_frame = tk.Frame(left, bg=BG2,
                                   highlightbackground=GOLD, highlightthickness=1)
        self.hitl_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.hitl_frame.grid_remove()

        ht = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=10)
        ht.pack(fill="x")
        self._lbl(ht, "⬡  HUMAN REVIEW CHECKPOINT").pack(anchor="w")

        self.script_preview = scrolledtext.ScrolledText(
            self.hitl_frame, height=8, bg=BG3, fg=CREAM,
            font=self.f_log, relief="flat", padx=10, pady=8, state="disabled")
        self.script_preview.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        fb = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=8)
        fb.pack(fill="x")
        self._lbl(fb, "FEEDBACK (optional)").pack(anchor="w")
        self.feedback_entry = tk.Entry(
            fb, bg=BG3, fg=WHITE, font=self.f_body,
            relief="flat", insertbackground=GOLD)
        self.feedback_entry.pack(fill="x", pady=(5, 0), ipady=6)

        hb = tk.Frame(self.hitl_frame, bg=BG2, padx=16, pady=10)
        hb.pack(fill="x")
        tk.Button(hb, text="✓  APPROVE", font=self.f_btn, bg=GREEN, fg="#0f0f0f",
                  relief="flat", padx=20, pady=8, cursor="hand2",
                  command=self._approve).pack(side="left", padx=(0, 8))
        tk.Button(hb, text="✗  REJECT & REGENERATE", font=self.f_btn, bg=RED,
                  fg=WHITE, relief="flat", padx=20, pady=8, cursor="hand2",
                  command=self._reject).pack(side="left")

    def _on_input_change(self, event=None):
        """Live-updates the detected mode label as the user types."""
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

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        self._lbl(right, "PIPELINE PROGRESS").grid(row=0, column=0, sticky="w", pady=(0, 8))
        pf = tk.Frame(right, bg=BG2, padx=14, pady=12,
                      highlightbackground=BORDER, highlightthickness=1)
        pf.grid(row=0, column=0, sticky="ew", pady=(18, 10))

        self.stages = ["Scriptwriter", "Validator", "HITL Review",
                       "Character Designer", "Image Synthesizer"]
        self.stage_labels = {}
        for s in self.stages:
            row = tk.Frame(pf, bg=BG2)
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="○", font=self.f_body, fg=MUTED, bg=BG2, width=2)
            dot.pack(side="left")
            lbl = tk.Label(row, text=s, font=self.f_label, fg=MUTED, bg=BG2)
            lbl.pack(side="left")
            self.stage_labels[s] = (dot, lbl)

        self._lbl(right, "LIVE LOG").grid(row=1, column=0, sticky="w", pady=(10, 6))
        self.log_box = scrolledtext.ScrolledText(
            right, bg=BG2, fg="#8aad8a", font=self.f_log,
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
        for name in ["scene_manifest.json", "character_db.json", "images/"]:
            r = tk.Frame(of, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="▸", fg=MUTED, bg=BG2, font=self.f_body).pack(side="left")
            lbl = tk.Label(r, text=name, fg=MUTED, bg=BG2, font=self.f_label)
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
                       "gold"  if any(x in msg for x in ["[MCP]","[Script","[Charact","[Image","[Valida","[HITL]","[Pipe","[Out"]) else
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
        mode = detect_input_mode(raw_input)  # auto-detect here

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
                "images": [],
                "status": "processing",
                "hitl_feedback": ""
            }

            self._patch_agents()
            graph = build_graph()
            result = graph.invoke(state)

            save_outputs(result)

            self.after(0, lambda: self._mark_output("scene_manifest.json"))
            self.after(0, lambda: self._mark_output("character_db.json"))
            self.after(0, lambda: self._mark_output("images/"))
            self.after(0, self._on_success)

        except Exception as e:
            self.after(0, lambda err=str(e): self._on_error(err))

    def _patch_agents(self):
        import agents.scriptwriter as sw
        import agents.validator   as vl
        import agents.hitl        as hl
        import agents.character   as ch
        import agents.image       as im

        orig_sw = sw.scriptwriter_agent
        orig_vl = vl.validator_agent
        orig_hl = hl.hitl_agent
        orig_ch = ch.character_agent
        orig_im = im.image_agent
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
        im.image_agent        = wrap(orig_im, "Image Synthesizer")

        # ── Re-patch every module that may have already imported these
        #    by name (e.g. `from agents.character import character_agent`).
        #    Without this the graph holds stale pre-wrap references.
        import sys as _sys
        for _mod_name, _attr, _val in [
            ("agents.scriptwriter", "scriptwriter_agent", sw.scriptwriter_agent),
            ("agents.validator",    "validator_agent",    vl.validator_agent),
            ("agents.hitl",         "hitl_agent",         hl.hitl_agent),
            ("agents.character",    "character_agent",    ch.character_agent),
            ("agents.image",        "image_agent",        im.image_agent),
        ]:
            if _mod_name in _sys.modules:
                setattr(_sys.modules[_mod_name], _attr, _val)
            # Also patch graph.py if it imported the function directly
            if "graph" in _sys.modules and hasattr(_sys.modules["graph"], _attr):
                setattr(_sys.modules["graph"], _attr, _val)

    def _on_success(self):
        self.run_btn.config(state="normal", text="▶  RUN PIPELINE")
        self.status_var.set("✅  Phase 1 Complete")
        self._log("═" * 48, "gold")
        self._log("✅  Phase 1 Completed Successfully!", "green")
        self._log("  outputs/scene_manifest.json", "green")
        self._log("  outputs/character_db.json",   "green")
        self._log("  outputs/images/",             "green")
        self._log("═" * 48, "gold")

    def _on_error(self, msg):
        self.run_btn.config(state="normal", text="▶  RUN PIPELINE")
        self.status_var.set("❌  Error — see log")
        self._log("❌  " + msg, "red")


if __name__ == "__main__":
    App().mainloop()