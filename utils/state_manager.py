"""
utils/state_manager.py
────────────────────────
State Versioning & Snapshot System

Provides:
  - StateManager.snapshot(label, state, asset_paths) → version_id
  - StateManager.revert(version_id) → (state, asset_paths)
  - StateManager.history() → list of version summaries
  - StateManager.diff(v1, v2) → summary of changes

Storage: SQLite (append-only, no version is ever lost)
         + file copies of assets under snapshots/vN/
"""

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Optional


SNAPSHOT_DB   = "outputs/snapshots/versions.db"
SNAPSHOT_ROOT = Path("outputs/snapshots")


class StateManager:
    def __init__(self, db_path: str = SNAPSHOT_DB):
        self.db_path = db_path
        SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── DB setup ──────────────────────────────────────────────────────────────

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS versions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_tag TEXT    NOT NULL,
                    label       TEXT    NOT NULL,
                    timestamp   REAL    NOT NULL,
                    state_json  TEXT    NOT NULL,
                    asset_paths TEXT    NOT NULL,
                    edit_query  TEXT,
                    intent      TEXT,
                    target      TEXT
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(
        self,
        state: dict,
        label: str = "",
        asset_paths: list[str] | None = None,
        edit_query: str = "",
        intent: str = "",
        target: str = "",
    ) -> int:
        """
        Save a full state snapshot.
        Returns the integer version id.
        """
        asset_paths = asset_paths or []
        ts = time.time()

        # Determine version number
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) FROM versions").fetchone()
            next_id = (row[0] or 0) + 1
            version_tag = f"v{next_id}"

        # Copy assets to snapshot folder
        snap_dir = SNAPSHOT_ROOT / version_tag
        snap_dir.mkdir(parents=True, exist_ok=True)

        copied_paths: dict[str, str] = {}
        for src in asset_paths:
            if src and os.path.exists(src):
                dst = snap_dir / Path(src).name
                shutil.copy2(src, dst)
                copied_paths[src] = str(dst)

        # Sanitise state for serialisation (remove non-serialisable objects)
        safe_state = _sanitise(state)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO versions
                   (version_tag, label, timestamp, state_json, asset_paths, edit_query, intent, target)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_tag,
                    label or f"Auto-snapshot at {time.strftime('%H:%M:%S', time.localtime(ts))}",
                    ts,
                    json.dumps(safe_state, default=str),
                    json.dumps(copied_paths),
                    edit_query,
                    intent,
                    target,
                ),
            )

        print(f"[StateManager] ✅ Snapshot {version_tag} saved  ({len(copied_paths)} assets)")
        return next_id

    # ── Revert ────────────────────────────────────────────────────────────────

    def revert(self, version_id: int) -> tuple[dict, dict]:
        """
        Restore state + assets from a snapshot.
        Returns (state_dict, asset_path_map).
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT version_tag, state_json, asset_paths FROM versions WHERE id = ?",
                (version_id,),
            ).fetchone()

        if not row:
            raise ValueError(f"Version {version_id} not found")

        version_tag, state_json, asset_paths_json = row
        state       = json.loads(state_json)
        asset_map   = json.loads(asset_paths_json)

        # Copy assets back to their original locations
        restored: dict[str, str] = {}
        for original_path, snapshot_path in asset_map.items():
            if os.path.exists(snapshot_path):
                os.makedirs(os.path.dirname(original_path) or ".", exist_ok=True)
                shutil.copy2(snapshot_path, original_path)
                restored[original_path] = snapshot_path
                print(f"  ↩  Restored {os.path.basename(original_path)}")

        print(f"[StateManager] ✅ Reverted to {version_tag}  ({len(restored)} assets restored)")
        return state, restored

    # ── History ───────────────────────────────────────────────────────────────

    def history(self) -> list[dict]:
        """Return all version summaries, newest-first."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, version_tag, label, timestamp, edit_query, intent, target
                   FROM versions ORDER BY id DESC"""
            ).fetchall()

        result = []
        for row in rows:
            vid, vtag, label, ts, eq, intent, target = row
            result.append({
                "id":          vid,
                "version_tag": vtag,
                "label":       label,
                "timestamp":   ts,
                "time_str":    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                "edit_query":  eq or "",
                "intent":      intent or "",
                "target":      target or "",
            })
        return result

    # ── Diff ─────────────────────────────────────────────────────────────────

    def diff(self, v1_id: int, v2_id: int) -> str:
        """Return a human-readable summary of what changed between two versions."""
        with self._conn() as conn:
            rows = {
                r[0]: json.loads(r[1])
                for r in conn.execute(
                    "SELECT id, state_json FROM versions WHERE id IN (?, ?)",
                    (v1_id, v2_id),
                ).fetchall()
            }

        if v1_id not in rows or v2_id not in rows:
            return "One or both versions not found."

        s1, s2 = rows[v1_id], rows[v2_id]
        changed_keys = [k for k in set(list(s1) + list(s2)) if s1.get(k) != s2.get(k)]
        if not changed_keys:
            return "No differences found."
        return "Changed keys: " + ", ".join(changed_keys)

    # ── Convenience ──────────────────────────────────────────────────────────

    def latest_id(self) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute("SELECT MAX(id) FROM versions").fetchone()
        return row[0] if row else None

    def get_version(self, version_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, version_tag, label, timestamp, state_json, asset_paths, edit_query, intent, target FROM versions WHERE id = ?",
                (version_id,),
            ).fetchone()
        if not row:
            return None
        vid, vtag, label, ts, state_json, asset_paths_json, eq, intent, target = row
        return {
            "id":          vid,
            "version_tag": vtag,
            "label":       label,
            "timestamp":   ts,
            "time_str":    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
            "state":       json.loads(state_json),
            "asset_paths": json.loads(asset_paths_json),
            "edit_query":  eq or "",
            "intent":      intent or "",
            "target":      target or "",
        }

    def delete_version(self, version_id: int):
        """Delete a snapshot (assets + DB row). Use with caution."""
        version = self.get_version(version_id)
        if not version:
            return
        snap_dir = SNAPSHOT_ROOT / version["version_tag"]
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
        with self._conn() as conn:
            conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitise(obj):
    """Recursively make an object JSON-serialisable."""
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitise(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


# ── Module-level singleton ────────────────────────────────────────────────────
_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    global _manager
    if _manager is None:
        _manager = StateManager()
    return _manager