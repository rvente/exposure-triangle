"""Atlas server — inspection harness for every meaningfully-unique UI state.

Not part of the assignment runtime. Wraps the real Flask app and mounts an
/_atlas/ index plus per-frame routes that render synthetic states without
touching the session or SQLite.

Run:
    uv run python tests/atlas_server.py
    → open http://127.0.0.1:5001/_atlas/

Coverage mirrors hw9_rv2459/capture_states.py: every slider stop, every
toggle position, every quiz button's post-click feedback.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from flask import render_template  # noqa: E402

from app import create_app  # noqa: E402


DATA = ROOT / "data"
LESSONS = json.loads((DATA / "lessons.json").read_text())
QUIZZES = json.loads((DATA / "quizzes.json").read_text())
REFERENCE = json.loads((DATA / "reference.json").read_text())


_LEARN_CHAPTER = {
    1: "iris",
    2: "duration", 3: "duration",
    4: "sensitivity", 5: "sensitivity", 6: "sensitivity",
    7: "triangle",
}


def _learn_extras(n: int) -> dict:
    return {
        "current_chapter": _LEARN_CHAPTER.get(n, "iris"),
        "prev_url": "/intro" if n == 1 else f"/learn/{n - 1}",
    }


def _quiz_extras(n: int) -> dict:
    return {
        "current_chapter": "quizzes",
        "prev_url": "/learn/4" if n == 1 else f"/quiz/{n - 1}",
    }


def _quiz_fresh(n: int):
    return render_template(
        "quiz.html",
        quiz=QUIZZES[str(n)],
        quiz_n=n,
        total=len(QUIZZES),
        feedback=None,
        selected=None,
        **_quiz_extras(n),
    )


def _quiz_feedback(n: int, *, correct: bool, locked: bool, attempt: int, selected: str):
    q = QUIZZES[str(n)]
    return render_template(
        "quiz.html",
        quiz=q,
        quiz_n=n,
        total=len(QUIZZES),
        feedback={
            "correct": correct,
            "locked": locked,
            "attempt": attempt,
            "correct_choice": q["burn_in"]["correct"] if locked else None,
        },
        selected=selected,
        **_quiz_extras(n),
    )


def _lesson_with_slider_index(n: int, idx: int):
    lesson = copy.deepcopy(LESSONS[str(n)])
    lesson["slider"]["default_index"] = idx
    return render_template("learn.html", lesson=lesson, lesson_n=n, total=len(LESSONS), **_learn_extras(n))


def _lesson_with_toggle_index(n: int, idx: int):
    lesson = copy.deepcopy(LESSONS[str(n)])
    lesson["toggle"]["default_index"] = idx
    # Don't render the comparison viewer on toggle-only frames — clarifies
    # which interactive element the frame is demonstrating.
    lesson.pop("comparison", None)
    return render_template("learn.html", lesson=lesson, lesson_n=n, total=len(LESSONS), **_learn_extras(n))


def _lesson_with_compare_pct(n: int, pct: int):
    lesson = copy.deepcopy(LESSONS[str(n)])
    # Drop the toggle so the compare viewer is the headline element.
    lesson.pop("toggle", None)
    return render_template(
        "learn.html",
        lesson=lesson,
        lesson_n=n,
        total=len(LESSONS),
        compare_initial_pct=pct,
        **_learn_extras(n),
    )


def _score(answers: list[dict]):
    return {
        "correct": sum(1 for a in answers if a["correct"]),
        "total": len(QUIZZES),
        "first_try": sum(1 for a in answers if a.get("first_try_correct")),
        "answers": answers,
    }


def _make_answer(qid: str, *, correct: bool, first_try: bool, attempts: int, latency_ms: int):
    q = QUIZZES[qid]["burn_in"]
    choice = q["correct"] if correct else next(o["id"] for o in q["options"] if o["id"] != q["correct"])
    return {
        "qid": qid,
        "choice": choice,
        "correct": correct,
        "attempts": attempts,
        "latency_ms": latency_ms,
        "first_try_correct": first_try and correct,
    }


def _frame_catalog():
    cat: list[tuple[str, str, str, callable]] = []

    # ── Static pages ────────────────────────────────────────────────────
    cat.append(("home", "Home — bucket intro + start", "s0 port: bucket-metaphor intro, three-icon row, Start button, attribution.", lambda: render_template("home.html")))
    cat.append(("intro", "Intro — Press the Shutter", "s-drama port: one-breath narrative + 'Why this page is dark' sidebar.", lambda: render_template("intro.html", current_chapter="intro", prev_url="/")))

    # ── Lesson 1: iris slider, all 9 stops ──────────────────────────────
    iris_frames = LESSONS["1"]["slider"]["frames"]
    for i, frame in enumerate(iris_frames):
        cat.append((
            f"learn-1-iris-{i}",
            f"Lesson 1 — iris stop {i} ({frame['label'].split(' — ')[0]})",
            frame["label"],
            lambda i=i: _lesson_with_slider_index(1, i),
        ))

    # ── Lesson 2: duration teaching (showcase only) ─────────────────────
    cat.append((
        "learn-2-duration-teaching",
        "Lesson 2 — duration teaching showcase",
        "Pre-interactive 3-image showcase + body copy for Capture Duration.",
        lambda: render_template("learn.html", lesson=LESSONS["2"], lesson_n=2, total=len(LESSONS), **_learn_extras(2)),
    ))

    # ── Lesson 3: duration slider, all 8 stops ──────────────────────────
    dur_frames = LESSONS["3"]["slider"]["frames"]
    for i, frame in enumerate(dur_frames):
        cat.append((
            f"learn-3-duration-{i}",
            f"Lesson 3 — duration stop {i} ({frame['label'].split(' — ')[0]})",
            frame["label"],
            lambda i=i: _lesson_with_slider_index(3, i),
        ))

    # ── Lesson 4: sensitivity teaching (showcase only) ──────────────────
    cat.append((
        "learn-4-sensitivity-teaching",
        "Lesson 4 — sensitivity teaching showcase",
        "Pre-interactive 2-image showcase + body copy for Sensor Sensitivity.",
        lambda: render_template("learn.html", lesson=LESSONS["4"], lesson_n=4, total=len(LESSONS), **_learn_extras(4)),
    ))

    # ── Lesson 5: ISO toggle (interactive only) ─────────────────────────
    iso_frames = LESSONS["5"]["toggle"]["frames"]
    for i, frame in enumerate(iso_frames):
        cat.append((
            f"learn-5-iso-{i}",
            f"Lesson 5 — ISO {frame['button']}",
            frame["label"],
            lambda i=i: _lesson_with_toggle_index(5, i),
        ))

    # ── Lesson 6: ISO A/B comparison divider ────────────────────────────
    for pct in (25, 50, 75):
        cat.append((
            f"learn-6-compare-{pct}",
            f"Lesson 6 — compare divider at {pct}%",
            f"ISO A/B comparison slider, divider positioned at {pct}%.",
            lambda pct=pct: _lesson_with_compare_pct(6, pct),
        ))

    # ── Lesson 7: triangle summary (static) ─────────────────────────────
    cat.append((
        "learn-7-summary",
        "Lesson 7 — triangle summary",
        "Bucket-row consolidation of all three controls with side-effect annotations.",
        lambda: render_template("learn.html", lesson=LESSONS["7"], lesson_n=7, total=len(LESSONS), **_learn_extras(7)),
    ))

    # ── Quiz 1: full second-chance matrix ───────────────────────────────
    q1 = QUIZZES["1"]["burn_in"]
    q1_correct = q1["correct"]
    q1_wrong = next(o["id"] for o in q1["options"] if o["id"] != q1_correct)
    cat.append((
        "quiz-1-fresh",
        "Quiz 1 — fresh",
        "Options interactive, no feedback yet.",
        lambda: _quiz_fresh(1),
    ))
    cat.append((
        "quiz-1-wrong-retry",
        "Quiz 1 — first wrong (retry allowed)",
        "Clicked option disabled-gray, amber hint, group still interactive.",
        lambda: _quiz_feedback(1, correct=False, locked=False, attempt=1, selected=q1_wrong),
    ))
    cat.append((
        "quiz-1-wrong-locked",
        "Quiz 1 — second wrong (locked, reveal)",
        "Chosen option red, correct highlighted, group locked, Advance visible.",
        lambda: _quiz_feedback(1, correct=False, locked=True, attempt=2, selected=q1_wrong),
    ))
    cat.append((
        "quiz-1-correct-first",
        "Quiz 1 — correct first try",
        "Green lock, Advance visible.",
        lambda: _quiz_feedback(1, correct=True, locked=True, attempt=1, selected=q1_correct),
    ))
    cat.append((
        "quiz-1-correct-second",
        "Quiz 1 — correct second try",
        "First wrong still gray; correct option green on attempt 2.",
        lambda: _quiz_feedback(1, correct=True, locked=True, attempt=2, selected=q1_correct),
    ))

    # ── Quiz 2–8 (main flow): fresh + one feedback per option (locked) ──
    for n in range(2, 9):
        q = QUIZZES[str(n)]["burn_in"]
        cat.append((
            f"quiz-{n}-fresh",
            f"Quiz {n} — fresh",
            "Options interactive.",
            lambda n=n: _quiz_fresh(n),
        ))
        for opt in q["options"]:
            is_correct = opt["id"] == q["correct"]
            suffix = "correct" if is_correct else f"wrong-{opt['id']}"
            cat.append((
                f"quiz-{n}-feedback-{suffix}",
                f"Quiz {n} — option {opt['id']} clicked (locked {'correct' if is_correct else 'wrong'})",
                f"Locked state showing option {opt['id']} feedback.",
                lambda n=n, opt_id=opt["id"], is_correct=is_correct: _quiz_feedback(
                    n, correct=is_correct, locked=True, attempt=1 if is_correct else 2, selected=opt_id,
                ),
            ))

    # ── Variant coverage: render the low/medium/high of every post-burn-in
    # question that has variants. Visual diff-ability for content edits. ─
    for qid in ("4", "5", "6", "7", "8", "9", "10"):
        quiz = QUIZZES[qid]
        variants = quiz.get("variants") or {}
        for slug, variant in variants.items():
            cat.append((
                f"quiz-{qid}-variant-{slug}",
                f"Quiz {qid} — variant '{slug}'",
                f"{slug.title()}-bucket content rendered fresh.",
                lambda qid=qid, variant=variant: render_template(
                    "quiz.html",
                    quiz=QUIZZES[qid],
                    content=variant,
                    quiz_n=int(qid),
                    total=8 if qid not in ("9", "10") else 2,
                    is_bonus=qid in ("9", "10"),
                    bonus_index=(1 if qid == "9" else (2 if qid == "10" else 0)),
                    feedback=None,
                    selected=None,
                    **_quiz_extras(int(qid)),
                ),
            ))

    # ── Bonus quizzes 9 + 10: fresh + one feedback each (burn_in content)
    for qid in ("9", "10"):
        q = QUIZZES[qid]["burn_in"]
        n = int(qid)
        bonus_index = 1 if qid == "9" else 2
        cat.append((
            f"quiz-{qid}-bonus-fresh",
            f"Quiz {qid} — bonus fresh (★ banner + bonus counter)",
            "Fresh bonus question, first-bonus announcement visible on q9.",
            lambda qid=qid, n=n, bonus_index=bonus_index: render_template(
                "quiz.html",
                quiz=QUIZZES[qid],
                content=QUIZZES[qid]["burn_in"],
                quiz_n=n,
                total=2,
                is_bonus=True,
                bonus_index=bonus_index,
                feedback=None,
                selected=None,
                **_quiz_extras(n),
            ),
        ))
        cat.append((
            f"quiz-{qid}-bonus-correct",
            f"Quiz {qid} — bonus locked correct",
            "Bonus state with the correct answer green-locked + Advance visible.",
            lambda qid=qid, n=n, bonus_index=bonus_index, q=q: render_template(
                "quiz.html",
                quiz=QUIZZES[qid],
                content=QUIZZES[qid]["burn_in"],
                quiz_n=n,
                total=2,
                is_bonus=True,
                bonus_index=bonus_index,
                feedback={"correct": True, "locked": True, "attempt": 1,
                          "correct_choice": q["correct"]},
                selected=q["correct"],
                **_quiz_extras(n),
            ),
        ))

    # ── Results ─────────────────────────────────────────────────────────
    cat.append((
        "result-full",
        "Result — 5 / 5, all first-try",
        "Perfect-run score summary.",
        lambda: render_template("result.html", current_chapter="result", prev_url="/quiz/5", score=_score([
            _make_answer("1", correct=True, first_try=True, attempts=1, latency_ms=3200),
            _make_answer("2", correct=True, first_try=True, attempts=1, latency_ms=2800),
            _make_answer("3", correct=True, first_try=True, attempts=1, latency_ms=2100),
            _make_answer("4", correct=True, first_try=True, attempts=1, latency_ms=4100),
            _make_answer("5", correct=True, first_try=True, attempts=1, latency_ms=3500),
        ])),
    ))
    cat.append((
        "result-mixed",
        "Result — 3 / 5, mixed",
        "Two wrong on second attempt, one correct on second, two first-try correct.",
        lambda: render_template("result.html", current_chapter="result", prev_url="/quiz/5", score=_score([
            _make_answer("1", correct=True, first_try=True, attempts=1, latency_ms=3000),
            _make_answer("2", correct=False, first_try=False, attempts=2, latency_ms=9000),
            _make_answer("3", correct=True, first_try=False, attempts=2, latency_ms=14000),
            _make_answer("4", correct=True, first_try=True, attempts=1, latency_ms=4500),
            _make_answer("5", correct=False, first_try=False, attempts=2, latency_ms=18000),
        ])),
    ))
    cat.append((
        "result-zero",
        "Result — 0 / 5",
        "Every answer locked wrong.",
        lambda: render_template("result.html", current_chapter="result", prev_url="/quiz/5", score=_score([
            _make_answer(str(n), correct=False, first_try=False, attempts=2, latency_ms=12000 + n * 500)
            for n in range(1, 6)
        ])),
    ))
    cat.append((
        "result-bonus-reached",
        "Result — 10 / 10 with bonus celebration",
        "Perfect run through main + bonus; ★ banner + per-qid stars on 9 and 10.",
        lambda: render_template(
            "result.html",
            current_chapter="result",
            prev_url="/quiz/10",
            score=_score([
                _make_answer(str(n), correct=True, first_try=True, attempts=1, latency_ms=3000 + n * 100)
                for n in range(1, 9)
            ] + [
                _make_answer("9", correct=True, first_try=True, attempts=1, latency_ms=4200),
                _make_answer("10", correct=True, first_try=True, attempts=1, latency_ms=5100),
            ]),
            bonus_reached=True,
            first_try_in_window=5,
            bonus_gate_window=5,
            bonus_gate_threshold=4,
            bonus_quiz_count=2,
            bonus_qids=("9", "10"),
        ),
    ))

    # ── Reference ───────────────────────────────────────────────────────
    cat.append(("reference", "Reference card", "Post-quiz cheat sheet with motion-blur vocabulary bridge.", lambda: render_template("reference.html", ref=REFERENCE, current_chapter="reference", prev_url="/result")))

    return cat


def build_app():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="atlas-")
    app = create_app(db_path=str(Path(tmp) / "atlas.db"))
    catalog = _frame_catalog()

    @app.route("/_atlas/")
    def atlas_index():
        return render_template("atlas_index.html", frames=[(n, t, d) for n, t, d, _ in catalog])

    @app.route("/_atlas/frame/<name>")
    def atlas_frame(name):
        for n, _t, _d, builder in catalog:
            if n == name:
                return builder()
        return ("Unknown frame: " + name, 404)

    return app


if __name__ == "__main__":
    app = build_app()
    app.run(host="127.0.0.1", port=5001, debug=False)
