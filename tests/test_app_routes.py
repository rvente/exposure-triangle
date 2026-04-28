"""Flask route-level tests (test-client, no Playwright).

Covers HTTP-side behavior the reducer tests can't see:
  - Bonus URL guard: /quiz/9 and /quiz/10 must redirect to /result for a
    learner whose bonus_unlocked flag is still False, in live (non-static)
    mode. The static build intentionally skips this guard so frozen-flask
    can render every bonus HTML; LocalBackend enforces client-side.
  - Normal quiz routes serve 200 and include the variant content.
  - Chapter-nav Bonus pip appears once bonus_unlocked is True.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
import reducer  # noqa: E402


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "state.db"))
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as c:
        yield c


def _advance_to_quiz_page(client, page_index):
    """Prime a session so state.page_index == page_index. Uses the /start
    flow + direct state-store writes for test determinism."""
    # Hit /start so the session cookie is set and SQLite row exists.
    client.post("/start", follow_redirects=False)


def _unlock_bonus(app, sid):
    """Reach into the store and flip `bonus_unlocked` on the session.
    Exercises the live-mode bonus-aware routes without walking the
    full answer flow."""
    from state_store import StateStore

    store = StateStore(app.config["_db_path"])
    s = store.load(sid)
    s = replace(s, bonus_unlocked=True)
    store.save(s)


def test_bonus_url_redirects_to_result_when_gate_locked(client):
    # Fresh session — bonus stays locked. Direct-URL hit on a bonus qid
    # should 302 to /result rather than leak the bonus question.
    for bonus_qid in reducer.BONUS_QUIZ_IDS:
        r = client.get(f"/quiz/{bonus_qid}", follow_redirects=False)
        assert r.status_code in (301, 302), (
            f"/quiz/{bonus_qid} should redirect when bonus_unlocked=False; "
            f"got {r.status_code}"
        )
        assert "/result" in r.headers.get("Location", ""), (
            f"/quiz/{bonus_qid} should redirect to /result; got "
            f"Location={r.headers.get('Location')!r}"
        )


def test_main_flow_quiz_url_serves_200(client):
    # Sanity: the main-flow routes should not be affected by the bonus
    # guard.
    r = client.get("/quiz/4", follow_redirects=False)
    assert r.status_code == 200


def test_main_flow_quiz_carries_variant_content_attrs(client):
    # The quiz.html form carries data-correct-choice + data-msg-* so the
    # LocalBackend JS can render feedback client-side. Regression guard
    # for the HW12 content-threading work (content vs quiz.burn_in).
    r = client.get("/quiz/4", follow_redirects=False)
    body = r.data.decode("utf-8")
    for attr in (
        'data-qid="4"',
        "data-correct-choice=",
        "data-msg-correct=",
        "data-msg-hint=",
        "data-msg-reveal=",
    ):
        assert attr in body, f"/quiz/4 missing {attr!r}"


def test_bonus_url_serves_200_when_unlocked(client, tmp_path):
    # Walk the session into a state where bonus_unlocked=True, then
    # assert the bonus route serves content instead of bouncing.
    # Directly modify the session state via the store so we don't have
    # to play all 5 gate-qualifying answers through HTTP.
    from state_store import StateStore

    with client.session_transaction() as sess:
        sess["sid"] = "test-unlocked"
    store = StateStore(str(tmp_path / "state.db"))
    s = reducer.new_state("test-unlocked")
    s = replace(s, bonus_unlocked=True)
    store.save(s)
    r = client.get(f"/quiz/{reducer.BONUS_QUIZ_IDS[0]}", follow_redirects=False)
    assert r.status_code == 200, (
        f"/quiz/{reducer.BONUS_QUIZ_IDS[0]} should serve 200 once bonus "
        f"is unlocked; got {r.status_code}"
    )
    body = r.data.decode("utf-8")
    # Bonus chrome: "★ Bonus" badge + "Question k of 2" counter.
    assert "★ Bonus" in body
    assert "Question 1 of 2" in body


def test_chapter_nav_injects_bonus_pip_when_unlocked(client, tmp_path):
    # With bonus_unlocked=True, the context_processor-injected chapter
    # list includes a "Bonus" entry between Quizzes and Result. Pages
    # loaded in that state should render it.
    from state_store import StateStore

    with client.session_transaction() as sess:
        sess["sid"] = "test-nav"
    store = StateStore(str(tmp_path / "state.db"))
    s = replace(reducer.new_state("test-nav"), bonus_unlocked=True)
    store.save(s)
    r = client.get("/learn/1", follow_redirects=False)
    body = r.data.decode("utf-8")
    assert r.status_code == 200
    assert 'data-slug="bonus"' in body, (
        "chapter-nav should contain a bonus pip once bonus_unlocked; "
        "check app.py _inject_chapters context_processor."
    )


def test_chapter_nav_hides_bonus_pip_when_locked(client):
    # Fresh session — bonus pip must NOT appear; leaks the bonus path's
    # existence to a learner who hasn't earned it.
    r = client.get("/learn/1", follow_redirects=False)
    body = r.data.decode("utf-8")
    assert 'data-slug="bonus"' not in body, (
        "chapter-nav should not include a bonus pip when bonus_unlocked=False"
    )


def test_result_route_surfaces_bonus_context_when_reached(client, tmp_path):
    # With at least one bonus answer in state, the result page shows
    # the ★ celebration banner + a per-qid bonus star in the answer list.
    from state_store import StateStore

    with client.session_transaction() as sess:
        sess["sid"] = "test-result"
    store = StateStore(str(tmp_path / "state.db"))
    s = replace(
        reducer.new_state("test-result"),
        bonus_unlocked=True,
        answers=tuple(
            {"qid": str(i), "choice": "a", "correct": True,
             "attempts": 1, "latency_ms": 2000, "first_try_correct": True}
            for i in range(1, 9)
        ) + (
            {"qid": "9", "choice": "b", "correct": True,
             "attempts": 1, "latency_ms": 2000, "first_try_correct": True},
        ),
    )
    store.save(s)
    r = client.get("/result", follow_redirects=False)
    body = r.data.decode("utf-8")
    assert r.status_code == 200
    assert "Bonus round unlocked" in body
    # Per-qid star badge next to the bonus answer.
    assert 'bg-warning text-dark">★' in body


def test_result_route_hides_bonus_celebration_when_not_reached(client, tmp_path):
    # Learner completed main flow only. bonus_reached=False → no banner.
    from state_store import StateStore

    with client.session_transaction() as sess:
        sess["sid"] = "test-no-bonus"
    store = StateStore(str(tmp_path / "state.db"))
    s = replace(
        reducer.new_state("test-no-bonus"),
        answers=tuple(
            {"qid": str(i), "choice": "a", "correct": True,
             "attempts": 1, "latency_ms": 2000, "first_try_correct": True}
            for i in range(1, 9)
        ),
    )
    store.save(s)
    r = client.get("/result", follow_redirects=False)
    body = r.data.decode("utf-8")
    assert r.status_code == 200
    assert "Bonus round unlocked" not in body


def test_bonus_url_guard_skipped_in_static_mode(tmp_path):
    # Static mode (is_static=True) disables the live guard — LocalBackend
    # enforces client-side, and freeze.py must be able to render every
    # bonus page with fresh (not unlocked) state.
    app = create_app(db_path=str(tmp_path / "state.db"), is_static=True)
    app.config.update(TESTING=True, SECRET_KEY="test-secret")
    with app.test_client() as c:
        r = c.get(f"/quiz/{reducer.BONUS_QUIZ_IDS[0]}", follow_redirects=False)
        # 200, not a redirect — guard is skipped in static mode.
        assert r.status_code == 200, (
            f"Static mode must serve bonus HTML so frozen-flask + "
            f"LocalBackend can navigate; got {r.status_code}"
        )
