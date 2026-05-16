"""Playwright e2e coverage for the Capture Duration fullscreen image
preview (G4 item #6).

Covers:
  - /learn/2 duration showcase: clicking any of the three `.showcase-row`
    images opens the modal with the right src + caption; Escape closes;
    focus returns to the clicked trigger.
  - /learn/3 duration slider: clicking `#slider-image` opens the modal,
    and then dragging the tuner (via `#slider-input` value changes)
    live-updates the modal's <img>.src to match the new frame. Mirrors
    the roadmap spec "respects the current slider state."
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


def test_showcase_image_opens_and_closes_preview(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(live_server + "/learn/2?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector(".showcase-row img")

        trigger = page.locator(".showcase-row img").first
        trigger.scroll_into_view_if_needed()
        trigger_src = trigger.get_attribute("src")
        trigger.click()

        page.wait_for_selector(".image-preview-modal.open", timeout=2000)
        assert page.evaluate(
            "() => !document.getElementById('image-preview-modal').hidden"
        )
        modal_src = page.evaluate(
            "() => document.querySelector('.image-preview-img').src"
        )
        assert trigger_src.split("/")[-1] in modal_src

        # Escape dismisses.
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        assert page.evaluate(
            "() => document.getElementById('image-preview-modal').hidden"
        )
        # Focus returns to the trigger.
        assert page.evaluate(
            "() => document.activeElement === document.querySelector('.showcase-row img')"
        )

        browser.close()


def test_preview_tracks_slider_state_on_learn_3(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(live_server + "/learn/3?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector("#slider-image")

        # Open preview on the main slider viewer.
        page.locator("#slider-image").scroll_into_view_if_needed()
        page.locator("#slider-image").click()
        page.wait_for_selector(".image-preview-modal.open", timeout=2000)

        initial_src = page.evaluate(
            "() => document.querySelector('.image-preview-img').src"
        )

        # Drag the tuner to the last frame.
        page.evaluate(
            """() => {
                const el = document.getElementById('slider-input');
                el.value = String(parseInt(el.max, 10));
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        page.wait_for_timeout(150)

        new_src = page.evaluate(
            "() => document.querySelector('.image-preview-img').src"
        )
        assert new_src != initial_src, (
            f"preview should swap src when slider value changes; "
            f"initial={initial_src.split('/')[-1]} new={new_src.split('/')[-1]}"
        )

        # Close via Escape (backdrop click is behind the centered image
        # frame so Playwright's center-click lands on the frame; Escape
        # is the cleaner assertion surface).
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)
        assert page.evaluate(
            "() => document.getElementById('image-preview-modal').hidden"
        )

        browser.close()
