"""Render the state atlas to static PNGs.

Spawns the atlas server (tests/atlas_server.py) in a background thread,
drives Playwright Chromium through the frame catalog, and writes:

- tests/_atlas_output/atlas.png         — full-page screenshot of the
                                          /_atlas/ index (the contact sheet
                                          with all iframes laid out).
- tests/_atlas_output/frame-<slug>.png  — per-frame screenshot at a
                                          larger viewport for detail.

Usage:
    uv run python tests/build_atlas_static.py
    make atlas-static

Designed to run headless in CI without xvfb. Playwright's launch(headless=True)
doesn't need a display.
"""
from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_server import _frame_catalog, build_app  # noqa: E402


OUT_DIR = Path(__file__).resolve().parent / "_atlas_output"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server() -> tuple[str, threading.Thread]:
    port = _free_port()
    app = build_app()

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
        raise RuntimeError("atlas server did not start in time")
    return f"http://127.0.0.1:{port}", t


def _wait_for_iframes(page, expected: int):
    # Bounded wait: every iframe's contentDocument has readyState === "complete".
    page.wait_for_function(
        """(expected) => {
            const frames = Array.from(document.querySelectorAll('iframe'));
            if (frames.length < expected) return false;
            return frames.every(f => {
                try { return f.contentDocument && f.contentDocument.readyState === 'complete'; }
                catch (_) { return false; }
            });
        }""",
        arg=expected,
        timeout=15000,
    )


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT_DIR.mkdir(exist_ok=True)
    for f in OUT_DIR.glob("*.png"):
        f.unlink()

    catalog = _frame_catalog()
    base, _t = _start_server()
    print(f"atlas server up on {base}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            # Contact sheet: full-page screenshot of /_atlas/ at a wide viewport.
            ctx = browser.new_context(viewport={"width": 2560, "height": 1440}, device_scale_factor=1)
            page = ctx.new_page()
            page.goto(base + "/_atlas/", wait_until="load")
            _wait_for_iframes(page, len(catalog))
            sheet = OUT_DIR / "atlas.png"
            page.screenshot(path=str(sheet), full_page=True)
            print(f"wrote {sheet.relative_to(ROOT)}")
            ctx.close()

            # Per-frame screenshots at a larger viewport for detail.
            ctx = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)
            page = ctx.new_page()
            for slug, title, _desc, _builder in catalog:
                # `?reveal=off` short-circuits the paragraph fade-in cascade
                # so the screenshot captures the final settled state.
                page.goto(f"{base}/_atlas/frame/{slug}?reveal=off", wait_until="load")
                # One-frame settle for images + CSS.
                page.wait_for_timeout(150)
                out = OUT_DIR / f"frame-{slug}.png"
                page.screenshot(path=str(out), full_page=True)
                print(f"wrote {out.relative_to(ROOT)}  [{title}]")
            ctx.close()
        finally:
            browser.close()

    print(f"\n{len(catalog) + 1} PNGs → {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
