"""Flask adapter — thin glue between HTTP and the pure reducer."""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session

import reducer
from state_store import StateStore


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INSTANCE_DIR = ROOT / "instance"


def load_content() -> tuple[dict, dict]:
    with (DATA_DIR / "lessons.json").open() as f:
        lessons = json.load(f)
    with (DATA_DIR / "quizzes.json").open() as f:
        quizzes = json.load(f)
    return lessons, quizzes


def answer_key_from(quizzes: dict) -> dict[str, str]:
    return {qid: q["burn_in"]["correct"] for qid, q in quizzes.items()}


def now_ms() -> int:
    return int(time.time() * 1000)


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_urlsafe(16))

    if db_path is None:
        INSTANCE_DIR.mkdir(exist_ok=True)
        db_path = str(INSTANCE_DIR / "state.db")
    store = StateStore(db_path)

    lessons, quizzes = load_content()
    answer_key = answer_key_from(quizzes)

    def sid() -> str:
        if "sid" not in session:
            session["sid"] = secrets.token_urlsafe(16)
        return session["sid"]

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/start", methods=["POST"])
    def start():
        s = reducer.new_state(sid())
        s, resp = reducer.reduce(s, {"type": "start"}, now_ms())
        store.save(s)
        return redirect(resp.get("redirect", "/learn/1"))

    @app.route("/learn/<int:n>", methods=["GET", "POST"])
    def learn(n: int):
        key = str(n)
        if key not in lessons:
            return redirect("/")
        s = store.load(sid())
        if request.method == "POST":
            s, resp = reducer.reduce(s, {"type": "advance_learn"}, now_ms())
            store.save(s)
            return redirect(resp.get("redirect", "/"))
        s, _ = reducer.reduce(s, {"type": "enter", "page": "learn", "index": n}, now_ms())
        store.save(s)
        return render_template("learn.html", lesson=lessons[key], lesson_n=n, total=reducer.NUM_LESSONS)

    @app.route("/quiz/<int:n>", methods=["GET", "POST"])
    def quiz(n: int):
        key = str(n)
        if key not in quizzes:
            return redirect("/")
        s = store.load(sid())
        if request.method == "POST":
            action = request.form.get("action", "submit")
            if action == "advance":
                s, resp = reducer.reduce(s, {"type": "advance_quiz"}, now_ms())
                store.save(s)
                return redirect(resp.get("redirect", "/"))
            choice = request.form.get("choice", "")
            s, resp = reducer.reduce(
                s,
                {"type": "submit_answer", "qid": key, "choice": choice},
                now_ms(),
                answer_key=answer_key,
            )
            store.save(s)
            return render_template(
                "quiz.html",
                quiz=quizzes[key],
                quiz_n=n,
                total=reducer.NUM_QUIZZES,
                feedback=resp,
                selected=choice,
            )
        s, _ = reducer.reduce(s, {"type": "enter", "page": "quiz", "index": n}, now_ms())
        store.save(s)
        return render_template(
            "quiz.html",
            quiz=quizzes[key],
            quiz_n=n,
            total=reducer.NUM_QUIZZES,
            feedback=None,
            selected=None,
        )

    @app.route("/result")
    def result():
        s = store.load(sid())
        score = reducer.compute_score(s)
        return render_template("result.html", score=score)

    @app.route("/api/state")
    def api_state():
        s = store.load(sid())
        return jsonify(
            {
                "session_id": s.session_id,
                "page": s.page,
                "page_index": s.page_index,
                "answers": list(s.answers),
            }
        )

    @app.route("/api/event", methods=["POST"])
    def api_event():
        event = request.get_json(silent=True) or {}
        s = store.load(sid())
        s, resp = reducer.reduce(s, event, now_ms(), answer_key=answer_key)
        store.save(s)
        return jsonify(resp)

    @app.route("/api/reset", methods=["POST"])
    def api_reset():
        store.clear(sid())
        session.clear()
        return jsonify({"ok": True})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
