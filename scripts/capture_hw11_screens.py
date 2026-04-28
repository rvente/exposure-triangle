"""Capture screenshots of the deployed Exposure Triangle pages for the
HW11 graphic-design submission.

Targets each "most important" screen the rubric calls for:

    /            -> screen_home.png         (home)
    /intro/      -> screen_intro.png        (transition)
    /learn/1/    -> screen_learn.png        (one learning screen)
    /quiz/1/     -> screen_quiz.png         (one quiz screen)
    /result/     -> screen_result.png       (final quiz screen)
    /reference/  -> screen_reference.png    (extra — reference card)

For /result/ the script seeds LocalBackend state (10 answered quizzes
with a mix of right and wrong) so the per-question review renders with
real content rather than an empty list. The seed shape mirrors
`static/js/reducer.js::newState` and the answer-entry shape used by
`submit_answer`.

Usage:
    uv run python scripts/capture_hw11_screens.py [--base URL] [--out DIR]

Defaults:
    --base  https://exposure-triangle.pages.dev
    --out   ../hw11/placeholders/   (relative to repo root)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE = "https://exposure-triangle.pages.dev"
DEFAULT_OUT = REPO_ROOT.parent / "hw11" / "placeholders"
VIEWPORT = {"width": 1440, "height": 900}


def seed_state_for_result() -> dict:
    """A plausible end-state for a learner who walked the full flow,
    cleared the bonus gate, and answered both bonus questions. Shape
    matches `static/js/reducer.js::newState` plus the per-answer fields
    populated by `submit_answer`. Values chosen so the result page
    surfaces the bonus banner + a mix of correct/wrong rows.
    """
    base_ts = 1_730_000_000_000  # arbitrary millisecond timestamp
    answers = []

    # qid -> (chosen, is_correct, attempts, latency_ms, first_try_correct)
    plan = [
        ("1", "a", True,  1, 4_200, True),
        ("2", "b", True,  1, 5_100, True),
        ("3", "c", True,  1, 6_800, True),
        ("4", "a", True,  1, 7_300, True),
        ("5", "b", True,  1, 4_900, True),
        ("6", "b", True,  1, 5_700, True),
        ("7", "a", False, 2, 9_100, False),
        ("8", "a", True,  1, 6_300, True),
        ("9", "b", True,  1, 5_500, True),
        ("10", "a", True, 1, 8_400, True),
    ]
    for qid, choice, correct, attempts, latency_ms, first_try in plan:
        answers.append({
            "qid": qid,
            "choice": choice,
            "correct": correct,
            "attempts": attempts,
            "latency_ms": latency_ms,
            "first_try_correct": first_try,
        })

    return {
        "sessionId": "hw11-capture-fixture",
        "page": "result",
        "pageIndex": 0,
        "answers": answers,
        "lessons": {},
        "lessonsEntered": {},
        "attempts": {q[0]: q[3] for q in plan},
        "latencyMs": {q[0]: q[4] for q in plan},
        "firstTryCorrect": {q[0]: q[5] for q in plan},
        "proficiency": 0.85,
        "proficiencyEwma": 0.82,
        "bucket": "high",
        "pendingBucket": "high",
        "pendingBucketCount": 0,
        "bonusUnlocked": True,
        "variantSelections": {
            "4": "high", "5": "high", "6": "high", "7": "high",
            "8": "high", "9": "high", "10": "high",
        },
        "_seededAt": base_ts,
    }


def capture(page: Page, url: str, out_path: Path) -> None:
    page.goto(url, wait_until="networkidle")
    # Settle reveal-cascade + chapter-nav progress sweep before shooting.
    # ?reveal=off short-circuits the staggered animations.
    if "?" not in url:
        page.goto(url + "?reveal=off", wait_until="networkidle")
    page.wait_for_timeout(400)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out_path), full_page=False)
    print(f"  -> {out_path.relative_to(REPO_ROOT.parent)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"Base URL to capture from (default: {DEFAULT_BASE})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Output directory (default: {DEFAULT_OUT})")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    out = args.out.resolve()

    targets = [
        ("/",            "screen_home.png",      False),
        ("/intro/",      "screen_intro.png",     False),
        ("/learn/1/",    "screen_learn.png",     False),
        ("/quiz/1/",     "screen_quiz.png",      False),
        ("/reference/",  "screen_reference.png", False),
        ("/result/",     "screen_result.png",    True),  # needs seeded state
    ]

    print(f"Capturing from {base}")
    print(f"Writing to {out}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
        page = context.new_page()

        # Seed LocalBackend state on the origin first so /result has rows
        # to render. localStorage is origin-scoped, so a single visit to
        # any page on the base URL is enough to seed it.
        page.goto(base + "/", wait_until="networkidle")
        seed = seed_state_for_result()
        page.evaluate(
            "(s) => localStorage.setItem('exposure_triangle_state_v2', JSON.stringify(s))",
            seed,
        )

        for path, name, _needs_seed in targets:
            print(f"  {path}")
            capture(page, base + path, out / name)

        browser.close()

    print(f"\nDone. {len(targets)} screenshots written to {out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
