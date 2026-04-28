"""Compile-time validation of the frozen-flask static build.

Builds _static_build/ via freeze.py and asserts that:
  - Every flow page lands at the expected directory/index.html.
  - Each page sets window.IS_STATIC = true.
  - Each page loads reducer.js + backend.js + app.js in order.
  - The home page Start form is tagged for the static intercept.
  - The quiz template carries the data-* attrs the JS feedback path needs.
  - All photo renders the lessons reference are present under static/renders/.

Catches drift between the live Flask templates and the frozen artifact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import freeze  # noqa: E402


def _build_once():
    paths = freeze.build()
    return freeze.DESTINATION, paths


def test_all_flow_pages_emitted(tmp_path_factory):
    dest, _ = _build_once()
    # Full flow: intro + 7 lessons + 8 main-flow quizzes + 2 bonus quizzes +
    # result + reference. Bonus pages are always emitted even though the
    # runtime route guards them — LocalBackend unlocks bonus client-side and
    # needs the HTML on disk.
    expected = [
        "index.html",
        "intro/index.html",
    ]
    expected += [f"learn/{n}/index.html" for n in range(1, 8)]
    expected += [f"quiz/{n}/index.html" for n in range(1, 9)]
    expected += ["quiz/9/index.html", "quiz/10/index.html"]
    expected += ["result/index.html", "reference/index.html"]
    for rel in expected:
        assert (dest / rel).exists(), f"missing frozen page: {rel}"


def test_is_static_flag_set_in_every_flow_page():
    dest, _ = _build_once()
    flow = ["index.html", "intro/index.html", "learn/1/index.html",
            "quiz/1/index.html", "result/index.html", "reference/index.html"]
    for rel in flow:
        html = (dest / rel).read_text()
        assert "window.IS_STATIC = true;" in html, f"{rel} missing IS_STATIC=true"


def test_js_bundle_loaded_in_order():
    dest, _ = _build_once()
    html = (dest / "learn" / "1" / "index.html").read_text()
    pos_reducer = html.find("js/reducer.js")
    pos_backend = html.find("js/backend.js")
    pos_app = html.find("js/app.js")
    assert pos_reducer != -1 and pos_backend != -1 and pos_app != -1
    assert pos_reducer < pos_backend < pos_app, (
        "reducer.js must load before backend.js (which references window.Reducer), "
        "and backend.js before app.js (which references window.backend)."
    )


def test_static_action_attrs_present():
    dest, _ = _build_once()
    home = (dest / "index.html").read_text()
    assert 'data-static-action="start"' in home

    intro = (dest / "intro" / "index.html").read_text()
    assert 'data-static-action="intro_advance"' in intro

    learn1 = (dest / "learn" / "1" / "index.html").read_text()
    assert 'data-static-action="learn_advance"' in learn1

    quiz1 = (dest / "quiz" / "1" / "index.html").read_text()
    assert 'data-static-action="quiz_submit"' in quiz1
    # Quiz form carries the strings JS needs to render feedback client-side.
    for attr in ("data-correct-choice=", "data-msg-correct=", "data-msg-hint=", "data-msg-reveal="):
        assert attr in quiz1, f"quiz/1 missing {attr}"


def test_renders_copied_for_every_lesson_image():
    dest, _ = _build_once()
    lessons = json.loads((ROOT / "data" / "lessons.json").read_text())
    expected: set[str] = set()
    for lesson in lessons.values():
        for key in ("slider", "toggle", "showcase"):
            section = lesson.get(key)
            if not section:
                continue
            for frame in section.get("frames", []) + section.get("images", []):
                expected.add(frame["src"])
        cmp = lesson.get("comparison")
        if cmp:
            expected.add(cmp["base"])
            expected.add(cmp["overlay"])
    for src in expected:
        assert (dest / "static" / src).exists(), f"frozen build missing static/{src}"


def test_local_backend_present_and_flask_backend_skipped_at_runtime():
    """The frozen JS bundle must contain both backends; runtime decides which.

    backend.js does `window.backend = window.IS_STATIC ? new LocalBackend() : new FlaskBackend()`,
    so the file is the same in both modes — only the constant differs.
    """
    dest, _ = _build_once()
    backend_js = (dest / "static" / "js" / "backend.js").read_text()
    assert "class LocalBackend" in backend_js
    assert "class FlaskBackend" in backend_js
    assert "window.IS_STATIC ? new LocalBackend()" in backend_js


def test_static_url_helper_climbs_full_depth():
    """Regression for the off-by-one in staticUrl().

    Earlier the function did `depth - 1` ups, so a "/static/x" hop from
    /learn/2/ resolved to /learn/static/x and 404'd. Lock in the fixed
    formula: one "../" per non-empty path segment.
    """
    dest, _ = _build_once()
    js = (dest / "static" / "js" / "app.js").read_text()
    assert "function staticUrl(" in js
    # Forbid the buggy form.
    assert "depth - 1" not in js, (
        "staticUrl regressed: 'depth - 1' produces too few '../' hops, "
        "breaking image swaps under nested routes (/learn/N, /quiz/N)."
    )
    # The fix uses .filter(Boolean).length as the number of ups.
    assert ".filter(Boolean)" in js
