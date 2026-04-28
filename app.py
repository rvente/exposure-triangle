"""Flask adapter — thin glue between HTTP and the pure reducer."""
from __future__ import annotations

import html
import json
import os
import re
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session
from markupsafe import Markup

import reducer
from state_store import StateStore


_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC = re.compile(r"\*([^*\n]+?)\*")


def markdown_inline(text: str | None) -> Markup:
    """Minimal inline-markdown: **bold** and *italic*. HTML-escapes input."""
    if not text:
        return Markup("")
    escaped = html.escape(text)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    return Markup(escaped)


ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
INSTANCE_DIR = ROOT / "instance"


def load_content() -> tuple[dict, dict, dict]:
    with (DATA_DIR / "lessons.json").open() as f:
        lessons = json.load(f)
    with (DATA_DIR / "quizzes.json").open() as f:
        quizzes = json.load(f)
    with (DATA_DIR / "reference.json").open() as f:
        reference = json.load(f)
    return lessons, quizzes, reference


def answer_key_from(quizzes: dict) -> dict[str, str]:
    return {qid: q["burn_in"]["correct"] for qid, q in quizzes.items()}


def active_content(quiz: dict, variant_slug: str | None) -> dict:
    """Pick the question block the learner actually sees. Burn-in slugs and
    any unknown slug fall back to the burn_in content; a known variant slug
    picks that variant. Variants are expected to match burn_in's shape
    (prompt / options / correct / hint_on_wrong / reveal_on_wrong)."""
    if not variant_slug or variant_slug == "burn_in":
        return quiz["burn_in"]
    variants = quiz.get("variants") or {}
    return variants.get(variant_slug) or quiz["burn_in"]


def now_ms() -> int:
    return int(time.time() * 1000)


CHAPTERS = (
    ("intro", "Intro", "/intro"),
    ("iris", "Iris", "/learn/1"),
    ("duration", "Duration", "/learn/2"),
    ("sensitivity", "Sensitivity", "/learn/4"),
    ("triangle", "Triangle", "/learn/7"),
    ("quizzes", "Quizzes", "/quiz/1"),
    ("result", "Result", "/result"),
    ("reference", "Reference", "/reference"),
)


