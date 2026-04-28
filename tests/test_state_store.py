"""Round-trip tests for state_store.

Guards against field-addition regressions: if a new field gets added to
`State` but isn't threaded through `save()` / `load()`, the round-trip
equivalence assertion here fails. Also verifies backwards-compat: an old
row missing post-HW10 fields still loads cleanly with sensible defaults.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from reducer import State, new_state  # noqa: E402
from state_store import StateStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return StateStore(str(tmp_path / "state.db"))


def test_fresh_state_round_trips_cleanly(store):
    s = new_state("sid-1")
    store.save(s)
    loaded = store.load("sid-1")
    assert asdict(loaded) == asdict(s), "fresh State round-trip diverged"


def test_populated_state_round_trips_cleanly(store):
    # Build a state with every field non-default so a missing plumbing
    # path shows up as a field-value diff.
    s = State(
        session_id="sid-2",
        page="quiz",
        page_index=7,
        page_entry_time_ms=1_700_000_000_000,
        answers=(
            {"qid": "1", "choice": "a", "correct": True, "attempts": 1,
             "latency_ms": 2000, "first_try_correct": True},
            {"qid": "2", "choice": "b", "correct": True, "attempts": 1,
             "latency_ms": 3000, "first_try_correct": True},
        ),
        attempts={"1": 1, "2": 1},
        latency_ms={"1": 2000, "2": 3000},
        first_try_correct={"1": True, "2": True},
        proficiency=0.82,
        proficiency_ewma=0.82,
        bucket="high",
        pending_bucket="high",
        pending_bucket_count=1,
        bonus_unlocked=True,
        variant_selections={"1": "burn_in", "4": "high"},
    )
    store.save(s)
    loaded = store.load("sid-2")
    # asdict on both sides normalises tuple/dict ordering while keeping
    # every field comparable; the only normalisation we need is the
    # answers tuple (json → list → tuple round-trip).
    assert loaded.answers == s.answers
    assert asdict(loaded) == asdict(s), "populated State round-trip diverged"


def test_every_state_field_is_persisted(store):
    # Regression guard: every `@dataclass(frozen=True) State` field must
    # survive save → load. If this fails after adding a field, plumb it
    # through state_store.load()'s constructor call.
    s = State(
        session_id="sid-3",
        page="result",
        page_index=0,
        page_entry_time_ms=1234,
        answers=(),
        attempts={},
        latency_ms={},
        first_try_correct={},
        proficiency=0.5,
        proficiency_ewma=0.5,
        bucket="medium",
        pending_bucket="low",
        pending_bucket_count=1,
        bonus_unlocked=False,
        variant_selections={},
    )
    store.save(s)
    loaded = store.load("sid-3")
    field_names = [f.name for f in fields(State)]
    for name in field_names:
        assert getattr(loaded, name) == getattr(s, name), (
            f"state field {name!r} did not round-trip cleanly; check "
            f"state_store.load() constructor wiring"
        )


def test_load_unknown_session_returns_fresh_state(store):
    # No side-effects, no SQL exceptions — a cold load returns a fresh
    # default State under the requested session id.
    loaded = store.load("never-seen")
    assert loaded == new_state("never-seen")


def test_load_tolerates_old_row_missing_hw12_fields(store):
    # Legacy row written by a pre-HW12 build that only knew about v0
    # fields. state_store must fill in the new HW12 defaults without
    # raising — backwards-compat via `.get()` in the loader.
    import json
    import sqlite3
    import time

    legacy_payload = {
        "session_id": "sid-legacy",
        "page": "quiz",
        "page_index": 3,
        "page_entry_time_ms": 0,
        "answers": [],
        "attempts": {},
        "latency_ms": {},
        "first_try_correct": {},
        "proficiency": 0.0,
        "bucket": "medium",
        "variant_selections": {},
        # Deliberately omit: proficiency_ewma, pending_bucket,
        # pending_bucket_count, bonus_unlocked.
    }
    with sqlite3.connect(store.db_path) as c:
        c.execute(
            """INSERT INTO sessions(session_id, state_json, updated_at)
               VALUES (?, ?, ?)""",
            ("sid-legacy", json.dumps(legacy_payload), time.time()),
        )

    loaded = store.load("sid-legacy")
    assert loaded.session_id == "sid-legacy"
    assert loaded.proficiency_ewma == 0.0
    assert loaded.pending_bucket == "medium"
    assert loaded.pending_bucket_count == 0
    assert loaded.bonus_unlocked is False


def test_save_overwrites_existing_row(store):
    s1 = new_state("sid-4")
    store.save(s1)
    s2 = State(**{**asdict(s1), "page": "result", "bonus_unlocked": True})
    store.save(s2)
    loaded = store.load("sid-4")
    assert loaded.page == "result"
    assert loaded.bonus_unlocked is True


def test_clear_removes_session(store):
    s = new_state("sid-5")
    store.save(s)
    assert store.load("sid-5").session_id == "sid-5"
    store.clear("sid-5")
    # After clear, loading the same session id returns a fresh default
    # (identical to a never-seen id).
    assert store.load("sid-5") == new_state("sid-5")
