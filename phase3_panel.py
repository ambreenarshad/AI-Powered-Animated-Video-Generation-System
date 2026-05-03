"""
phase3_panel.py
────────────────
Phase 3 Panel  —  Per-Character Video Generation & Composition

Stages:
  1. Manifest Loader
  2. Image Gen (wan2.5-t2i-preview)
  3. Video Gen (wan2.7-i2v)
  4. A/V Sync
  5. Scene Merge
  6. Compositor
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext

# Load .env BEFORE reading any env vars so the key is available immediately
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; user can still paste the key manually

# ── Colour palette (mirrors main.py) ──────────────────────────────────────────
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

# Current model IDs — update this block whenever models change
_IMAGE_MODEL = "wan2.5-t2i-preview"
_VIDEO_MODEL = "wan2.7-i2v-2026-04-25"
_MODEL_INFO  = f"Image: {_IMAGE_MODEL}  ·  Video: {_VIDEO_MODEL}"

# Stage labels must stay in sync with _STAGE_MAP in _patch_agents()
_STAGES = [
    "Manifest Loader",
    f"Image Gen ({_IMAGE_MODEL})",
    f"Video Gen ({_VIDEO_MODEL})",
    "A/V Sync",
    "Scene Merge",
    "Compositor",
]


class Phase3Panel(tk.Frame):
    """Full Phase 3 UI panel — per-character video generation."""

    def __init__(self, parent, log_queue: queue.Queue, fonts: dict):
        super().__init__(parent, bg=BG)
        self.f          = fonts
        self._log_queue = log_queue
        # Expose stage list as instance attribute so _patch_agents() can read it
        self.STAGES = _STAGES
        self._build_ui()
        self._poll_log()

    # ──────────────────────────────────────────────────────────────────────────
    # UI build
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)
        self._build_left()
        self._build_right()

    def _build_left(self):
        left = tk.Frame(self, bg=BG, padx=28, pady=20)
        left.grid(row=0, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)

        # Title
        tk.Label(
            left,
            text="PHASE 3  ·  Per-Character Video Generation & Composition",
            font=self.f["label"], fg=GOLD, bg=BG,
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        # ── Input paths ──────────────────────────────────────────────────────
        self._path_vars: dict[str, tk.StringVar] = {}
        path_defs = [
            ("scene_manifest.json",  "outputs/scene_manifest.json"),
            ("timing_manifest.json", "outputs/timing_manifest.json"),
            ("character_db.json",    "outputs/character_db.json"),
            ("audio_dir",            "outputs/audio"),
        ]
        for i, (label, default) in enumerate(path_defs):
            var = tk.StringVar(value=default)
            self._path_vars[label] = var
            row_f = tk.Frame(left, bg=BG)
            row_f.grid(row=i + 1, column=0, sticky="ew", pady=3)
            row_f.columnconfigure(1, weight=1)

            tk.Label(
                row_f, text=label, font=self.f["small"],
                fg=MUTED, bg=BG, width=26, anchor="w",
            ).grid(row=0, column=0, padx=(0, 6))
            tk.Entry(
                row_f, textvariable=var, font=self.f["body"],
                bg=BG3, fg=CREAM, insertbackground=GOLD,
                relief="flat", bd=4,
            ).grid(row=0, column=1, sticky="ew")
            tk.Button(
                row_f, text="…", font=self.f["small"], fg=GOLD, bg=BG2,
                relief="flat", cursor="hand2", padx=4,
                command=lambda lbl=label, v=var: self._browse(lbl, v),
            ).grid(row=0, column=2, padx=(4, 0))

        # ── DashScope API key ─────────────────────────────────────────────────
        row_start = len(path_defs) + 1
        key_row = tk.Frame(left, bg=BG)
        key_row.grid(row=row_start, column=0, sticky="ew", pady=(10, 3))
        key_row.columnconfigure(1, weight=1)
        tk.Label(
            key_row, text="DASHSCOPE_API_KEY", font=self.f["small"],
            fg=MUTED, bg=BG, width=26, anchor="w",
        ).grid(row=0, column=0)

        # Read key now — dotenv was loaded at module import, so this will
        # pick up the value from .env without any manual entry needed.
        _env_key = os.getenv("DASHSCOPE_API_KEY", "")
        self._api_key_var = tk.StringVar(value=_env_key)
        tk.Entry(
            key_row, textvariable=self._api_key_var, font=self.f["body"],
            bg=BG3, fg=CREAM, insertbackground=GOLD,
            show="*", relief="flat", bd=4,
        ).grid(row=0, column=1, sticky="ew")

        # Small indicator showing whether the key came from the environment
        self._key_src_var = tk.StringVar(
            value="(loaded from .env)" if _env_key else "(not set — enter manually)"
        )
        tk.Label(
            key_row, textvariable=self._key_src_var,
            font=self.f["small"],
            fg=GREEN if _env_key else RED,
            bg=BG,
        ).grid(row=0, column=2, padx=(8, 0))

        # Update the indicator whenever the user edits the field
        self._api_key_var.trace_add("write", self._on_key_changed)

        # ── Model info label (always reflects actual model IDs) ───────────────
        info_row = tk.Frame(left, bg=BG)
        info_row.grid(row=row_start + 1, column=0, sticky="w", pady=(4, 0))
        tk.Label(
            info_row,
            text=_MODEL_INFO,
            font=self.f["small"], fg=BLUE, bg=BG,
        ).pack(side="left")

        # ── Subtitles toggle ──────────────────────────────────────────────────
        self._subtitles_var = tk.BooleanVar(value=True)
        sub_row = tk.Frame(left, bg=BG)
        sub_row.grid(row=row_start + 2, column=0, sticky="w", pady=(6, 0))
        tk.Checkbutton(
            sub_row, text="Burn accurate subtitles into video",
            variable=self._subtitles_var,
            font=self.f["small"], fg=MUTED, bg=BG,
            selectcolor=BG3, activebackground=BG, activeforeground=GOLD,
        ).pack(side="left")

        # ── Run button ────────────────────────────────────────────────────────
        sep_row = row_start + 3
        tk.Frame(left, bg=BORDER, height=1).grid(
            row=sep_row, column=0, sticky="ew", pady=(16, 12))
        self.run_btn = tk.Button(
            left, text="▶  RUN PHASE 3 PIPELINE",
            font=self.f["btn"], fg=BG, bg=GOLD,
            activebackground=GOLD2, activeforeground=BG,
            relief="flat", padx=20, pady=8, cursor="hand2",
            command=self._run_pipeline,
        )
        self.run_btn.grid(row=sep_row + 1, column=0, sticky="w")

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(
            left, textvariable=self.status_var,
            font=self.f["small"], fg=MUTED, bg=BG,
        ).grid(row=sep_row + 2, column=0, sticky="w", pady=(8, 0))

        # ── Stage indicators ──────────────────────────────────────────────────
        tk.Frame(left, bg=BORDER, height=1).grid(
            row=sep_row + 3, column=0, sticky="ew", pady=(14, 10))
        tk.Label(
            left, text="PIPELINE STAGES",
            font=self.f["small"], fg=GOLD, bg=BG,
        ).grid(row=sep_row + 4, column=0, sticky="w", pady=(0, 6))

        self.stage_labels: dict[str, tuple] = {}
        for j, stage in enumerate(self.STAGES):
            sf  = tk.Frame(left, bg=BG)
            sf.grid(row=sep_row + 5 + j, column=0, sticky="w", pady=2)
            dot = tk.Label(sf, text="○", font=self.f["small"], fg=MUTED, bg=BG)
            dot.pack(side="left", padx=(0, 6))
            lbl = tk.Label(sf, text=stage, font=self.f["small"], fg=MUTED, bg=BG)
            lbl.pack(side="left")
            self.stage_labels[stage] = (dot, lbl)

        # ── Outputs ───────────────────────────────────────────────────────────
        out_start = sep_row + 5 + len(self.STAGES)
        tk.Frame(left, bg=BORDER, height=1).grid(
            row=out_start, column=0, sticky="ew", pady=(14, 8))
        tk.Label(
            left, text="OUTPUTS",
            font=self.f["small"], fg=GOLD, bg=BG,
        ).grid(row=out_start + 1, column=0, sticky="w", pady=(0, 4))

        self.out_labels: dict[str, tk.Label] = {}
        outputs = [
            "outputs/video/final_output.mp4",
            "outputs/video/subtitles.srt",
            "outputs/logs/phase3_task_log.json",
        ]
        for k, key in enumerate(outputs):
            lbl = tk.Label(
                left, text=key, font=self.f["small"], fg=MUTED, bg=BG)
            lbl.grid(row=out_start + 2 + k, column=0, sticky="w")
            self.out_labels[key] = lbl

    def _build_right(self):
        right = tk.Frame(self, bg=BG2, padx=16, pady=20)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        tk.Label(
            right, text="PIPELINE LOG",
            font=self.f["small"], fg=GOLD, bg=BG2,
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.log_box = scrolledtext.ScrolledText(
            right, state="disabled", wrap="word",
            font=self.f["log"], bg=BG3, fg=CREAM,
            insertbackground=GOLD, relief="flat",
            highlightbackground=BORDER, highlightthickness=1,
        )
        self.log_box.grid(row=1, column=0, sticky="nsew")

        self.log_box.tag_config("gold",  foreground=GOLD)
        self.log_box.tag_config("green", foreground=GREEN)
        self.log_box.tag_config("red",   foreground=RED)
        self.log_box.tag_config("blue",  foreground=BLUE)
        self.log_box.tag_config("dim",   foreground=MUTED)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _on_key_changed(self, *_):
        """Update the source indicator when the user edits the key field."""
        val = self._api_key_var.get()
        if val:
            self._key_src_var.set("(set)")
        else:
            self._key_src_var.set("(not set)")

    def _browse(self, label: str, var: tk.StringVar):
        if label == "audio_dir":
            path = filedialog.askdirectory()
        else:
            path = filedialog.askopenfilename(
                filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if path:
            var.set(path)

    def _log(self, text: str, tag=None):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag or "")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                tag = (
                    "green" if "✅" in msg else
                    "red"   if "❌" in msg else
                    "gold"  if "[Phase3]" in msg or "[Phase 3" in msg else
                    "blue"  if "wan2" in msg.lower() or "t2i" in msg.lower() else
                    "dim"   if msg.startswith("  →") or msg.startswith("    ") else
                    None
                )
                self._log(msg.rstrip(), tag)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _set_stage(self, name: str, state: str):
        # Match by substring so partial names still resolve
        entry = next(
            ((k, v) for k, v in self.stage_labels.items()
             if name.lower() in k.lower()),
            None,
        )
        if not entry:
            return
        dot, lbl = entry[1]
        cfg = {
            "running": ("◉", GOLD),
            "done":    ("●", GREEN),
            "error":   ("✗", RED),
            "idle":    ("○", MUTED),
        }
        sym, col = cfg.get(state, ("○", MUTED))
        dot.config(text=sym, fg=col)
        lbl.config(fg=col)

    def _reset_stages(self):
        for s in self.STAGES:
            self._set_stage(s, "idle")

    def _mark_output(self, key: str):
        if key in self.out_labels:
            self.out_labels[key].config(fg=GREEN)

    # ──────────────────────────────────────────────────────────────────────────
    # Pipeline
    # ──────────────────────────────────────────────────────────────────────────

    def _run_pipeline(self):
        self.run_btn.config(state="disabled", text="⏳  RUNNING…")
        self.status_var.set("Phase 3 pipeline running…")
        self._reset_stages()
        for lbl in self.out_labels.values():
            lbl.config(fg=MUTED)
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        config = {
            "scene_manifest_path":  self._path_vars["scene_manifest.json"].get(),
            "timing_manifest_path": self._path_vars["timing_manifest.json"].get(),
            "character_db_path":    self._path_vars["character_db.json"].get(),
            "audio_dir":            self._path_vars["audio_dir"].get(),
            "dashscope_api_key":    self._api_key_var.get().strip(),
            "enable_subtitles":     self._subtitles_var.get(),
        }
        threading.Thread(
            target=self._pipeline_thread, args=(config,), daemon=True
        ).start()

    def _pipeline_thread(self, config: dict):
        try:
            from graph3 import build_graph3

            state = {
                "scene_manifest_path":  config["scene_manifest_path"],
                "timing_manifest_path": config["timing_manifest_path"],
                "character_db_path":    config["character_db_path"],
                "audio_dir":            config["audio_dir"],
                "dashscope_api_key":    config["dashscope_api_key"],
                "enable_subtitles":     config["enable_subtitles"],
                "scenes":          [],
                "characters":      [],
                "timing_manifest": [],
                "task_graph":      [],
                "final_output":    "",
                "subtitle_file":   None,
                "status":          "processing",
                "error":           None,
                "task_log":        [],
            }

            self._patch_agents()
            graph  = build_graph3()
            result = graph.invoke(state)

            self.after(0, lambda: self._mark_output("outputs/video/final_output.mp4"))
            if result.get("subtitle_file"):
                self.after(0, lambda: self._mark_output("outputs/video/subtitles.srt"))
            self.after(0, lambda: self._mark_output("outputs/logs/phase3_task_log.json"))
            self.after(0, self._on_success)

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.after(0, lambda err=str(e), trace=tb: self._on_error(err, trace))

    def _patch_agents(self):
        """Wrap agent functions to update UI stage indicators."""
        import agents3.manifest_loader   as ml
        import agents3.image_gen         as ig
        import agents3.ken_burns         as kb
        import agents3.av_sync_agent     as ava
        import agents3.scene_merge_agent as sma
        import agents3.compositor_agent  as ca

        app = self

        # Keys must match the *prefix* of a stage label for _set_stage() to
        # find them via substring search.
        _STAGE_MAP = {
            "manifest_loader_agent": "Manifest Loader",
            "image_gen_agent":       "Image Gen",
            "ken_burns_agent":       "Video Gen",
            "av_sync_agent":         "A/V Sync",
            "scene_merge_agent":     "Scene Merge",
            "compositor_agent":      "Compositor",
        }

        def wrap(module, fn_name: str):
            stage = _STAGE_MAP[fn_name]
            orig  = getattr(module, fn_name)

            def inner(state):
                app.after(0, lambda s=stage: app._set_stage(s, "running"))
                app.after(0, lambda s=stage: app.status_var.set(f"Running: {s}…"))
                try:
                    r = orig(state)
                    app.after(0, lambda s=stage: app._set_stage(s, "done"))
                    return r
                except Exception:
                    app.after(0, lambda s=stage: app._set_stage(s, "error"))
                    raise

            setattr(module, fn_name, inner)

        wrap(ml,  "manifest_loader_agent")
        wrap(ig,  "image_gen_agent")
        wrap(kb,  "ken_burns_agent")
        wrap(ava, "av_sync_agent")
        wrap(sma, "scene_merge_agent")
        wrap(ca,  "compositor_agent")

    def _on_success(self):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 3 PIPELINE")
        self.status_var.set("✅  Phase 3 Complete — Final Video Ready")
        self._log("═" * 56, "gold")
        self._log("✅  Phase 3 Completed Successfully!", "green")
        self._log("  outputs/video/final_output.mp4  — finished MP4",   "green")
        self._log("  outputs/video/subtitles.srt     — subtitle file",   "green")
        self._log("  outputs/logs/phase3_task_log.json — execution log", "green")
        self._log("═" * 56, "gold")

    def _on_error(self, msg: str, trace: str = ""):
        self.run_btn.config(state="normal", text="▶  RUN PHASE 3 PIPELINE")
        self.status_var.set("❌  Error — see log")
        self._log("❌  " + msg, "red")
        if trace:
            for line in trace.splitlines():
                self._log("  " + line, "dim")