# main2.py
"""
PROJECT MONTAGE — Phase 2
GUI Entry Point (Tkinter)
The Studio Floor: Video & Audio Synthesis Layer
Cinematic noir aesthetic matching Phase 1.
"""

import tkinter as tk
from tkinter import scrolledtext, font, filedialog
import threading
import json
import sys
import queue
import os


# ── Stdout redirect ───────────────────────────────────────────────────────────
class QueueStream:
    def __init__(self, q):
        self.q = q
    def write(self, text):
        if text.strip():
            self.q.put(text)
    def flush(self):
        pass


# ── Colour palette (matches Phase 1) ─────────────────────────────────────────
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


class App2(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PROJECT MONTAGE  ·  Phase 2  —  The Studio Floor")
        self.geometry("1200x860")
        self.minsize(1000, 720)
        self.configure(bg=BG)

        self._log_queue = queue.Queue()
        sys.stdout = QueueStream(self._log_queue)

        self._build_fonts()
        self._build_ui()
        self._poll_log()

    def _build_fonts(self):
        self.f_title = font.Font(family="Georgia",     size=20, weight="bold")
        self.f_sub   = font.Font(family="Georgia",     size=10, slant="italic")
        self.f_label = font.Font(family="Courier New", size=9,  weight="bold")
        self.f_body  = font.Font(family="Courier New", size=10)
        self.f_log   = font.Font(family="Courier New", size=9)
        self.f_btn   = font.Font(family="Georgia",     size=10, weight="bold")
        self.f_small = font.Font(family="Courier New", size=8)

    def _lbl(self, parent, text, fg=None):
        return tk.Label(parent, text=text, font=self.f_label,
                        fg=fg or GOLD, bg=parent["bg"])

    # ── UI layout ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG, pady=14)
        hdr.pack(fill="x", padx=30)
        tk.Label(hdr, text="◈  PROJECT MONTAGE  ·  PHASE 2",
                 font=self.f_title, fg=GOLD, bg=BG).pack(side="left")
        tk.Label(hdr, text="  the studio floor — video & audio synthesis",
                 font=self.f_sub, fg=MUTED, bg=BG).pack(side="left", pady=4)
        tk.Frame(self, bg=GOLD, height=1).pack(fill="x", padx=30)

        # Body
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=30, pady=12)
        body.columnconfigure(0, weight=50)
        body.columnconfigure(1, weight=50)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        # Status bar
        self.status_var = tk.StringVar(value="Ready — load Phase 1 outputs to begin")
        sb = tk.Frame(self, bg=BG2, pady=7)
        sb.pack(fill="x", side="bottom")
        tk.Frame(sb, bg=GOLD, width=3).pack(side="left", fill="y")
        tk.Label(sb, textvariable=self.status_var, font=self.f_label,
                 fg=GOLD, bg=BG2, padx=12).pack(side="left")

    def _build_left(self, parent):
        left = tk.Frame(parent, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)

        # ── Input paths ──────────────────────────────────────────────────────
        pf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                      highlightbackground=BORDER, highlightthickness=1)
        pf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        pf.columnconfigure(1, weight=1)
        self._lbl(pf, "PHASE 1 OUTPUT PATHS").grid(row=0, column=0, columnspan=3,
                                                    sticky="w", pady=(0, 8))

        paths = [
            ("scene_manifest.json", "outputs/scene_manifest.json"),
            ("character_db.json",   "outputs/character_db.json"),
            ("images/ directory",   "outputs/images"),
        ]
        self._path_vars = {}
        for i, (label, default) in enumerate(paths):
            tk.Label(pf, text=label, font=self.f_small, fg=MUTED,
                     bg=BG2, width=20, anchor="w").grid(row=i+1, column=0, sticky="w", pady=2)
            var = tk.StringVar(value=default)
            self._path_vars[label] = var
            tk.Entry(pf, textvariable=var, bg=BG3, fg=WHITE, font=self.f_small,
                     relief="flat", insertbackground=GOLD).grid(
                         row=i+1, column=1, sticky="ew", padx=(8, 6), ipady=4)
            tk.Button(pf, text="…", font=self.f_small, bg=BG3, fg=GOLD,
                      relief="flat", padx=4, cursor="hand2",
                      command=lambda l=label, v=var: self._browse(l, v)
                      ).grid(row=i+1, column=2)

        # ── Run button ────────────────────────────────────────────────────────
        self.run_btn = tk.Button(
            left, text="▶  RUN PHASE 2 PIPELINE", font=self.f_btn,
            bg=GOLD, fg="#0f0f0f", activebackground=GOLD2, activeforeground="#0f0f0f",
            relief="flat", padx=28, pady=12, cursor="hand2",
            command=self._run_pipeline)
        self.run_btn.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # ── Pipeline progress ─────────────────────────────────────────────────
        sf = tk.Frame(left, bg=BG2, padx=16, pady=14,
                      highlightbackground=BORDER, highlightthickness=1)
        sf.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self._lbl(sf, "PIPELINE PROGRESS").pack(anchor="w", pady=(0, 8))

        self.stages = [
            "Scene Parser",
            "Voice Synthesis  (audio branch)",
            "Video Generation (video branch)",
            "Face Swap",
            "Lip Sync  [fusion layer]",
        ]
        self.stage_labels = {}
        for s in self.stages:
            row = tk.Frame(sf, bg=BG2)
            row.pack(fill="x", pady=3)
            dot = tk.Label(row, text="○", font=self.f_body, fg=MUTED, bg=BG2, width=2)
            dot.pack(side="left")
            lbl = tk.Label(row, text=s, font=self.f_label, fg=MUTED, bg=BG2)
            lbl.pack(side="left")
            self.stage_labels[s] = (dot, lbl)

        # ── Output files ──────────────────────────────────────────────────────
        of = tk.Frame(left, bg=BG2, padx=16, pady=12,
                      highlightbackground=BORDER, highlightthickness=1)
        of.grid(row=3, column=0, sticky="nsew")
        self._lbl(of, "OUTPUT FILES").pack(anchor="w", pady=(0, 8))

        self.out_files = [
            "outputs/raw_scenes/scene_*.mp4",
            "outputs/audio/scene_*.wav",
            "outputs/logs/phase2_task_log.json",
            "outputs/phase2_manifest.json",
            "outputs/frames/  (frame sequences)",
        ]
        self.out_labels = {}
        for name in self.out_files:
            r = tk.Frame(of, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="▸", fg=MUTED, bg=BG2, font=self.f_body).pack(side="left")
            lbl = tk.Label(r, text=name, fg=MUTED, bg=BG2, font=self.f_label)
            lbl.pack(side="left", padx=4)
            self.out_labels[name] = lbl

    def _build_right(self, parent):
        right = tk.Frame(parent, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        self._lbl(right, "LIVE LOG").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.log_box = scrolledtext.ScrolledText(
            right, bg=BG2, fg="#8aad8a", font=self.f_log,
            relief="flat", padx=10, pady=8, state="disabled")
        self.log_box.grid(row=1, column=0, sticky="nsew")
        self.log_box.tag_config("gold",  foreground=GOLD)
        self.log_box.tag_config("green", foreground=GREEN)
        self.log_box.tag_config("red",   foreground=RED)
        self.log_box.tag_config("blue",  foreground=BLUE)
        self.log_box.tag_config("dim",   foreground=MUTED)

        # Scene status table
        self._lbl(right, "SCENE STATUS").grid(row=2, column=0, sticky="w", pady=(12, 6))
        self.scene_frame = tk.Frame(right, bg=BG2, padx=14, pady=10,
                                    highlightbackground=BORDER, highlightthickness=1)
        self.scene_frame.grid(row=3, column=0, sticky="ew")
        self.scene_rows = {}  # populated dynamically after scene parse

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _browse(self, label, var):
        if "directory" in label.lower() or "images" in label.lower():
            path = filedialog.askdirectory()
        else:
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
                       "gold"  if any(x in msg for x in ["[MCP", "[Scene", "[Voice", "[Video",
                                                           "[Face", "[Lip",  "[Output", "[Phase"]) else
                       "blue"  if "parallel" in msg.lower() or "branch" in msg.lower() else
                       "dim"   if msg.startswith("  →") or msg.startswith("  ✅") else None)
                self._log(msg.rstrip(), tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _set_stage(self, name, state):
        # Support partial name matching for long stage names
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
        for col, width, text in [
            (0, 8,  "SCENE"),
            (1, 22, "LOCATION"),
            (2, 10, "AUDIO"),
            (3, 10, "VIDEO"),
            (4, 10, "SWAP"),
            (5, 10, "SYNC"),
        ]:
            tk.Label(header, text=text, font=self.f_small, fg=GOLD,
                     bg=BG2, width=width, anchor="w").grid(row=0, column=col, padx=2)

        for task in task_graph:
            sid  = task["scene_id"]
            row  = tk.Frame(self.scene_frame, bg=BG3)
            row.pack(fill="x", pady=1)
            loc  = task["location"][:20] + "…" if len(task["location"]) > 20 else task["location"]
            cols = [str(sid), loc, "⏳", "⏳", "⏳", "⏳"]
            lbls = []
            for c, (width, text) in enumerate(zip([8, 22, 10, 10, 10, 10], cols)):
                lbl = tk.Label(row, text=text, font=self.f_small, fg=MUTED,
                               bg=BG3, width=width, anchor="w")
                lbl.grid(row=0, column=c, padx=2, pady=2)
                lbls.append(lbl)
            self.scene_rows[sid] = lbls  # [scene_id_lbl, loc_lbl, audio, video, swap, sync]

    def _update_scene_cell(self, scene_id: int, col_idx: int, text: str, color: str):
        """col_idx: 2=audio, 3=video, 4=swap, 5=sync"""
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
            "images_dir":          self._path_vars["images/ directory"].get(),
        }
        threading.Thread(
            target=self._pipeline_thread,
            args=(config,),
            daemon=True
        ).start()

    def _pipeline_thread(self, config: dict):
        try:
            from mcp.init2 import register_tools_p2
            from graph2 import build_graph2
            from utils.json_utils2 import save_outputs_p2

            register_tools_p2()

            state = {
                "scene_manifest_path": config["scene_manifest_path"],
                "character_db_path":   config["character_db_path"],
                "images_dir":          config["images_dir"],
                "scenes":              [],
                "characters":          [],
                "task_graph":          [],
                "audio_results":       [],
                "video_results":       [],
                "swapped_results":     [],
                "synced_results":      [],
                "final_videos":        [],
                "audio_tracks":        [],
                "task_log":            [],
                "status":              "processing",
                "error":               None,
            }

            self._patch_agents()
            graph = build_graph2()
            result = graph.invoke(state)

            # Update scene table after parse
            self.after(0, lambda tg=result.get("task_graph", []):
                       self._update_scene_table(tg))

            # Update scene cells from results
            self._populate_scene_cells(result)

            save_outputs_p2(result)

            self.after(0, lambda: self._mark_output("outputs/raw_scenes/scene_*.mp4"))
            self.after(0, lambda: self._mark_output("outputs/audio/scene_*.wav"))
            self.after(0, lambda: self._mark_output("outputs/logs/phase2_task_log.json"))
            self.after(0, lambda: self._mark_output("outputs/phase2_manifest.json"))
            self.after(0, lambda: self._mark_output("outputs/frames/  (frame sequences)"))
            self.after(0, self._on_success)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.after(0, lambda err=str(e), trace=tb: self._on_error(err, trace))

    def _populate_scene_cells(self, result: dict):
        audio_map   = {r["scene_id"]: r for r in result.get("audio_results",   [])}
        video_map   = {r["scene_id"]: r for r in result.get("video_results",   [])}
        swapped_map = {r["scene_id"]: r for r in result.get("swapped_results", [])}
        synced_map  = {r["scene_id"]: r for r in result.get("synced_results",  [])}

        def _col(status):
            if status == "done":   return "✅", GREEN
            if status == "skipped": return "⏭", MUTED
            if status == "error":  return "❌", RED
            return "⏳", MUTED

        for task in result.get("task_graph", []):
            sid = task["scene_id"]
            at, ac = _col(audio_map.get(sid,   {}).get("status", "pending"))
            vt, vc = _col(video_map.get(sid,   {}).get("status", "pending"))
            st, sc = _col(swapped_map.get(sid, {}).get("status", "pending"))
            lt, lc = _col(synced_map.get(sid,  {}).get("status", "pending"))
            self.after(0, lambda s=sid, t=at, c=ac: self._update_scene_cell(s, 2, t, c))
            self.after(0, lambda s=sid, t=vt, c=vc: self._update_scene_cell(s, 3, t, c))
            self.after(0, lambda s=sid, t=st, c=sc: self._update_scene_cell(s, 4, t, c))
            self.after(0, lambda s=sid, t=lt, c=lc: self._update_scene_cell(s, 5, t, c))

    def _patch_agents(self):
        """Wraps each agent with GUI stage indicator updates."""
        import agents2.scene_parser as sp
        import agents2.voice_synth  as vs
        import agents2.video_gen    as vg
        import agents2.face_swap    as fs
        import agents2.lip_sync     as ls
        app = self

        def wrap(orig_mod, attr, stage):
            orig = getattr(orig_mod, attr)
            def inner(state):
                app.after(0, lambda s=stage: app._set_stage(s, "running"))
                app.after(0, lambda: app.status_var.set(f"Running: {stage}…"))
                try:
                    # After scene_parser, populate scene table immediately
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
        wrap(vg, "video_gen_agent",    "Video Generation")
        wrap(fs, "face_swap_agent",    "Face Swap")
        wrap(ls, "lip_sync_agent",     "Lip Sync")

    def _on_success(self):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 2 PIPELINE")
        self.status_var.set("✅  Phase 2 Complete — The Studio Floor")
        self._log("═" * 52, "gold")
        self._log("✅  Phase 2 Completed Successfully!", "green")
        self._log("  outputs/raw_scenes/  — lip-synced scene videos", "green")
        self._log("  outputs/audio/       — speech waveforms (.wav)",  "green")
        self._log("  outputs/frames/      — intermediate frame seqs",  "green")
        self._log("  outputs/logs/        — task graph execution log", "green")
        self._log("  outputs/phase2_manifest.json",                    "green")
        self._log("═" * 52, "gold")

    def _on_error(self, msg: str, trace: str = ""):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 2 PIPELINE")
        self.status_var.set("❌  Error — see log")
        self._log("❌  " + msg, "red")
        if trace:
            for line in trace.splitlines():
                self._log("  " + line, "dim")


if __name__ == "__main__":
    App2().mainloop()