"""SQLite-backed state store, keyed by session_id.

State is serialized as JSON. The store only knows about opaque JSON — the
reducer owns the shape.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from reducer import State, new_state


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def load(self, session_id: str) -> State:
        with self._conn() as c:
            row = c.execute(
                "SELECT state_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return new_state(session_id)
        data = json.loads(row[0])
        return State(
            session_id=data["session_id"],
            page=data.get("page", "home"),
            page_index=data.get("page_index", 0),
            page_entry_time_ms=data.get("page_entry_time_ms", 0),
            answers=tuple(data.get("answers", ())),
            attempts=dict(data.get("attempts", {})),
            latency_ms=dict(data.get("latency_ms", {})),
            first_try_correct=dict(data.get("first_try_correct", {})),
            proficiency=data.get("proficiency", 0.0),
            proficiency_ewma=data.get("proficiency_ewma", 0.0),
            bucket=data.get("bucket", "medium"),
            pending_bucket=data.get("pending_bucket", "medium"),
            pending_bucket_count=data.get("pending_bucket_count", 0),
            bonus_unlocked=data.get("bonus_unlocked", False),
            variant_selections=dict(data.get("variant_selections", {})),
        )

    def save(self, state: State) -> None:
        payload = asdict(state)
        payload["answers"] = list(state.answers)
        blob = json.dumps(payload)
        with self._conn() as c:
            c.execute(
                """INSERT INTO sessions(session_id, state_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET
                     state_json=excluded.state_json,
                     updated_at=excluded.updated_at""",
                (state.session_id, blob, time.time()),
            )

    def clear(self, session_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
