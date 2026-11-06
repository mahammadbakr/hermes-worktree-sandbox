"""Durable ledger for worktree-sandbox.

State lives in ``$HERMES_HOME/plugin-data/worktree-sandbox/data.db`` (WAL mode via
``plugins.plugin_storage.plugin_db``), so it survives ``hermes plugins update`` / ``remove``
and follows the active profile. Secrets are never written here: only paths the user already
owns, git branch names, and small bookkeeping values.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any

PLUGIN_NAME = "worktree-sandbox"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS worktrees (
    id           TEXT PRIMARY KEY,
    workspace    TEXT NOT NULL,
    path         TEXT NOT NULL,
    branch       TEXT NOT NULL,
    base_commit  TEXT,
    shadow       INTEGER NOT NULL DEFAULT 0,
    state        TEXT NOT NULL DEFAULT 'active',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    worktree_id  TEXT,
    kind         TEXT NOT NULL,
    detail       TEXT,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_worktree ON events(worktree_id);
CREATE TABLE IF NOT EXISTS races (
    id           TEXT PRIMARY KEY,
    workspace    TEXT NOT NULL,
    spec         TEXT,
    result       TEXT,
    winner       TEXT,
    created_at   REAL NOT NULL
);
"""

# Columns added after the first release; `_migrate` adds any that are missing on an existing DB.
_ADDED_COLUMNS = {
    "worktrees": {"repo_root": "TEXT"},
}


def _now() -> float:
    return time.time()


class Ledger:
    """Small thread-safe wrapper over the plugin's SQLite database.

    The connection is opened lazily so ``register()`` never touches disk during plugin
    discovery (which the capability probe runs with a throwaway ``HERMES_HOME``). A single
    ``RLock`` serialises writers; ``plugin_db`` already opens the file with
    ``check_same_thread=False`` and WAL, so a dashboard reader can coexist with tool writers.
    """

    def __init__(self, connection: sqlite3.Connection | None = None, db_path: Any | None = None) -> None:
        self._conn = connection
        self._db_path = db_path
        self._initialized = False
        self._lock = threading.RLock()

    @property
    def conn(self) -> sqlite3.Connection:
        with self._lock:
            if not self._initialized:
                if self._conn is None:
                    if self._db_path is not None:
                        from pathlib import Path

                        path = Path(self._db_path)
                        path.parent.mkdir(parents=True, exist_ok=True)
                        self._conn = sqlite3.connect(str(path), check_same_thread=False)
                        self._conn.execute("PRAGMA journal_mode=WAL")
                    else:
                        from plugins.plugin_storage import plugin_db

                        self._conn = plugin_db(PLUGIN_NAME)
                try:
                    self._conn.row_factory = sqlite3.Row
                except AttributeError:  # a double without row_factory support (tests)
                    pass
                self._conn.executescript(_SCHEMA)
                self._migrate()
                self._conn.commit()
                self._initialized = True
            conn = self._conn
            if conn is None:  # pragma: no cover - defensive; the block above always assigns one
                raise RuntimeError("worktree-sandbox: ledger connection unavailable")
            return conn

    def _migrate(self) -> None:
        """Add columns introduced after the first release (safe to run on every open)."""
        from contextlib import suppress

        conn = self._conn
        if conn is None:  # pragma: no cover - only reachable before the connection is opened
            return
        for table, columns in _ADDED_COLUMNS.items():
            with suppress(sqlite3.Error):
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                for name, decl in columns.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchall()

    # -- worktrees ---------------------------------------------------------------

    def upsert_worktree(
        self, *, worktree_id: str, workspace: str, path: str, branch: str,
        base_commit: str | None, shadow: bool, state: str = "active", repo_root: str | None = None,
    ) -> None:
        now = _now()
        existing = self.get_worktree(worktree_id)
        if existing is None:
            self._execute(
                "INSERT INTO worktrees (id, workspace, path, branch, base_commit, shadow, state, repo_root,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (worktree_id, workspace, path, branch, base_commit, int(shadow), state, repo_root, now, now),
            )
        else:
            self._execute(
                "UPDATE worktrees SET workspace=?, path=?, branch=?, base_commit=?, shadow=?, state=?,"
                " repo_root=?, updated_at=? WHERE id=?",
                (workspace, path, branch, base_commit, int(shadow), state, repo_root, now, worktree_id),
            )

    def get_worktree(self, worktree_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM worktrees WHERE id=?", (worktree_id,))
        return dict(rows[0]) if rows else None

    def list_worktrees(self, *, workspace: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if workspace:
            clauses.append("workspace=?")
            params.append(workspace)
        if state:
            clauses.append("state=?")
            params.append(state)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._query(f"SELECT * FROM worktrees{where} ORDER BY created_at DESC", tuple(params))
        return [dict(row) for row in rows]

    def set_state(self, worktree_id: str, state: str) -> None:
        self._execute("UPDATE worktrees SET state=?, updated_at=? WHERE id=?", (state, _now(), worktree_id))

    def delete_worktree(self, worktree_id: str) -> None:
        self._execute("DELETE FROM worktrees WHERE id=?", (worktree_id,))
        self._execute("DELETE FROM events WHERE worktree_id=?", (worktree_id,))

    # -- events ------------------------------------------------------------------

    def record_event(self, worktree_id: str | None, kind: str, detail: Any = None) -> None:
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, default=str)
        if detail and len(detail) > 2000:
            detail = detail[:2000] + "...[truncated]"
        self._execute(
            "INSERT INTO events (worktree_id, kind, detail, created_at) VALUES (?, ?, ?, ?)",
            (worktree_id, kind, detail, _now()),
        )

    def recent_events(self, worktree_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 50
        if worktree_id:
            rows = self._query(
                "SELECT * FROM events WHERE worktree_id=? ORDER BY id DESC LIMIT ?", (worktree_id, limit))
        else:
            rows = self._query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    # -- races -------------------------------------------------------------------

    def record_race(self, *, race_id: str, workspace: str, spec: Any, result: Any, winner: str | None) -> None:
        self._execute(
            "INSERT OR REPLACE INTO races (id, workspace, spec, result, winner, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (race_id, workspace, json.dumps(spec, default=str), json.dumps(result, default=str), winner, _now()),
        )

    def get_race(self, race_id: str) -> dict[str, Any] | None:
        rows = self._query("SELECT * FROM races WHERE id=?", (race_id,))
        if not rows:
            return None
        record = dict(rows[0])
        for key in ("spec", "result"):
            if record.get(key):
                try:
                    record[key] = json.loads(record[key])
                except (ValueError, TypeError):
                    pass
        return record
