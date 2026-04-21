"""Pure state-transition function for the Exposure Triangle app.

No I/O, no time.time(), no imports from Flask or SQLite. The caller injects
now_ms and any content the reducer needs (quiz answer key).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

NUM_LESSONS = 3
NUM_QUIZZES = 5


@dataclass(frozen=True)
class State:
    session_id: str
    page: str = "home"
    page_index: int = 0
    page_entry_time_ms: int = 0
    answers: tuple = ()
    attempts: dict = field(default_factory=dict)
    latency_ms: dict = field(default_factory=dict)
    first_try_correct: dict = field(default_factory=dict)


def new_state(session_id: str) -> State:
    return State(session_id=session_id)


def reduce(state: State, event: dict, now_ms: int, *, answer_key: dict[str, str] | None = None) -> tuple[State, dict]:
    """Return (new_state, response_payload).

    Events:
      - {"type": "start"}
      - {"type": "enter", "page": "learn"|"quiz"|"result", "index": int}
      - {"type": "advance_learn"}
      - {"type": "submit_answer", "qid": str, "choice": str}
    """
    et = event.get("type")

    if et == "start":
        ns = replace(state, page="learn", page_index=1, page_entry_time_ms=now_ms)
        return ns, {"redirect": "/learn/1"}

    if et == "enter":
        page = event["page"]
        idx = int(event.get("index", 0))
        ns = replace(state, page=page, page_index=idx, page_entry_time_ms=now_ms)
        return ns, {}

    if et == "advance_learn":
        idx = state.page_index
        if idx < NUM_LESSONS:
            nxt = idx + 1
            ns = replace(state, page="learn", page_index=nxt, page_entry_time_ms=now_ms)
            return ns, {"redirect": f"/learn/{nxt}"}
        ns = replace(state, page="quiz", page_index=1, page_entry_time_ms=now_ms)
        return ns, {"redirect": "/quiz/1"}

    if et == "submit_answer":
        if answer_key is None:
            raise ValueError("submit_answer requires answer_key")
        qid = str(event["qid"])
        choice = event["choice"]
        correct = answer_key.get(qid)
        is_correct = choice == correct

        prior_attempts = state.attempts.get(qid, 0)
        new_attempts = dict(state.attempts)
        new_attempts[qid] = prior_attempts + 1

        latency_ms = dict(state.latency_ms)
        first_try = dict(state.first_try_correct)
        if prior_attempts == 0:
            latency_ms[qid] = max(0, now_ms - state.page_entry_time_ms)
            first_try[qid] = is_correct

        # Second-chance mechanic: first wrong stays on page (not locked).
        # Correct or second wrong locks and records an answer.
        locked = is_correct or prior_attempts >= 1
        answers = state.answers
        if locked:
            answers = answers + (
                {
                    "qid": qid,
                    "choice": choice,
                    "correct": is_correct,
                    "attempts": prior_attempts + 1,
                    "latency_ms": latency_ms.get(qid, 0),
                    "first_try_correct": first_try.get(qid, False),
                },
            )

        ns = replace(
            state,
            answers=answers,
            attempts=new_attempts,
            latency_ms=latency_ms,
            first_try_correct=first_try,
        )

        response = {
            "correct": is_correct,
            "locked": locked,
            "attempt": prior_attempts + 1,
            "correct_choice": correct if locked else None,
        }
        return ns, response

    if et == "advance_quiz":
        idx = state.page_index
        if idx < NUM_QUIZZES:
            nxt = idx + 1
            ns = replace(state, page="quiz", page_index=nxt, page_entry_time_ms=now_ms)
            return ns, {"redirect": f"/quiz/{nxt}"}
        ns = replace(state, page="result", page_index=0, page_entry_time_ms=now_ms)
        return ns, {"redirect": "/result"}

    return state, {}


def compute_score(state: State) -> dict[str, Any]:
    total = NUM_QUIZZES
    correct = sum(1 for a in state.answers if a["correct"])
    first_try = sum(1 for a in state.answers if a.get("first_try_correct"))
    return {
        "correct": correct,
        "total": total,
        "first_try": first_try,
        "answers": list(state.answers),
    }
