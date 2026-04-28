"""Build the static (frozen-flask) artifact under _static_build/.

The frozen output renders every public route to disk:
    /                  → index.html
    /intro             → intro/index.html
    /learn/<n>         → learn/<n>/index.html (n=1..4)
    /quiz/<n>          → quiz/<n>/index.html (n=1..5)
    /result            → result/index.html
    /reference         → reference/index.html
    /static/...        → copied as-is

API routes (/api/state, /api/event, /api/reset) and /start are *not*
frozen — they don't make sense without a server, and LocalBackend
takes over those responsibilities client-side.

Run:
    uv run python freeze.py
    make freeze
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from flask_frozen import Freezer  # noqa: E402

from app import create_app  # noqa: E402
import reducer  # noqa: E402


DESTINATION = ROOT / "_static_build"


def build():
    app = create_app(is_static=True)
    app.config["FREEZER_DESTINATION"] = str(DESTINATION)
    app.config["FREEZER_RELATIVE_URLS"] = False
    app.config["FREEZER_REMOVE_EXTRA_FILES"] = True
    # Skip routes that only make sense with a live server.
    app.config["FREEZER_SKIP_EXISTING"] = False

    freezer = Freezer(app, with_no_argument_rules=False, with_static_files=True)

    @freezer.register_generator
    def home():
        yield "/"

    @freezer.register_generator
    def intro():
        yield "/intro/"

    @freezer.register_generator
    def learn():
        for n in range(1, reducer.NUM_LESSONS + 1):
            yield f"/learn/{n}/"

    @freezer.register_generator
    def quiz():
        # Main flow + bonus pages. Bonus pages are frozen too because the
        # LocalBackend unlocks bonus client-side — the HTML has to exist on
        # disk for the JS redirect to resolve.
        for n in range(1, reducer.NUM_QUIZZES + 1):
            yield f"/quiz/{n}/"
        for qid in reducer.BONUS_QUIZ_IDS:
            yield f"/quiz/{qid}/"

    @freezer.register_generator
    def result():
        yield "/result/"

    @freezer.register_generator
    def reference_card():
        yield "/reference/"

    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)

    written = freezer.freeze()
    return sorted(str(p) for p in written)


def main() -> int:
    paths = build()
    print(f"frozen {len(paths)} URL(s) → {DESTINATION.relative_to(ROOT)}/")
    for p in paths:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
