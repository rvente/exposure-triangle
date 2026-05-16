"""Playwright e2e coverage for the floating bottom nav (G4 item #7).

Covers:
  - `.page-nav` is fixed-positioned at the bottom of the viewport on
    every flow page (regression guard — templates each emit a
    `.page-nav` block but the CSS now lives one place).
  - Translucency rule: hover over text content in `.slide-content`
    toggles `.reading` on the nav; hover off removes it.
  - Hover over the nav itself does NOT flip `.reading` (nav is
    excluded from the hover set).
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


def test_page_nav_is_fixed_at_viewport_bottom(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        for path in ("/learn/1", "/learn/3", "/intro"):
            page.goto(live_server + path + "?reveal=off", wait_until="domcontentloaded")
            page.wait_for_selector(".page-nav")
            rect = page.evaluate(
                "() => { const n = document.querySelector('.page-nav'); "
                "const r = n.getBoundingClientRect(); "
                "return { bottom: r.bottom, pos: getComputedStyle(n).position }; }"
            )
            assert rect["pos"] == "fixed", (
                f"{path}: .page-nav should be fixed; got {rect['pos']}"
            )
            # Pinned to the viewport bottom (±1 px tolerance for subpixel rounding).
            assert abs(rect["bottom"] - 800) <= 2, (
                f"{path}: .page-nav bottom should be ~viewport height; got {rect['bottom']}"
            )
        browser.close()


def test_nav_translucency_toggles_on_text_hover(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(live_server + "/learn/2?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector(".slide-content")
        # Pick a paragraph that the lesson definitely has.
        para = page.locator(".slide-content p").first
        assert para.count() >= 1
        para.scroll_into_view_if_needed()
        para.hover()
        page.wait_for_timeout(80)
        assert page.evaluate(
            "() => document.querySelector('.page-nav').classList.contains('reading')"
        ), "hovering a paragraph should flip the nav to .reading"

        # Hover away.
        page.mouse.move(5, 5)
        page.wait_for_timeout(80)
        assert not page.evaluate(
            "() => document.querySelector('.page-nav').classList.contains('reading')"
        ), "hovering off the paragraph should clear .reading"

        browser.close()


def test_hover_over_nav_itself_does_not_flip_reading(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(live_server + "/learn/2?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector(".page-nav")
        # Move cursor to the nav.
        nav_box = page.locator(".page-nav").bounding_box()
        assert nav_box is not None
        page.mouse.move(
            nav_box["x"] + nav_box["width"] / 2,
            nav_box["y"] + nav_box["height"] / 2,
        )
        page.wait_for_timeout(80)
        assert not page.evaluate(
            "() => document.querySelector('.page-nav').classList.contains('reading')"
        ), "hovering the nav itself should NOT flip .reading"
        browser.close()
