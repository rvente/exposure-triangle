"""End-to-end click-through under Playwright.

Spawns the Flask app on a background thread, walks /, /learn/1..3, /quiz/1..5,
verifies the second-chance mechanic on one quiz, and asserts the final score.

Run under Xvfb on headless Linux:
    xvfb-run -a uv run pytest tests/test_e2e.py
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    port = _free_port()
    db = tmp_path_factory.mktemp("data") / "state.db"
    app = create_app(db_path=str(db))
    app.config.update(TESTING=True)

    def run():
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # Wait for port to open
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError("Flask server did not start in time")

    yield f"http://127.0.0.1:{port}"


def _answer_keys() -> dict[str, str]:
    quizzes = json.loads((ROOT / "data" / "quizzes.json").read_text())
    return {qid: q["burn_in"]["correct"] for qid, q in quizzes.items()}


def _wrong_choice(correct: str, options: list[str]) -> str:
    for o in options:
        if o != correct:
            return o
    return correct


def test_full_click_through(live_server):
    from playwright.sync_api import sync_playwright

    key = _answer_keys()
    quizzes = json.loads((ROOT / "data" / "quizzes.json").read_text())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.goto(live_server + "/", wait_until="domcontentloaded")
        page.locator("#start-btn").click()
        page.wait_for_url("**/learn/1")

        # Three lessons
        for n in range(1, 4):
            assert f"/learn/{n}" in page.url
            page.locator("#advance-btn").click()

        # Quiz 1: test second-chance mechanic — wrong first, then correct
        page.wait_for_url("**/quiz/1")
        opts = [o["id"] for o in quizzes["1"]["burn_in"]["options"]]
        wrong = _wrong_choice(key["1"], opts)
        page.locator(f'.quiz-option[data-opt-id="{wrong}"]').click()
        # Page re-renders with retry still allowed (advance button absent)
        assert page.locator("#advance-btn").count() == 0
        # Now click the correct answer
        page.locator(f'.quiz-option[data-opt-id="{key["1"]}"]').click()
        page.locator("#advance-btn").click()

        # Quizzes 2..5: answer correctly on first try
        for n in range(2, 6):
            page.wait_for_url(f"**/quiz/{n}")
            page.locator(f'.quiz-option[data-opt-id="{key[str(n)]}"]').click()
            page.locator("#advance-btn").click()

        page.wait_for_url("**/result")
        score_text = page.locator("#score-display").inner_text()
        assert score_text.strip() == "5 / 5"
        first_try = page.locator("#first-try").inner_text().strip()
        # Q1 was second-chance correct, so first-try = 4
        assert first_try == "4"

        ctx.close()
        browser.close()
