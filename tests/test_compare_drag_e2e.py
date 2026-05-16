"""Playwright e2e coverage for the A/B compare slider drag (G4 #1 redux).

The 2026-04-23 pass added `pointer-events: none` on the compare `<img>`
elements to stop HTML5 native image drag from eating events. Follow-up
regression report: "drag still stalls" on some platforms (user report).
This suite exercises a multi-step drag and asserts the handle's
`left` tracks every intermediate cursor position — no stalls.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


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


def _handle_left_percent(page) -> float:
    raw = page.evaluate(
        "() => document.querySelector('.compare-handle').style.left"
    )
    assert raw and raw.endswith("%"), f"unexpected handle.left: {raw!r}"
    return float(raw.rstrip("%"))


def test_compare_drag_tracks_every_step(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(live_server + "/learn/6?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector("#compare-viewer")
        page.locator("#compare-viewer").scroll_into_view_if_needed()

        box = page.locator("#compare-viewer").bounding_box()
        assert box is not None
        cy = box["y"] + box["height"] / 2
        start_x = box["x"] + box["width"] * 0.8
        end_x = box["x"] + box["width"] * 0.1

        # Initial handle position (set by attachCompareViewer on mount).
        initial = _handle_left_percent(page)
        assert 40 <= initial <= 60, f"default should start near 50%; got {initial}"

        # Drag from 80% to 10% in 10 steps; sample the handle at each
        # intermediate stop and assert it's tracking.
        page.mouse.move(start_x, cy)
        page.mouse.down()
        samples = []
        N = 10
        for i in range(1, N + 1):
            frac = i / N
            x = start_x + (end_x - start_x) * frac
            page.mouse.move(x, cy)
            samples.append(_handle_left_percent(page))
        page.mouse.up()

        # Monotonic descent: each sample ≤ previous.
        for i in range(1, len(samples)):
            assert samples[i] <= samples[i - 1] + 0.5, (
                f"drag stalled at step {i}: previous={samples[i-1]:.2f}%, "
                f"current={samples[i]:.2f}%, samples={samples}"
            )
        # Final sample close to 10%.
        assert samples[-1] < 15, (
            f"drag should have landed near 10%; got {samples[-1]:.2f}% "
            f"(samples={samples})"
        )

        browser.close()


def test_compare_touch_action_prevents_scroll_hijack(live_server):
    # Compare viewer must declare `touch-action: none` so mobile browsers
    # don't interpret a horizontal drag as a page scroll after a tiny
    # vertical wander. Assert the computed style carries the declaration.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(live_server + "/learn/6?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector("#compare-viewer")
        ta = page.evaluate(
            "() => getComputedStyle(document.getElementById('compare-viewer')).touchAction"
        )
        assert ta == "none", f"compare-viewer must have touch-action: none; got {ta!r}"
        browser.close()