def create_app(db_path: str | None = None, *, is_static: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = os.environ.get("FLASK_SECRET", secrets.token_urlsafe(16))
    app.jinja_env.filters["markdown_inline"] = markdown_inline
    # Threaded into the Jinja template via `config.IS_STATIC`. The frozen
    # build flips this so window.IS_STATIC = true → LocalBackend kicks in.
    app.config["IS_STATIC"] = is_static
    # Allow both /intro and /intro/ so frozen-flask's directory-style output
    # (intro/index.html) and Flask's normal routing both work without redirect.
    app.url_map.strict_slashes = False

    @app.context_processor
    def _inject_chapters():
        # Base nav for every page. If the learner has unlocked the bonus
        # path, inject a "Bonus" pip between Quizzes and Result so the nav
        # reflects the wider track they're on. Fails silently if no session
        # context (atlas_server renders, freeze.py freezing passes) — those
        # paths always fall back to base CHAPTERS. In static runtime mode
        # the client-side `injectBonusChapterIfUnlocked` in app.js mirrors
        # this by reading LocalBackend state + DOM-patching the nav.
        chapters = list(CHAPTERS)
        try:
            stored_sid = session.get("sid")
            if stored_sid:
                s = store.load(stored_sid)
                if s.bonus_unlocked:
                    qi = next((i for i, c in enumerate(chapters) if c[0] == "quizzes"), None)
                    if qi is not None:
                        bonus_url = f"/quiz/{reducer.BONUS_QUIZ_IDS[0]}"
                        chapters.insert(qi + 1, ("bonus", "Bonus", bonus_url))
        except Exception:
            pass
        return {"chapters": tuple(chapters)}

    if db_path is None:
        INSTANCE_DIR.mkdir(exist_ok=True)
        db_path = str(INSTANCE_DIR / "state.db")
    store = StateStore(db_path)

    lessons, quizzes, reference = load_content()
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
        return redirect(resp.get("redirect", "/intro"))

    def _learn_chapter(n: int) -> str:
        # Lessons 2-3 are the duration showcase + slider; 4-6 are the
        # sensitivity showcase + toggle + compare; 7 is the triangle summary.
        # All sub-pages within a section map back to the section's chapter.
        return {
            1: "iris",
            2: "duration", 3: "duration",
            4: "sensitivity", 5: "sensitivity", 6: "sensitivity",
            7: "triangle",
        }.get(n, "iris")

    @app.route("/intro", methods=["GET", "POST"])
    def intro():
        s = store.load(sid())
        if request.method == "POST":
            s, _ = reducer.reduce(s, {"type": "enter", "page": "learn", "index": 1}, now_ms())
            store.save(s)
            return redirect("/learn/1")
        s, _ = reducer.reduce(s, {"type": "enter", "page": "intro", "index": 0}, now_ms())
        store.save(s)
        return render_template("intro.html", current_chapter="intro", prev_url="/")

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
        prev_url = "/intro" if n == 1 else f"/learn/{n - 1}"
        return render_template(
            "learn.html",
            lesson=lessons[key],
            lesson_n=n,
            total=reducer.NUM_LESSONS,
            current_chapter=_learn_chapter(n),
            prev_url=prev_url,
        )

    @app.route("/quiz/<int:n>", methods=["GET", "POST"])
    def quiz(n: int):
        key = str(n)
        if key not in quizzes:
            return redirect("/")
        s = store.load(sid())
        # Guard: bonus quizzes are only reachable when the gate has
        # cleared. Direct URL access to /quiz/9 without bonus_unlocked
        # bounces back to /result rather than leaking bonus content. Skipped
        # in static mode — the frozen-flask pass renders every page with a
        # fresh state, and LocalBackend enforces the gate client-side.
        if (
            key in reducer.BONUS_QUIZ_IDS
            and not s.bonus_unlocked
            and not app.config.get("IS_STATIC")
        ):
            return redirect("/result")

        is_bonus = key in reducer.BONUS_QUIZ_IDS
        # Previous-page: main-flow q1 → last lesson; main-flow qN → q(N-1);
        # first bonus → last main-flow quiz; later bonus → previous bonus.
        if n == 1:
            prev_url = f"/learn/{reducer.NUM_LESSONS}"
        elif is_bonus and key == reducer.BONUS_QUIZ_IDS[0]:
            prev_url = f"/quiz/{reducer.NUM_QUIZZES}"
        else:
            prev_url = f"/quiz/{n - 1}"

        # Total shown in the header: main-flow count for activate quizzes,
        # bonus count for bonus quizzes. `bonus_index` tells the template
        # this is the k-th bonus question (1-indexed) for the header label.
        if is_bonus:
            total = len(reducer.BONUS_QUIZ_IDS)
            bonus_index = reducer.BONUS_QUIZ_IDS.index(key) + 1
        else:
            total = reducer.NUM_QUIZZES
            bonus_index = 0

        if request.method == "POST":
            action = request.form.get("action", "submit")
            if action == "advance":
                s, resp = reducer.reduce(s, {"type": "advance_quiz"}, now_ms())
                store.save(s)
                return redirect(resp.get("redirect", "/"))
            choice = request.form.get("choice", "")
            # Validate against the currently-selected variant's correct answer,
            # not the burn_in default. The variant was chosen at `enter` time
            # and is stable for the rest of this question.
            variant_slug = s.variant_selections.get(key, "burn_in")
            content = active_content(quizzes[key], variant_slug)
            per_request_key = dict(answer_key)
            per_request_key[key] = content["correct"]
            s, resp = reducer.reduce(
                s,
                {"type": "submit_answer", "qid": key, "choice": choice},
                now_ms(),
                answer_key=per_request_key,
            )
            store.save(s)
            return render_template(
                "quiz.html",
                quiz=quizzes[key],
                content=content,
                quiz_n=n,
                total=total,
                is_bonus=is_bonus,
                bonus_index=bonus_index,
                feedback=resp,
                selected=choice,
                current_chapter=("bonus" if is_bonus else "quizzes"),
                prev_url=prev_url,
                variant_slug=variant_slug,
            )
        s, _ = reducer.reduce(s, {"type": "enter", "page": "quiz", "index": n}, now_ms())
        store.save(s)
        variant_slug = s.variant_selections.get(key, "burn_in")
        content = active_content(quizzes[key], variant_slug)
        return render_template(
            "quiz.html",
            quiz=quizzes[key],
            content=content,
            quiz_n=n,
            total=total,
            is_bonus=is_bonus,
            bonus_index=bonus_index,
            feedback=None,
            selected=None,
            current_chapter="quizzes",
            prev_url=prev_url,
            variant_slug=variant_slug,
        )

    @app.route("/result")
    def result():
        s = store.load(sid())
        score = reducer.compute_score(s)
        # Previous-button target: the last quiz the learner actually
        # completed. If bonus was unlocked + reached, that's the last bonus
        # qid; otherwise it's the last main-flow quiz.
        answered_bonus = [a["qid"] for a in s.answers if a["qid"] in reducer.BONUS_QUIZ_IDS]
        if answered_bonus:
            prev_url = f"/quiz/{answered_bonus[-1]}"
        else:
            prev_url = f"/quiz/{reducer.NUM_QUIZZES}"
        # Bonus celebration context — the template guards on bonus_reached
        # so the banner only fires when the learner actually walked into
        # bonus. first_try_in_window reports their performance on the
        # exact 5-answer window the gate judged, so the banner tells them
        # WHY they earned the unlock.
        bonus_window = s.answers[: reducer.BONUS_GATE_WINDOW]
        first_try_in_window = sum(1 for a in bonus_window if a.get("first_try_correct"))
        # Per-question review (TA feedback): expose the actual prompt, the
        # option text the learner chose, the option text that was correct,
        # and the reveal-on-wrong rationale. Variant slug picks the same
        # block the learner saw at answer time.
        per_q = []
        for ans in s.answers:
            qid = ans["qid"]
            quiz = quizzes.get(qid, {})
            block = active_content(quiz, s.variant_selections.get(qid))
            opts_by_id = {o.get("id"): o.get("text", "") for o in block.get("options", [])}
            per_q.append({
                "qid": qid,
                "category": quiz.get("category", ""),
                "prompt": block.get("prompt", ""),
                "chosen_id": ans.get("choice", ""),
                "chosen_text": opts_by_id.get(ans.get("choice", ""), "(no choice)"),
                "correct_id": block.get("correct", ""),
                "correct_text": opts_by_id.get(block.get("correct", ""), ""),
                "is_correct": ans.get("correct", False),
                "attempts": ans.get("attempts", 0),
                "latency_ms": ans.get("latency_ms", 0),
                "first_try_correct": ans.get("first_try_correct", False),
                "why": block.get("reveal_on_wrong", ""),
            })
        return render_template(
            "result.html",
            score=score,
            per_q=per_q,
            quizzes_json=quizzes,
            current_chapter="result",
            prev_url=prev_url,
            bonus_reached=len(answered_bonus) > 0,
            first_try_in_window=first_try_in_window,
            bonus_gate_window=reducer.BONUS_GATE_WINDOW,
            bonus_gate_threshold=reducer.BONUS_GATE_MIN_FIRST_TRY,
            bonus_quiz_count=len(reducer.BONUS_QUIZ_IDS),
            bonus_qids=reducer.BONUS_QUIZ_IDS,
        )

    @app.route("/reference")
    def reference_card():
        return render_template(
            "reference.html",
            ref=reference,
            current_chapter="reference",
            prev_url="/result",
        )

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
