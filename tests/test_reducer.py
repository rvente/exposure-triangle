import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reducer import (
    NUM_LESSONS,
    NUM_QUIZZES,
    compute_score,
    new_state,
    reduce,
)


ANSWER_KEY = {"1": "a", "2": "b", "3": "c", "4": "a", "5": "b"}


def test_start_redirects_to_first_lesson():
    s = new_state("sid")
    s2, resp = reduce(s, {"type": "start"}, 1000)
    assert s2.page == "learn"
    assert s2.page_index == 1
    assert s2.page_entry_time_ms == 1000
    assert resp["redirect"] == "/learn/1"


def test_advance_learn_walks_lessons_then_quiz():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "start"}, 0)
    for i in range(1, NUM_LESSONS):
        s, resp = reduce(s, {"type": "advance_learn"}, 1000 * i)
        assert resp["redirect"] == f"/learn/{i + 1}"
    s, resp = reduce(s, {"type": "advance_learn"}, 9999)
    assert resp["redirect"] == "/quiz/1"
    assert s.page == "quiz" and s.page_index == 1


def test_correct_first_try_locks_and_records():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 5000)
    s, resp = reduce(
        s,
        {"type": "submit_answer", "qid": "1", "choice": "a"},
        7000,
        answer_key=ANSWER_KEY,
    )
    assert resp["correct"] is True
    assert resp["locked"] is True
    assert resp["correct_choice"] == "a"
    assert s.first_try_correct["1"] is True
    assert s.latency_ms["1"] == 2000
    assert len(s.answers) == 1


def test_second_chance_first_wrong_does_not_lock():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, resp = reduce(
        s,
        {"type": "submit_answer", "qid": "1", "choice": "b"},
        1000,
        answer_key=ANSWER_KEY,
    )
    assert resp["correct"] is False
    assert resp["locked"] is False
    assert resp["correct_choice"] is None
    assert s.first_try_correct["1"] is False
    assert len(s.answers) == 0
    assert s.attempts["1"] == 1


def test_second_chance_second_wrong_locks_and_reveals():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 500, answer_key=ANSWER_KEY)
    s, resp = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "c"}, 1000, answer_key=ANSWER_KEY)
    assert resp["correct"] is False
    assert resp["locked"] is True
    assert resp["correct_choice"] == "a"
    assert len(s.answers) == 1
    assert s.answers[0]["attempts"] == 2
    assert s.answers[0]["first_try_correct"] is False


def test_second_chance_second_attempt_correct_locks_records_not_first_try():
    s = new_state("sid")
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 1}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "b"}, 500, answer_key=ANSWER_KEY)
    s, resp = reduce(s, {"type": "submit_answer", "qid": "1", "choice": "a"}, 1200, answer_key=ANSWER_KEY)
    assert resp["correct"] is True
    assert resp["locked"] is True
    assert s.answers[0]["correct"] is True
    assert s.answers[0]["first_try_correct"] is False
    assert s.answers[0]["attempts"] == 2


def test_advance_quiz_walks_through_to_result():
    s = new_state("sid")
    for n in range(1, NUM_QUIZZES):
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": n}, 0)
        s, _ = reduce(
            s,
            {"type": "submit_answer", "qid": str(n), "choice": ANSWER_KEY[str(n)]},
            100,
            answer_key=ANSWER_KEY,
        )
        s, resp = reduce(s, {"type": "advance_quiz"}, 200)
        assert resp["redirect"] == f"/quiz/{n + 1}"
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": NUM_QUIZZES}, 0)
    s, _ = reduce(
        s,
        {"type": "submit_answer", "qid": str(NUM_QUIZZES), "choice": ANSWER_KEY[str(NUM_QUIZZES)]},
        100,
        answer_key=ANSWER_KEY,
    )
    s, resp = reduce(s, {"type": "advance_quiz"}, 200)
    assert resp["redirect"] == "/result"
    assert s.page == "result"


def test_compute_score_counts_correct_and_first_try():
    s = new_state("sid")
    # 3 correct on first try, 1 correct on second, 1 wrong locked
    for qid in ("1", "2", "3"):
        s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": int(qid)}, 0)
        s, _ = reduce(s, {"type": "submit_answer", "qid": qid, "choice": ANSWER_KEY[qid]}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 4}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "4", "choice": "b"}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "4", "choice": "a"}, 200, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "enter", "page": "quiz", "index": 5}, 0)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "5", "choice": "a"}, 100, answer_key=ANSWER_KEY)
    s, _ = reduce(s, {"type": "submit_answer", "qid": "5", "choice": "a"}, 200, answer_key=ANSWER_KEY)
    score = compute_score(s)
    assert score["total"] == NUM_QUIZZES
    assert score["correct"] == 4
    assert score["first_try"] == 3
