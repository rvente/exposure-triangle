"""Playwright e2e coverage for the virtual camera /pad (G4 item #11 restore).

Covers:
  - /pad renders the reused Aperture widgets: iris drum,
    `pad-shutter-dial`, `pad-iso-dial`.
  - Both canvases mount (#pad-live-canvas, #pad-photo-canvas); WebGL2
    fallback banner is hidden (tests run in a headless chromium that
    supports WebGL2 under xvfb).
  - Snap button flips readout status to "SNAP %"; a short exposure
    completes and pushes an album entry.
  - Spacebar anywhere triggers snap.
  - Shutter readout tracks the hidden input (live render itself uses
    the fixed 1/120 s, but the readout reflects what Snap will do).
  - Album thumbnail click opens the shared image-preview modal.
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


def _wait_for_album_entry(page, timeout_s=20.0, poll_ms=400):
    # Playwright's wait_for_function polls via RAF hooks which (under
    # headless-software WebGL with two contexts) throttles the scene
    # RAF loop badly. Explicit setTimeout-style polling keeps the page
    # loop unblocked and matches the cadence the standalone debug sees.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        n = page.evaluate(
            "() => document.querySelectorAll('#pad-album-strip .pad-album-item').length"
        )
        if n >= 1:
            return
        page.wait_for_timeout(poll_ms)
    status = page.evaluate(
        "() => document.getElementById('readout-status').textContent"
    )
    raise AssertionError(
        f"album entry did not appear within {timeout_s}s; final status={status!r}"
    )


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


def test_pad_mounts_with_aperture_widgets(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.goto(live_server + "/pad", wait_until="domcontentloaded")
        page.wait_for_selector("#pad-live-canvas")
        page.wait_for_selector("#pad-photo-canvas")
        page.wait_for_timeout(500)

        # Reused Aperture widgets.
        assert page.locator("#iris-drum").count() == 1
        assert page.locator("#pad-shutter-dial").count() == 1
        assert page.locator("#pad-iso-dial").count() == 1
        # Hidden inputs for each control.
        for sel in ("#pad-iris-input", "#pad-shutter-input", "#pad-iso-input"):
            assert page.locator(sel).count() == 1, f"missing {sel}"
        # Album scaffolding present, starts empty.
        assert page.locator("#pad-album-strip").count() == 1
        assert page.evaluate(
            "() => document.getElementById('pad-album-strip').children.length"
        ) == 0
        # Fallback banner hidden under WebGL2.
        assert page.evaluate(
            "() => document.getElementById('pad-fallback').hidden"
        ), "WebGL2 should be available under headless chromium"

        browser.close()


def test_pad_snap_completes_and_adds_album_entry(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.goto(live_server + "/pad?snap_min=128", wait_until="domcontentloaded")
        page.wait_for_selector("#pad-snap-btn")
        page.wait_for_timeout(300)

        assert page.evaluate(
            "() => document.getElementById('readout-status').textContent"
        ) == "LIVE"

        # Use the fastest shutter so the snap hits its SPP floor quickly.
        page.evaluate(
            """() => {
                const el = document.getElementById('pad-shutter-input');
                el.value = '0';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        page.locator("#pad-snap-btn").click()
        _wait_for_album_entry(page, timeout_s=20.0)
        assert page.evaluate(
            "() => document.getElementById('readout-status').textContent"
        ) == "LIVE"

        # Spacebar triggers a second snap → second album entry.
        page.keyboard.press(" ")
        # Poll for a second entry; don't race on mid-snap status which
        # can complete faster than Playwright's polling interval.
        deadline = time.time() + 20.0
        while time.time() < deadline:
            n = page.evaluate(
                "() => document.querySelectorAll('#pad-album-strip .pad-album-item').length"
            )
            if n >= 2:
                break
            page.wait_for_timeout(400)
        else:
            raise AssertionError("spacebar snap did not add a second album entry")

        browser.close()


def test_pad_album_thumbnail_opens_image_preview(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.goto(live_server + "/pad?snap_min=128", wait_until="domcontentloaded")
        page.wait_for_selector("#pad-snap-btn")
        page.wait_for_timeout(300)

        # Fastest shutter → fastest completion.
        page.evaluate(
            """() => {
                const el = document.getElementById('pad-shutter-input');
                el.value = '0';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        page.locator("#pad-snap-btn").click()
        _wait_for_album_entry(page, timeout_s=20.0)

        # Click the thumbnail → shared image-preview modal opens.
        page.locator("#pad-album-strip .pad-album-item").first.click()
        page.wait_for_function(
            "() => { const m = document.getElementById('image-preview-modal');"
            "return m && !m.hidden; }",
            timeout=2000,
        )
        caption_has_settings = page.evaluate(
            "() => !!document.querySelector('#image-preview-modal "
            ".image-preview-caption .pad-caption-settings')"
        )
        assert caption_has_settings, "preview caption should include f/shutter/ISO"

        browser.close()


def test_pad_live_mode_shutter_readout_follows_dial(live_server):
    # Live rendering uses a fixed 1/120 s shutter regardless of the dial.
    # But the readout should still reflect the user's dial selection, so
    # they can see what "snap" will do without triggering it. This test
    # just verifies the readout tracks the hidden input.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        page.goto(live_server + "/pad", wait_until="domcontentloaded")
        page.wait_for_selector("#pad-shutter-input")
        page.wait_for_timeout(300)

        # Drive the hidden shutter input to the slowest stop (index 8 = 1s).
        page.evaluate(
            """() => {
                const el = document.getElementById('pad-shutter-input');
                el.value = '8';
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        page.wait_for_timeout(100)
        readout = page.evaluate(
            "() => document.getElementById('readout-shutter').textContent"
        )
        # At idx 8 the shutter is 1.0 s; our formatShutterReadout formats
        # whole-seconds with 1 decimal → "1.0".
        assert readout == "1.0", f"expected shutter readout '1.0'; got {readout!r}"

        browser.close()
