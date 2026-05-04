"""
state_manager.py
─────────────────
Append-only state snapshot system for the Project Montage pipeline.

Every pipeline run or partial re-run:
  1. Serialises the full pipeline JSON state.
  2. Records which asset files were produced/modified.
  3. Saves a diff summary (what changed vs. the previous snapshot).
  4. Persists everything to SQLite (outputs/versions.db).

API:
  manager = StateManager()
  manager.snapshot(state_dict, asset_paths, label)   → version_id (int)
  manager.revert(version_id)                          → state_dict
  manager.history()                                   → [VersionRecord]
  manager.current_version()                           → int | None
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DB_PATH     = "outputs/versions.db"
BACKUP_DIR  = "outputs/version_backups"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class VersionRecord:
    version_id:  int
    label:       str
    timestamp:   float
    state_json:  str          # full serialised state
    asset_paths: list[str]    # files produced at this version
    diff_summary: str         # human-readable change summary

    @property
    def timestamp_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))

    def to_dict(self) -> dict:
        return {
            "version_id":   self.version_id,
            "label":        self.label,
            "timestamp":    self.timestamp_str,
            "asset_paths":  self.asset_paths,
            "diff_summary": self.diff_summary,
        }


# ── StateManager ──────────────────────────────────────────────────────────────

class StateManager:
    """
    Append-only, SQLite-backed state versioning system.
    Asset files are backed up per-version so revert can restore them exactly.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs("outputs", exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self._init_db()

    # ── Database setup ────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    version_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                    label        TEXT    NOT NULL,
                    timestamp    REAL    NOT NULL,
                    state_json   TEXT    NOT NULL,
                    asset_paths  TEXT    NOT NULL,
                    diff_summary TEXT    NOT NULL
                )
            """)
            conn.commit()

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(
        self,
        state: dict[str, Any],
        asset_paths: list[str] | None = None,
        label: str = "",
    ) -> int:
        """
        Save a version snapshot. Returns the new version_id.

        - state: full pipeline state dict
        - asset_paths: list of files created/modified (will be backed up)
        - label: human-readable description of what changed
        """
        asset_paths = asset_paths or []
        state_json  = json.dumps(state, default=str, indent=2)

        # Compute diff summary vs. previous version
        prev = self._last_record()
        diff_summary = self._diff_summary(prev, state, asset_paths, label)

        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO versions
                   (label, timestamp, state_json, asset_paths, diff_summary)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    label or "pipeline run",
                    time.time(),
                    state_json,
                    json.dumps(asset_paths),
                    diff_summary,
                ),
            )
            version_id = cur.lastrowid
            conn.commit()

        # Back up asset files
        if asset_paths:
            self._backup_assets(version_id, asset_paths)

        print(f"[StateManager] ✅ Snapshot v{version_id} saved — {label or 'pipeline run'}")
        return version_id

    # ── Revert ────────────────────────────────────────────────────────────────

    def revert(self, version_id: int) -> dict[str, Any]:
        """
        Restore assets and return the state dict from a previous version.
        Does NOT delete newer versions (append-only log).
        """
        record = self._get_record(version_id)
        if record is None:
            raise ValueError(f"Version {version_id} not found")

        # Restore backed-up asset files
        backup_dir = Path(BACKUP_DIR) / f"v{version_id}"
        if backup_dir.exists():
            asset_paths = json.loads(record["asset_paths"])
            for rel_path in asset_paths:
                src = backup_dir / rel_path.lstrip("/").replace(":", "_")
                if src.exists():
                    dst = Path(rel_path)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            print(f"[StateManager] ↩ Assets restored from v{version_id} backup")

        state = json.loads(record["state_json"])
        print(f"[StateManager] ↩ Reverted to v{version_id} — {record['label']}")
        return state

    # ── History ───────────────────────────────────────────────────────────────

    def history(self) -> list[VersionRecord]:
        """Return all version records, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM versions ORDER BY version_id DESC"
            ).fetchall()
        return [
            VersionRecord(
                version_id=r["version_id"],
                label=r["label"],
                timestamp=r["timestamp"],
                state_json=r["state_json"],
                asset_paths=json.loads(r["asset_paths"]),
                diff_summary=r["diff_summary"],
            )
            for r in rows
        ]

    def current_version(self) -> int | None:
        """Return the latest version_id, or None if no versions exist."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(version_id) as vid FROM versions"
            ).fetchone()
        return row["vid"] if row else None

    def get_version(self, version_id: int) -> VersionRecord | None:
        record = self._get_record(version_id)
        if record is None:
            return None
        return VersionRecord(
            version_id=record["version_id"],
            label=record["label"],
            timestamp=record["timestamp"],
            state_json=record["state_json"],
            asset_paths=json.loads(record["asset_paths"]),
            diff_summary=record["diff_summary"],
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _last_record(self):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM versions ORDER BY version_id DESC LIMIT 1"
            ).fetchone()

    def _get_record(self, version_id: int):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM versions WHERE version_id = ?", (version_id,)
            ).fetchone()

    def _backup_assets(self, version_id: int, asset_paths: list[str]):
        backup_dir = Path(BACKUP_DIR) / f"v{version_id}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for path in asset_paths:
            if os.path.exists(path):
                # Preserve directory structure under the backup
                rel = path.lstrip("/").replace(":", "_")
                dst = backup_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dst)

    def _diff_summary(
        self,
        prev,
        new_state: dict,
        asset_paths: list[str],
        label: str,
    ) -> str:
        if prev is None:
            return f"Initial snapshot. {len(asset_paths)} asset(s) recorded."

        prev_state = json.loads(prev["state_json"])
        changes: list[str] = []

        # Compare top-level status
        if prev_state.get("status") != new_state.get("status"):
            changes.append(
                f"status: {prev_state.get('status')} → {new_state.get('status')}"
            )

        # Compare asset count
        prev_assets = json.loads(prev["asset_paths"])
        if len(asset_paths) != len(prev_assets):
            changes.append(
                f"assets: {len(prev_assets)} → {len(asset_paths)}"
            )

        # New assets
        new_files = set(asset_paths) - set(prev_assets)
        if new_files:
            changes.append(f"new files: {', '.join(os.path.basename(f) for f in new_files)}")

        if label:
            changes.insert(0, label)

        return "; ".join(changes) if changes else "Minor state update"


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    global _manager
    if _manager is None:
        _manager = StateManager()
    return _manager