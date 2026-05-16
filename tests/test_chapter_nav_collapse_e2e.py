"""Playwright e2e coverage for chapter-nav collapse-on-scroll (G4 #8).

Covers:
  - Scrolling down past ~80 px adds `.chapter-nav--collapsed` (the CSS
    `transform: translateY(-100%)` retracts the nav above the viewport).
  - Scrolling up removes the class and restores the nav.
  - Jitter under the delta threshold does not trigger a flap.
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


def _is_collapsed(page) -> bool:
    return page.evaluate(
        "() => document.querySelector('.chapter-nav')"
        ".classList.contains('chapter-nav--collapsed')"
    )


def test_chapter_nav_collapses_on_scroll_down_expands_on_up(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Narrow viewport ensures the page has enough vertical content
        # to scroll — /learn/3 has hero + tuner + dial + lesson body.
        ctx = browser.new_context(viewport={"width": 900, "height": 500})
        page = ctx.new_page()
        page.goto(live_server + "/learn/3?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector(".chapter-nav")

        assert not _is_collapsed(page), "nav should start expanded"

        # Scroll down past the 80 px threshold → collapse.
        page.evaluate("() => window.scrollTo(0, 400)")
        page.wait_for_timeout(120)
        assert _is_collapsed(page), "scrolling down past 80 px should collapse"

        # Scroll up → expand.
        page.evaluate("() => window.scrollTo(0, 50)")
        page.wait_for_timeout(120)
        assert not _is_collapsed(page), "scrolling up should restore the nav"

        browser.close()


def test_tiny_scroll_delta_does_not_flap_nav(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 900, "height": 500})
        page = ctx.new_page()
        page.goto(live_server + "/learn/3?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector(".chapter-nav")

        # Micro-scroll — below the DELTA_THRESHOLD (4 px).
        page.evaluate("() => window.scrollTo(0, 2)")
        page.wait_for_timeout(80)
        assert not _is_collapsed(page), (
            "scroll deltas under the jitter threshold must not collapse"
        )

        browser.close()
