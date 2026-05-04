"""
edit_panel.py
──────────────
Phase 4 — Intelligent Edit & Undo System Panel

Provides:
  • Free-text edit input field
  • Intent classification display
  • Version history panel with diff summaries
  • Undo / revert controls

Integrates with:
  • agents/edit_agent.py     — intent classification
  • agents/edit_executor.py  — intent execution
  • state_manager.py         — versioning & revert
"""

from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any

# ── Colour palette (matches main.py) ─────────────────────────────────────────
BG     = "#0f0f0f"
BG2    = "#1a1a1a"
BG3    = "#242424"
BG4    = "#2d2d2d"
BORDER = "#2e2e2e"
GOLD   = "#c9a84c"
GOLD2  = "#e8c96d"
CREAM  = "#f0e6cc"
MUTED  = "#7a7060"
GREEN  = "#4caf84"
RED    = "#c94c4c"
BLUE   = "#4c8caf"
PURPLE = "#9c6caf"
WHITE  = "#f5f0e8"

# Intent → colour mapping
INTENT_COLORS = {
    "audio":       BLUE,
    "video_frame": PURPLE,
    "video":       GOLD,
    "script":      GREEN,
}


class EditPanel(tk.Frame):
    """
    Intelligent Edit & Undo panel.
    Designed to be embedded as a tab in the main App window.
    """

    def __init__(self, parent, log_queue: queue.Queue, fonts: dict,
                 get_pipeline_state=None, set_pipeline_state=None):
        super().__init__(parent, bg=BG)
        self.f                  = fonts
        self._log_queue         = log_queue
        self._get_pipeline_state = get_pipeline_state   # callable → state dict
        self._set_pipeline_state = set_pipeline_state   # callable(state)
        self._current_state: dict[str, Any] = {}
        self._building = False

        from state_manager import get_state_manager
        self._mgr = get_state_manager()

        self._build_ui()
        self._poll_log()
        self._refresh_history()

    # ──────────────────────────────────────────────────────────────────────────
    # UI construction
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
        left.rowconfigure(5, weight=1)

        # Title
        tk.Label(
            left,
            text="PHASE 4  ·  Intelligent Edit & Undo",
            font=self.f["label"], fg=GOLD, bg=BG,
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        # ── Edit query input ──────────────────────────────────────────────────
        tk.Label(left, text="DESCRIBE YOUR EDIT",
                 font=self.f["small"], fg=MUTED, bg=BG).grid(
            row=1, column=0, sticky="w")

        self._query_var = tk.StringVar()
        query_frame = tk.Frame(left, bg=BG)
        query_frame.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        query_frame.columnconfigure(0, weight=1)

        self._query_entry = tk.Entry(
            query_frame, textvariable=self._query_var,
            font=self.f["body"], bg=BG3, fg=CREAM,
            insertbackground=GOLD, relief="flat", bd=6,
        )
        self._query_entry.grid(row=0, column=0, sticky="ew", ipady=8)
        self._query_entry.bind("<Return>", lambda _: self._on_submit())

        tk.Button(
            query_frame, text="▶ APPLY EDIT",
            font=self.f["btn"], fg=BG, bg=GOLD,
            activebackground=GOLD2, activeforeground=BG,
            relief="flat", padx=14, pady=4, cursor="hand2",
            command=self._on_submit,
        ).grid(row=0, column=1, padx=(8, 0))

        # Example queries
        ex_frame = tk.Frame(left, bg=BG)
        ex_frame.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        tk.Label(ex_frame, text="Examples: ", font=self.f["small"],
                 fg=MUTED, bg=BG).pack(side="left")
        examples = [
            "Make scene 1 darker",
            "Change voice tone to whispered",
            "Apply noir filter",
            "Remove subtitle",
            "Speed up scene 2",
        ]
        for ex in examples:
            btn = tk.Label(
                ex_frame, text=ex, font=self.f["small"],
                fg=BLUE, bg=BG, cursor="hand2",
                padx=4,
            )
            btn.pack(side="left")
            btn.bind("<Button-1>", lambda e, q=ex: self._fill_query(q))

        # ── Classified intent display ─────────────────────────────────────────
        tk.Frame(left, bg=BORDER, height=1).grid(
            row=4, column=0, sticky="ew", pady=(14, 10))
        intent_hdr = tk.Frame(left, bg=BG)
        intent_hdr.grid(row=4, column=0, sticky="ew", pady=(8, 4))
        tk.Label(intent_hdr, text="LAST CLASSIFIED INTENT",
                 font=self.f["small"], fg=MUTED, bg=BG).pack(side="left")

        self._intent_frame = tk.Frame(left, bg=BG2,
                                      highlightbackground=BORDER,
                                      highlightthickness=1,
                                      padx=14, pady=10)
        self._intent_frame.grid(row=5, column=0, sticky="nsew")
        self._intent_frame.columnconfigure(1, weight=1)
        self._intent_labels: dict[str, tk.Label] = {}

        intent_fields = [
            ("intent",     "Intent"),
            ("target",     "Target"),
            ("scope",      "Scope"),
            ("parameters", "Parameters"),
        ]
        for i, (key, label) in enumerate(intent_fields):
            tk.Label(self._intent_frame, text=label + ":",
                     font=self.f["small"], fg=MUTED, bg=BG2,
                     anchor="w", width=12).grid(row=i, column=0, sticky="w", pady=3)
            lbl = tk.Label(self._intent_frame, text="—",
                           font=self.f["body"], fg=CREAM, bg=BG2,
                           anchor="w", wraplength=380, justify="left")
            lbl.grid(row=i, column=1, sticky="w", padx=(8, 0))
            self._intent_labels[key] = lbl

        # Status bar
        self._status_var = tk.StringVar(value="Ready — enter an edit query above")
        tk.Label(left, textvariable=self._status_var,
                 font=self.f["small"], fg=MUTED, bg=BG).grid(
            row=6, column=0, sticky="w", pady=(10, 0))

    def _build_right(self):
        right = tk.Frame(self, bg=BG2, padx=16, pady=20)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        # ── Version history header ────────────────────────────────────────────
        hdr = tk.Frame(right, bg=BG2)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hdr.columnconfigure(0, weight=1)

        tk.Label(hdr, text="VERSION HISTORY",
                 font=self.f["small"], fg=GOLD, bg=BG2).grid(
            row=0, column=0, sticky="w")

        btn_frame = tk.Frame(hdr, bg=BG2)
        btn_frame.grid(row=0, column=1, sticky="e")

        self._undo_btn = tk.Button(
            btn_frame, text="↩ UNDO",
            font=self.f["small"], fg=BG, bg=GOLD,
            relief="flat", padx=10, pady=3, cursor="hand2",
            command=self._on_undo,
        )
        self._undo_btn.pack(side="left", padx=(0, 6))

        tk.Button(
            btn_frame, text="⟳ REFRESH",
            font=self.f["small"], fg=MUTED, bg=BG3,
            relief="flat", padx=10, pady=3, cursor="hand2",
            command=self._refresh_history,
        ).pack(side="left")

        # ── Version list ──────────────────────────────────────────────────────
        self._version_frame = tk.Frame(right, bg=BG2)
        self._version_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._version_frame.columnconfigure(0, weight=1)

        # Column headers
        col_hdr = tk.Frame(self._version_frame, bg=BG3)
        col_hdr.pack(fill="x", pady=(0, 2))
        for text, w in [("#", 4), ("Label", 22), ("Time", 18), ("Changes", 30)]:
            tk.Label(col_hdr, text=text, font=self.f["small"],
                     fg=GOLD, bg=BG3, width=w, anchor="w").pack(side="left", padx=2)

        # Scrollable history list
        hist_outer = tk.Frame(right, bg=BG2)
        hist_outer.grid(row=2, column=0, sticky="nsew")
        hist_outer.rowconfigure(0, weight=1)
        hist_outer.columnconfigure(0, weight=1)

        canvas    = tk.Canvas(hist_outer, bg=BG2, highlightthickness=0)
        scrollbar = tk.Scrollbar(hist_outer, orient="vertical", command=canvas.yview)
        self._hist_inner = tk.Frame(canvas, bg=BG2)

        self._hist_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._hist_inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ── Log ───────────────────────────────────────────────────────────────
        tk.Frame(right, bg=BORDER, height=1).grid(
            row=3, column=0, sticky="ew", pady=(6, 6))
        tk.Label(right, text="EDIT LOG",
                 font=self.f["small"], fg=GOLD, bg=BG2).grid(
            row=4, column=0, sticky="w", pady=(0, 4))

        self.log_box = scrolledtext.ScrolledText(
            right, state="disabled", wrap="word", height=8,
            font=self.f["log"], bg=BG3, fg=CREAM,
            insertbackground=GOLD, relief="flat",
        )
        self.log_box.grid(row=5, column=0, sticky="ew")
        self.log_box.tag_config("gold",  foreground=GOLD)
        self.log_box.tag_config("green", foreground=GREEN)
        self.log_box.tag_config("red",   foreground=RED)
        self.log_box.tag_config("blue",  foreground=BLUE)
        self.log_box.tag_config("dim",   foreground=MUTED)
        self.log_box.tag_config("purple",foreground=PURPLE)

    # ──────────────────────────────────────────────────────────────────────────
    # Public API — called by main App to inject current state
    # ──────────────────────────────────────────────────────────────────────────

    def load_state(self, state: dict):
        """Inject the current pipeline state so edits can be applied."""
        self._current_state = state
        self._status_var.set(
            f"State loaded — {len(state.get('task_graph', []))} scene(s) available"
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    def _fill_query(self, text: str):
        self._query_var.set(text)
        self._query_entry.focus()

    def _on_submit(self):
        query = self._query_var.get().strip()
        if not query:
            return
        self._status_var.set("Classifying intent…")
        self._log(f"▶ Edit request: {query}", "gold")
        threading.Thread(target=self._apply_edit_thread, args=(query,), daemon=True).start()

    def _on_undo(self):
        self._status_var.set("Reverting to previous version…")
        threading.Thread(target=self._undo_thread, daemon=True).start()

    def _on_revert_to(self, version_id: int):
        self._status_var.set(f"Reverting to v{version_id}…")
        threading.Thread(target=self._revert_thread,
                         args=(version_id,), daemon=True).start()

    # ──────────────────────────────────────────────────────────────────────────
    # Background threads
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_edit_thread(self, query: str):
        try:
            from agents.edit_agent    import classify_edit_intent
            from agents.edit_executor import execute_edit

            # 1. Classify
            intent = classify_edit_intent(query)
            self.after(0, lambda i=intent: self._show_intent(i))
            self._log(f"  Intent: {intent['intent']} → target={intent['target']} "
                      f"scope={intent['scope']}", "blue")

            # 2. Snapshot current state BEFORE applying edit
            state = self._current_state or {}
            self._mgr.snapshot(
                state,
                asset_paths=self._collect_assets(),
                label=f"Before: {query[:50]}",
            )

            # 3. Execute
            self._log(f"  Executing '{intent['intent']}'…", "dim")
            new_state, modified_assets, label = execute_edit(state, intent)

            # 4. Snapshot AFTER applying edit
            self._mgr.snapshot(
                new_state,
                asset_paths=modified_assets or self._collect_assets(),
                label=label,
            )

            # 5. Push updated state back
            self._current_state = new_state
            if self._set_pipeline_state:
                self.after(0, lambda s=new_state: self._set_pipeline_state(s))

            self._log(f"  ✅ {label}", "green")
            self.after(0, lambda: self._status_var.set(f"✅ {label}"))
            self.after(0, self._refresh_history)

        except Exception as exc:
            import traceback
            self._log(f"  ❌ Edit failed: {exc}", "red")
            self._log(traceback.format_exc(), "dim")
            self.after(0, lambda: self._status_var.set(f"❌ Error — see log"))

    def _undo_thread(self):
        try:
            history = self._mgr.history()
            # Find the previous version (skip the last 2 — before+after of last edit)
            if len(history) < 2:
                self.after(0, lambda: self._status_var.set("Nothing to undo"))
                return
            # The most recent "Before:" snapshot is our revert target
            target_version = None
            for rec in history:
                if rec.label.startswith("Before:"):
                    target_version = rec.version_id
                    break
            if target_version is None:
                target_version = history[1].version_id  # second-most-recent

            self._revert_to_version(target_version)
        except Exception as exc:
            self._log(f"  ❌ Undo failed: {exc}", "red")
            self.after(0, lambda: self._status_var.set("❌ Undo failed"))

    def _revert_thread(self, version_id: int):
        try:
            self._revert_to_version(version_id)
        except Exception as exc:
            self._log(f"  ❌ Revert failed: {exc}", "red")

    def _revert_to_version(self, version_id: int):
        restored_state = self._mgr.revert(version_id)
        self._current_state = restored_state
        if self._set_pipeline_state:
            self.after(0, lambda s=restored_state: self._set_pipeline_state(s))
        rec = self._mgr.get_version(version_id)
        label = rec.label if rec else f"v{version_id}"
        self._log(f"  ↩ Reverted to v{version_id}: {label}", "purple")
        self.after(0, lambda: self._status_var.set(f"↩ Reverted to v{version_id}"))
        self.after(0, self._refresh_history)

    # ──────────────────────────────────────────────────────────────────────────
    # History panel
    # ──────────────────────────────────────────────────────────────────────────

    def _refresh_history(self):
        for w in self._hist_inner.winfo_children():
            w.destroy()

        try:
            records = self._mgr.history()
        except Exception:
            records = []

        current = self._mgr.current_version()

        if not records:
            tk.Label(self._hist_inner, text="No versions yet.",
                     font=self.f["small"], fg=MUTED, bg=BG2).pack(pady=8)
            return

        for rec in records:
            is_current = (rec.version_id == current)
            row_bg = BG3 if is_current else BG2
            row = tk.Frame(self._hist_inner, bg=row_bg,
                           highlightbackground=GOLD if is_current else BORDER,
                           highlightthickness=1 if is_current else 0)
            row.pack(fill="x", pady=2, padx=2)
            row.columnconfigure(3, weight=1)

            # Version badge
            badge_fg = GOLD if is_current else MUTED
            tk.Label(row, text=f"v{rec.version_id}", font=self.f["small"],
                     fg=badge_fg, bg=row_bg, width=4, anchor="w").grid(
                row=0, column=0, padx=(6, 2), pady=4)

            # Label (truncated)
            label_text = rec.label[:24] + "…" if len(rec.label) > 24 else rec.label
            tk.Label(row, text=label_text, font=self.f["small"],
                     fg=CREAM if is_current else MUTED, bg=row_bg,
                     width=22, anchor="w").grid(row=0, column=1, padx=2)

            # Timestamp
            ts = time.strftime("%H:%M:%S", time.localtime(rec.timestamp))
            tk.Label(row, text=ts, font=self.f["small"],
                     fg=MUTED, bg=row_bg, width=10, anchor="w").grid(
                row=0, column=2, padx=2)

            # Diff summary
            diff_text = rec.diff_summary[:38] + "…" if len(rec.diff_summary) > 38 else rec.diff_summary
            tk.Label(row, text=diff_text, font=self.f["small"],
                     fg=MUTED, bg=row_bg, anchor="w").grid(
                row=0, column=3, sticky="w", padx=(4, 2))

            # Revert button
            if not is_current:
                tk.Button(
                    row, text="↩",
                    font=self.f["small"], fg=GOLD, bg=BG3,
                    relief="flat", padx=6, cursor="hand2",
                    command=lambda vid=rec.version_id: self._on_revert_to(vid),
                ).grid(row=0, column=4, padx=(4, 6))
            else:
                tk.Label(row, text="● CURRENT", font=self.f["small"],
                         fg=GREEN, bg=row_bg, padx=6).grid(row=0, column=4)

    # ──────────────────────────────────────────────────────────────────────────
    # Intent display
    # ──────────────────────────────────────────────────────────────────────────

    def _show_intent(self, intent: dict):
        target = intent.get("target", "")
        color  = INTENT_COLORS.get(target, CREAM)

        self._intent_labels["intent"].config(
            text=intent.get("intent", "—"), fg=color)
        self._intent_labels["target"].config(
            text=target, fg=color)
        self._intent_labels["scope"].config(
            text=intent.get("scope", "all"), fg=CREAM)
        params = intent.get("parameters", {})
        self._intent_labels["parameters"].config(
            text=json.dumps(params, indent=None) if params else "(none)",
            fg=MUTED)

    # ──────────────────────────────────────────────────────────────────────────
    # Log helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _log(self, text: str, tag: str | None = None):
        # Can be called from any thread
        self.after(0, lambda t=text, g=tag: self._log_main(t, g))

    def _log_main(self, text: str, tag: str | None):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n", tag or "")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_log(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                tag = (
                    "green"  if "✅" in msg else
                    "red"    if "❌" in msg else
                    "gold"   if "[EditAgent]" in msg or "[StateManager]" in msg else
                    "purple" if "↩" in msg else
                    "dim"
                )
                self._log_main(msg.rstrip(), tag)
        except Exception:
            pass
        self.after(120, self._poll_log)

    # ──────────────────────────────────────────────────────────────────────────
    # Asset collection
    # ──────────────────────────────────────────────────────────────────────────

    def _collect_assets(self) -> list[str]:
        """Gather all current output asset paths for snapshotting."""
        import glob as _glob
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
        ]
        assets: list[str] = []
        for pat in patterns:
            assets.extend(_glob.glob(pat))
        return assets