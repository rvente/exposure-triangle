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
        page.wait_for_url("**/intro")
        page.locator("#advance-btn").click()
        page.wait_for_url("**/learn/1")

        # Seven lessons after the s3/s6 split: 1=iris (slider), 2=duration
        # teaching showcase, 3=duration slider, 4=sensitivity teaching
        # showcase, 5=sensitivity toggle, 6=sensitivity compare, 7=triangle
        # summary. Exercise the snap slider on 1, the ISO toggle on 5, the
        # compare divider on 6 to guard the widgets against regressions.
        for n in range(1, 8):
            assert f"/learn/{n}" in page.url
            if n == 1:
                # Snap slider: set to last index and confirm the viewer image
                # src picks up the corresponding frame.
                page.wait_for_selector("#slider-input")
                last_idx = page.evaluate(
                    "() => parseInt(document.getElementById('slider-input').max, 10)"
                )
                page.evaluate(
                    """(idx) => {
                        const el = document.getElementById('slider-input');
                        el.value = String(idx);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                    }""",
                    last_idx,
                )
                src = page.evaluate("() => document.getElementById('slider-image').getAttribute('src')")
                assert "bokeh_f32.0" in src, f"slider did not advance to last frame: {src}"
            if n == 5:
                # Toggle group: click "High" and verify the viewer swaps.
                page.locator('#toggle-group .toggle-btn[data-index="2"]').click()
                src = page.evaluate("() => document.getElementById('toggle-image').getAttribute('src')")
                assert "iso_high" in src, f"toggle did not swap image: {src}"
            if n == 6:
                viewer = page.locator("#compare-viewer")
                assert viewer.count() == 1
                # Wait for the JS attach to initialize the handle position at 50%.
                page.wait_for_function(
                    "() => { const h = document.querySelector('#compare-viewer .compare-handle'); return h && h.style.left === '50%'; }"
                )
                # Dispatch a pointerdown at 25% of the viewer width. Playwright's
                # mouse.down does not always fire pointerdown in headless Chromium,
                # so we dispatch directly — the handler still receives a real event.
                moved = page.evaluate(
                    """() => {
                        const el = document.getElementById('compare-viewer');
                        const rect = el.getBoundingClientRect();
                        const x = rect.left + rect.width * 0.25;
                        const y = rect.top + rect.height * 0.5;
                        const opts = { bubbles: true, clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse' };
                        el.dispatchEvent(new PointerEvent('pointerdown', opts));
                        return document.querySelector('#compare-viewer .compare-handle').style.left;
                    }"""
                )
                assert moved.endswith("%"), f"unexpected handle left: {moved!r}"
                pct = float(moved.rstrip("%"))
                assert abs(pct - 25) < 5, f"handle did not move to ~25%: {moved}"
            page.locator("#advance-btn").click()

        # Quiz 1: test second-chance mechanic — wrong first, then correct
        page.wait_for_url("**/quiz/1")
        opts = [o["id"] for o in quizzes["1"]["burn_in"]["options"]]
        wrong = _wrong_choice(key["1"], opts)
        page.locator(f'#quiz-options button[data-opt-id="{wrong}"]').click()
        # Page re-renders with retry still allowed (advance button absent)
        assert page.locator("#advance-btn").count() == 0
        # Now click the correct answer
        page.locator(f'#quiz-options button[data-opt-id="{key["1"]}"]').click()
        page.locator("#advance-btn").click()

        # Main-flow quizzes 2..8: answer correctly on first try. The bonus
        # gate evaluates at 4+ first-try correct among the first 5 answers;
        # q1 was second-chance correct (first_try = False) and q2..q5 are
        # first-try right, so the gate clears at q5 → bonus unlocks.
        for n in range(2, 9):
            page.wait_for_url(f"**/quiz/{n}")
            page.locator(f'#quiz-options button[data-opt-id="{key[str(n)]}"]').click()
            page.locator("#advance-btn").click()

        # Bonus track: q9 + q10. Advance from q8 routes to q9 because the
        # gate cleared. q9 is an image-choice quiz; same selectors apply.
        for n in (9, 10):
            page.wait_for_url(f"**/quiz/{n}")
            page.locator(f'#quiz-options button[data-opt-id="{key[str(n)]}"]').click()
            page.locator("#advance-btn").click()

        page.wait_for_url("**/result")
        score_text = page.locator("#score-display").inner_text()
        # 10 total questions (8 main + 2 bonus); all 10 correct.
        assert score_text.strip() == "10 / 10"
        first_try = page.locator("#first-try").inner_text().strip()
        # Q1 was second-chance correct; all others first-try right → 9.
        assert first_try == "9"
        # Bonus celebration surfaces on the result page.
        assert page.locator("#bonus-celebration").count() == 1, (
            "result page should render the bonus-unlock celebration banner"
        )

        ctx.close()
        browser.close()


def test_locked_out_path_routes_to_result_after_last_main(live_server):
    """Mirror of test_advance_quiz_from_last_main_routes_to_result_when_locked_out
    in test_reducer.py, but exercised end-to-end under Playwright so the
    Flask route + LocalBackend-unaware-of-bonus path is covered in HTTP.

    Sabotage strategy: miss q1 AND q2 on first try. That drops first-try
    corrects in the BONUS_GATE_WINDOW (first 5 answers) to at most 3,
    below the threshold of 4 — gate stays locked, advance from q8 goes
    to /result instead of /quiz/9.
    """
    from playwright.sync_api import sync_playwright

    key = _answer_keys()
    quizzes = json.loads((ROOT / "data" / "quizzes.json").read_text())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Fresh browser context → fresh cookie jar → fresh server-side
        # session row, independent from `test_full_click_through`.
        ctx = browser.new_context()
        page = ctx.new_page()

        page.goto(live_server + "/", wait_until="domcontentloaded")
        page.locator("#start-btn").click()
        page.wait_for_url("**/intro")
        page.locator("#advance-btn").click()
        # Fast-forward through lessons without exercising widgets — the
        # first test already covers widget regressions. Just click Advance.
        for _ in range(1, 8):
            page.locator("#advance-btn").click()

        sabotage = {"1", "2"}
        for n in range(1, 9):
            page.wait_for_url(f"**/quiz/{n}")
            qid = str(n)
            correct = key[qid]
            if qid in sabotage:
                # Pick a wrong option first so first_try_correct becomes False.
                opts = [o["id"] for o in quizzes[qid]["burn_in"]["options"]]
                wrong = _wrong_choice(correct, opts)
                page.locator(f'#quiz-options button[data-opt-id="{wrong}"]').click()
            page.locator(f'#quiz-options button[data-opt-id="{correct}"]').click()
            page.locator("#advance-btn").click()

        # Advance from q8 should skip bonus and land on /result.
        page.wait_for_url("**/result", timeout=5000)
        assert "/quiz/9" not in page.url and "/quiz/10" not in page.url
        # Total shows 8 (no bonus answered), not 10.
        score_text = page.locator("#score-display").inner_text().strip()
        assert score_text == "8 / 8", (
            f"Expected score '8 / 8' (no bonus reached), got {score_text!r}"
        )
        # Bonus celebration must NOT appear.
        assert page.locator("#bonus-celebration").count() == 0, (
            "result page should not show the bonus banner when bonus was "
            "never reached"
        )
        # Chapter-nav should not include the Bonus pip.
        assert page.locator('.chapter-nav [data-slug="bonus"]').count() == 0, (
            "chapter-nav should not render a Bonus pip when gate stayed locked"
        )

        ctx.close()
        browser.close()
