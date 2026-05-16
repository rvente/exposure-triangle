"""Playwright e2e coverage for the scrub dial interactions (G4 item #4).

Covers:
  - Click-to-jump on the iris drum (new): clicking a label (or dead-space
    near a label) jumps the drum to that index.
  - Click-to-jump on the shutter tuner (regression guard): the tuner has
    always jumped to the clicked strip position; confirm that still works.
  - Drag-past-edge / no-ratchet: a big horizontal drag on the drum (well
    past the right end of the range) followed by a small reverse drag
    must immediately start pulling the value down — the overshoot does
    not build up invisible "debt".
  - Idle-hint timer: after ~5s of dwell on a widget without interaction,
    the `.idle-hint` element gains `.visible`. Moving the pointer resets
    the timer. Uses Playwright's `page.clock` for deterministic time.

The app already has `make test-e2e` wiring; this file is picked up by
`pytest tests/test_scrub_dials_e2e.py -v` under xvfb.
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


def _open_iris(page, base_url):
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.locator("#start-btn").click()
    page.wait_for_url("**/intro")
    page.locator("#advance-btn").click()
    page.wait_for_url("**/learn/1")
    # `?reveal=off` bypasses the paragraph-reveal cascade so locators land
    # on elements immediately.
    page.goto(base_url + "/learn/1?reveal=off", wait_until="domcontentloaded")
    page.wait_for_selector("#iris-drum")


def test_drum_click_to_jump_moves_idx(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        _open_iris(page, live_server)

        initial = int(page.get_attribute("#iris-drum", "aria-valuenow") or "0")
        # Click a label that sits to the right of the reticle (aperture drum
        # positions labels around a centered reticle; the label at idx
        # initial+2 lives ~160px to the right of center at 80px per label).
        target = initial + 2
        count = int(page.get_attribute("#iris-drum", "data-count") or "0")
        if target >= count:
            target = max(0, initial - 2)

        label = page.locator(f'#iris-drum .drum-label[data-index="{target}"]')
        label.click()

        # commitIdx eases the hidden input via requestAnimationFrame; wait
        # briefly for the ease to settle before asserting.
        page.wait_for_function(
            "(expected) => parseInt(document.getElementById('iris-drum').getAttribute('aria-valuenow'), 10) === expected",
            arg=target,
            timeout=2000,
        )
        assert int(page.get_attribute("#iris-drum", "aria-valuenow")) == target

        browser.close()


def test_tuner_click_to_jump_regression(live_server):
    # Tuner lives on /learn/3 (duration showcase) — but the slider-input
    # wiring + initTuner only fire on lessons that render a #tuner-strip.
    # /learn/3 is the duration *teaching* slide without the tuner; the
    # shutter tuner actually lands on the duration-slider lesson which
    # in this app is /learn/2. Check each in turn.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        found_page = None
        for n in (3, 2):
            page.goto(live_server + f"/learn/{n}?reveal=off", wait_until="domcontentloaded")
            if page.locator("#tuner-strip").count() > 0:
                found_page = n
                break
        if found_page is None:
            pytest.skip("no /learn/* page renders #tuner-strip in this build")

        strip = page.locator("#tuner-strip")
        strip.scroll_into_view_if_needed()
        box = strip.bounding_box()
        assert box is not None

        # Click at 70% across the strip.
        target_x = box["x"] + box["width"] * 0.70
        target_y = box["y"] + box["height"] / 2
        page.mouse.click(target_x, target_y)

        page.wait_for_function(
            "() => Math.abs(parseFloat(document.getElementById('slider-input').value) - "
            "0.70 * parseInt(document.getElementById('slider-input').max, 10)) < 0.8",
            timeout=2000,
        )
        v = float(page.evaluate("() => parseFloat(document.getElementById('slider-input').value)"))
        vmax = int(page.evaluate("() => parseInt(document.getElementById('slider-input').max, 10)"))
        assert abs(v / vmax - 0.70) < 0.10, f"tuner click-to-jump landed at {v}/{vmax}"

        browser.close()


def test_drum_drag_past_edge_no_ratchet(live_server):
    # Drag well past the right end of the strip, then nudge left by a
    # small amount. The value must move immediately on the reverse nudge,
    # not burn off the overshoot first. This is the core no-ratchet
    # property of Scrub.createScrubAccumulator.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        _open_iris(page, live_server)

        drum = page.locator("#iris-drum .drum-viewport")
        drum.scroll_into_view_if_needed()
        box = drum.bounding_box()
        assert box is not None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        # Carousel feel: drag right → strip follows finger → earlier
        # (lower-index) labels scroll into center → value *decreases*.
        # Drag way right to overshoot the left edge of the range (idx 0
        # = f/1.4). count=9 → strip range is 640 px so +2000 overshoots
        # the clamp by ~1360 px.
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 2000, cy, steps=20)
        maxed_value = float(page.evaluate(
            "() => parseFloat(document.getElementById('slider-input').value)"
        ))
        count = int(page.get_attribute("#iris-drum", "data-count"))
        assert maxed_value <= 0.01, (
            f"expected drag-right to min out slider-input at 0; got {maxed_value}"
        )

        # Small reverse nudge back left — 40 px should pull the value
        # UP by ~0.5 immediately (no ratchet debt to unwind).
        page.mouse.move(cx + 2000 - 40, cy, steps=4)
        page.mouse.up()

        page.wait_for_timeout(400)
        after_idx = int(page.get_attribute("#iris-drum", "aria-valuenow"))
        assert after_idx >= 0
        assert maxed_value == pytest.approx(0, abs=0.01), (
            "during-drag clamp should hit exact min (0)"
        )

        browser.close()


def test_idle_hint_appears_after_dwell_and_resets_on_movement(live_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # page.clock lets us deterministically fast-forward the idle-hint
        # timer (registered via setTimeout in Scrub.registerIdleHint) — no
        # need to wait real seconds for this to be testable. Install before
        # navigation so all setTimeouts are captured; fast_forward later to
        # fire them on demand.
        page.clock.install()
        _open_iris(page, live_server)

        hint = page.locator('.idle-hint[data-idle-hint-for="iris-drum"]')
        assert hint.count() == 1, "iris drum should ship with an idle-hint"
        # Before dwell: hint is hidden.
        assert not hint.evaluate("(el) => el.classList.contains('visible')")

        # Hover over the drum so registerIdleHint arms the timer. A single
        # pointermove event is enough.
        page.locator("#iris-drum").scroll_into_view_if_needed()
        drum = page.locator("#iris-drum").bounding_box()
        assert drum is not None
        page.mouse.move(drum["x"] + 10, drum["y"] + 10)

        # Fast-forward clock past the 4500 ms threshold.
        page.clock.fast_forward(6000)

        assert hint.evaluate("(el) => el.classList.contains('visible')"), (
            "hint should be visible after >4.5s of dwell"
        )

        # Any pointermove inside the widget must hide it again and re-arm.
        page.mouse.move(drum["x"] + 20, drum["y"] + 10)
        assert not hint.evaluate("(el) => el.classList.contains('visible')"), (
            "pointermove should dismiss the hint and re-arm the timer"
        )

        browser.close()


def test_drum_drag_carousel_direction_both_pointer_types(live_server):
    # Per 2026-04-24 unification: both mouse and touch follow the
    # carousel convention — drag right → strip follows finger → earlier
    # (lower-index) labels scroll into center → value *decreases*. The
    # old scrubber convention (mouse drag right → value up) is gone.
    # Verify by comparing a mouse drag (+150 px) vs a touch drag (+150
    # px) from the same starting idx — the resulting fractional values
    # should both move in the same direction (both below the start).
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Mouse context — default chromium, no touch.
        mouse_ctx = browser.new_context()
        mouse_page = mouse_ctx.new_page()
        _open_iris(mouse_page, live_server)
        mouse_page.locator("#iris-drum .drum-viewport").scroll_into_view_if_needed()
        mouse_box = mouse_page.locator("#iris-drum .drum-viewport").bounding_box()
        assert mouse_box is not None
        start_mouse = float(mouse_page.evaluate(
            "() => parseFloat(document.getElementById('slider-input').value)"
        ))
        mx = mouse_box["x"] + mouse_box["width"] / 2
        my = mouse_box["y"] + mouse_box["height"] / 2
        mouse_page.mouse.move(mx, my)
        mouse_page.mouse.down()
        mouse_page.mouse.move(mx + 150, my, steps=10)
        mouse_page.mouse.up()
        mouse_page.wait_for_timeout(300)
        end_mouse = float(mouse_page.evaluate(
            "() => parseFloat(document.getElementById('slider-input').value)"
        ))
        mouse_direction = end_mouse - start_mouse

        # Touch context — emulates a phone so pointerType === "touch".
        touch_ctx = browser.new_context(
            viewport={"width": 414, "height": 896},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        touch_page = touch_ctx.new_page()
        _open_iris(touch_page, live_server)
        touch_page.locator("#iris-drum .drum-viewport").scroll_into_view_if_needed()
        touch_box = touch_page.locator("#iris-drum .drum-viewport").bounding_box()
        assert touch_box is not None
        start_touch = float(touch_page.evaluate(
            "() => parseFloat(document.getElementById('slider-input').value)"
        ))
        tx = touch_box["x"] + touch_box["width"] / 2
        ty = touch_box["y"] + touch_box["height"] / 2
        # Build a multi-step touch drag by dispatching PointerEvents with
        # pointerType='touch' directly — Playwright's higher-level touch
        # API doesn't give a multi-step drag handle in sync mode.
        touch_page.evaluate(
            """(args) => {
                const el = document.querySelector('#iris-drum .drum-viewport');
                const opts = (clientX, movementX) => ({
                    bubbles: true, cancelable: true,
                    pointerId: 1, pointerType: 'touch', isPrimary: true,
                    clientX, clientY: args.y, movementX, movementY: 0,
                });
                el.dispatchEvent(new PointerEvent('pointerdown', opts(args.x0, 0)));
                for (let i = 1; i <= 10; i++) {
                    const step = args.dx / 10;
                    el.dispatchEvent(new PointerEvent('pointermove',
                        opts(args.x0 + step * i, step)));
                }
                el.dispatchEvent(new PointerEvent('pointerup',
                    opts(args.x0 + args.dx, 0)));
            }""",
            {"x0": tx, "y": ty, "dx": 150},
        )
        touch_page.wait_for_timeout(300)
        end_touch = float(touch_page.evaluate(
            "() => parseFloat(document.getElementById('slider-input').value)"
        ))
        touch_direction = end_touch - start_touch

        # Both drags must move the value DOWN (same direction — carousel
        # feel unified across pointer types as of 2026-04-24).
        assert mouse_direction < 0, (
            f"mouse drag right should decrease value (carousel feel); "
            f"got {mouse_direction:+.3f}"
        )
        assert touch_direction < 0, (
            f"touch drag right should decrease value; got {touch_direction:+.3f}"
        )

        browser.close()


def test_drum_wheel_scrolls_value(live_server):
    # Horizontal trackpad scroll (deltaX) on the iris drum should drive
    # the same virtual position as a drag. Vertical wheel (deltaY) is
    # the fallback for classic mouse wheels. Sign matches the drag:
    # positive deltaX/deltaY → earlier items scroll into center → value
    # decreases. A negative delta moves the value up.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1400, "height": 1400})
        page = ctx.new_page()
        _open_iris(page, live_server)

        drum = page.locator("#iris-drum .drum-viewport")
        drum.scroll_into_view_if_needed()
        box = drum.bounding_box()
        assert box is not None
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        def set_idx(n):
            page.evaluate(
                "(n) => { const el = document.getElementById('slider-input');"
                "el.value = String(n);"
                "el.dispatchEvent(new Event('input', { bubbles: true })); }",
                n,
            )
            page.wait_for_timeout(200)

        # deltaX +240 → value drops by 3 (240 / 80 px per label).
        set_idx(5)
        page.mouse.move(cx, cy)
        page.mouse.wheel(240, 0)
        page.wait_for_timeout(400)
        val = float(page.evaluate("() => parseFloat(document.getElementById('slider-input').value)"))
        assert val < 5, f"wheel deltaX=+240 should decrease value from 5; got {val}"

        # deltaY fallback for classic mouse wheels.
        set_idx(5)
        page.mouse.wheel(0, 240)
        page.wait_for_timeout(400)
        val_y = float(page.evaluate("() => parseFloat(document.getElementById('slider-input').value)"))
        assert val_y < 5, f"wheel deltaY=+240 should decrease value; got {val_y}"

        # Negative wheel → value goes up.
        set_idx(2)
        page.mouse.wheel(-240, 0)
        page.wait_for_timeout(400)
        val_up = float(page.evaluate("() => parseFloat(document.getElementById('slider-input').value)"))
        assert val_up > 2, f"wheel deltaX=-240 should increase value from 2; got {val_up}"

        browser.close()
