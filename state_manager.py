"""
state_manager.py
─────────────────
Append-only state snapshot system for the Project Montage pipeline.

Every pipeline run or partial re-run:
  1. Serialises the full pipeline JSON state.
  2. Copies every asset file into a version-specific backup folder.
  3. Records a diff summary (what changed vs. the previous snapshot).
  4. Persists everything to SQLite (outputs/versions.db).

API:
  manager = StateManager()
  manager.snapshot(state_dict, asset_paths, label)   → version_id (int)
  manager.revert(version_id)                          → state_dict
  manager.history()                                   → [VersionRecord]
  manager.current_version()                           → int | None
  manager.get_version(version_id)                     → VersionRecord | None
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

DB_PATH    = "outputs/versions.db"
BACKUP_DIR = Path("outputs/version_backups")


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class VersionRecord:
    version_id:   int
    label:        str
    timestamp:    float
    state_json:   str
    asset_paths:  list[str]
    diff_summary: str

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
    """Append-only, SQLite-backed state versioning system."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs("outputs", exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Database ──────────────────────────────────────────────────────────────

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
        Save a version snapshot.  Returns the new version_id.

        asset_paths: list of file paths to back up (must exist on disk).
                     The backup preserves the full relative path so revert
                     restores each file to its original location.
        """
        asset_paths = [p for p in (asset_paths or []) if p and os.path.exists(p)]
        state_json  = json.dumps(_sanitise(state), default=str, indent=2)

        prev         = self._last_record()
        diff_summary = self._diff_summary(prev, state, asset_paths, label)

        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO versions (label, timestamp, state_json, asset_paths, diff_summary)
                   VALUES (?, ?, ?, ?, ?)""",
                (label or "pipeline run", time.time(), state_json,
                 json.dumps(asset_paths), diff_summary),
            )
            version_id = cur.lastrowid
            conn.commit()

        # Back up every asset file
        self._backup_assets(version_id, asset_paths)

        n = len(asset_paths)
        print(f"[StateManager] ✅ Snapshot v{version_id}: {label!r}  ({n} asset(s) backed up)")
        return version_id

    # ── Revert ────────────────────────────────────────────────────────────────

    def revert(self, version_id: int) -> dict[str, Any]:
        """
        Restore assets from the backup and return the saved state dict.
        Does NOT delete newer versions — append-only log.
        """
        rec = self._get_record(version_id)
        if rec is None:
            raise ValueError(f"Version {version_id} not found")

        backup_root = BACKUP_DIR / f"v{version_id}"
        asset_paths = json.loads(rec["asset_paths"])
        restored    = 0

        for orig_path in asset_paths:
            # Compute where we stored the backup
            backup_file = self._backup_path(version_id, orig_path)
            if backup_file.exists():
                dst = Path(orig_path)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_file, dst)
                restored += 1
            else:
                print(f"  ⚠  Backup missing for {orig_path}")

        print(f"[StateManager] ↩ Reverted to v{version_id}: {rec['label']!r}"
              f"  ({restored}/{len(asset_paths)} files restored)")
        return json.loads(rec["state_json"])

    # ── History ───────────────────────────────────────────────────────────────

    def history(self) -> list[VersionRecord]:
        """Return all version records, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM versions ORDER BY version_id DESC"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def current_version(self) -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(version_id) as vid FROM versions").fetchone()
        return row["vid"] if row else None

    def get_version(self, version_id: int) -> Optional[VersionRecord]:
        rec = self._get_record(version_id)
        return self._row_to_record(rec) if rec else None

    # ── Internal ──────────────────────────────────────────────────────────────

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

    @staticmethod
    def _row_to_record(row) -> VersionRecord:
        return VersionRecord(
            version_id=row["version_id"],
            label=row["label"],
            timestamp=row["timestamp"],
            state_json=row["state_json"],
            asset_paths=json.loads(row["asset_paths"]),
            diff_summary=row["diff_summary"],
        )

    def _backup_path(self, version_id: int, orig_path: str) -> Path:
        """
        Compute the backup path for a given original file path.
        We preserve the full relative path under outputs/version_backups/vN/
        to guarantee uniqueness and correct restore.
        Example:
          orig  = "outputs/images/characters/scene_01_Jack.png"
          backup = outputs/version_backups/v3/outputs/images/characters/scene_01_Jack.png
        """
        # normalise to relative path (strip leading / or ./)
        rel = orig_path.lstrip("./").lstrip("/")
        return BACKUP_DIR / f"v{version_id}" / rel

    def _backup_assets(self, version_id: int, asset_paths: list[str]):
        for orig_path in asset_paths:
            if not os.path.exists(orig_path):
                continue
            dst = self._backup_path(version_id, orig_path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(orig_path, dst)

    def _diff_summary(
        self,
        prev,
        new_state: dict,
        asset_paths: list[str],
        label: str,
    ) -> str:
        if prev is None:
            return f"Initial snapshot — {len(asset_paths)} asset(s)."

        prev_state   = json.loads(prev["state_json"])
        prev_assets  = set(json.loads(prev["asset_paths"]))
        new_assets   = set(asset_paths)
        changes: list[str] = []

        if prev_state.get("status") != new_state.get("status"):
            changes.append(
                f"status {prev_state.get('status')} → {new_state.get('status')}"
            )
        added = new_assets - prev_assets
        if added:
            changes.append(
                "added: " + ", ".join(os.path.basename(f) for f in sorted(added)[:3])
            )
        removed = prev_assets - new_assets
        if removed:
            changes.append(
                "removed: " + ", ".join(os.path.basename(f) for f in sorted(removed)[:3])
            )
        if label:
            changes.insert(0, label)

        return "; ".join(changes) if changes else "State update"


# ── Singleton ─────────────────────────────────────────────────────────────────

_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    global _manager
    if _manager is None:
        _manager = StateManager()
    return _manager


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitise(obj: Any) -> Any:
    """Recursively convert to JSON-safe types."""
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitise(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)