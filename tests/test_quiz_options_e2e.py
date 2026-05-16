"""Playwright e2e coverage for structured quiz options (2026-04-23).

Low-difficulty variants can set `icon` on individual options to render
a concept SVG next to the text. The MC button layout must accommodate
both shapes — iconed and iconless options side by side in one list —
without row misalignment. Higher-difficulty variants (burn_in / medium
/ high) must stay icon-free.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402
import reducer  # noqa: E402
from state_store import StateStore  # noqa: E402


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
    app.config["_db_path"] = str(db)

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

    yield f"http://127.0.0.1:{port}", str(db)


def _force_variant(db_path: str, sid: str, qid: str, variant: str):
    """Pin the active variant for a session so the live server serves
    the expected bucket regardless of adaptive-difficulty state."""
    store = StateStore(db_path)
    s = store.load(sid)
    selections = dict(s.variant_selections)
    selections[qid] = variant
    store.save(replace(s, variant_selections=selections))


def test_icon_and_iconless_options_share_the_same_list_cleanly(live_server):
    # Use q7's low variant — it has a mixed list: option "a" has no
    # icon, options "b" and "c" each have one. This is the critical
    # shape for verifying layout doesn't misalign.
    from playwright.sync_api import sync_playwright

    base_url, db_path = live_server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Seed session + pin q7 to `low`.
        r = page.goto(base_url + "/", wait_until="domcontentloaded")
        assert r and r.ok
        # POST /start to create the session cookie.
        page.locator("#start-btn").click()
        page.wait_for_url("**/intro")
        # Extract the session cookie's sid.
        cookies = ctx.cookies(base_url)
        # Flask signs the session cookie; reading the sid directly from
        # the server side is easier. Hit /api/state.
        import json as _json
        api = page.context.request.get(base_url + "/api/state")
        sid = _json.loads(api.text())["session_id"]
        _force_variant(db_path, sid, "7", "low")

        page.goto(base_url + "/quiz/7?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector("#quiz-options")

        # Collect rendered options: their row-heights should match.
        rows = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('#quiz-options .quiz-option')
            ).map(btn => ({
                id: btn.dataset.optId,
                hasIcon: !!btn.querySelector('.quiz-option-icon'),
                height: btn.getBoundingClientRect().height,
                top: btn.getBoundingClientRect().top,
                text: btn.querySelector('.quiz-option-text')?.textContent.trim(),
            }))"""
        )
        assert len(rows) >= 3, f"expected >=3 options on q7/low; got {len(rows)}"

        # Mixed shape: at least one with icon, at least one without.
        iconed = [r for r in rows if r["hasIcon"]]
        iconless = [r for r in rows if not r["hasIcon"]]
        assert iconed and iconless, (
            f"q7/low should have both iconed and iconless options; got {rows}"
        )

        # Row height parity — the shape change must not break layout.
        heights = [r["height"] for r in rows]
        assert max(heights) - min(heights) <= 1.0, (
            f"iconed/iconless option heights differ by more than 1 px: {heights}"
        )

        # Icon actually renders as SVG inside the marker span.
        svg_count = page.evaluate(
            "() => document.querySelectorAll('#quiz-options .quiz-option-icon svg').length"
        )
        assert svg_count == len(iconed), (
            f"expected {len(iconed)} icon SVGs; found {svg_count}"
        )

        browser.close()


def test_medium_variant_has_no_icons_rendered(live_server):
    # Higher-difficulty variants stay icon-free. Visit q7 with `medium`
    # pinned and assert no .quiz-option-icon nodes in the DOM.
    from playwright.sync_api import sync_playwright

    base_url, db_path = live_server
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        page.goto(base_url + "/", wait_until="domcontentloaded")
        page.locator("#start-btn").click()
        page.wait_for_url("**/intro")
        import json as _json
        api = page.context.request.get(base_url + "/api/state")
        sid = _json.loads(api.text())["session_id"]
        _force_variant(db_path, sid, "7", "medium")

        page.goto(base_url + "/quiz/7?reveal=off", wait_until="domcontentloaded")
        page.wait_for_selector("#quiz-options")

        icons = page.evaluate(
            "() => document.querySelectorAll('#quiz-options .quiz-option-icon').length"
        )
        assert icons == 0, f"medium variant should have 0 icons; got {icons}"

        browser.close()
