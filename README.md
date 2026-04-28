# exposure_triangle_rv2459

Flask app covering HW10 (scaffold + flow), HW11 (design + interaction
polish), and HW12 (adaptive difficulty v1) for the Exposure Triangle
learning arc. See `roadmap/ROADMAP.md` for gate definitions and
`roadmap/ADAPTIVE_DIFFICULTY.md` for the adaptive-difficulty spec.

## Setup

```
uv sync
uv run playwright install chromium
```

## Run

```
uv run flask --app app run --port 5000
```

Open http://127.0.0.1:5000/ and click **Start**.

## Tests

Unit + route + state-store + data-integrity tests:

```
make test                      # test_reducer.py only
uv run pytest tests/ -q        # everything except e2e
```

End-to-end (Playwright, headless):

```
xvfb-run -a uv run pytest tests/test_e2e.py -v
```

Current counts (2026-04-19): **37 reducer** (logic + data-integrity
guards), **9 app-route** (bonus URL guards, template context-var
threading, chapter-nav injection), **7 state-store** (round-trip + legacy
row compat + field-addition regression guard), **11 freeze** (static
build validation), **50 atlas** (smoke-test every catalog frame),
**2 e2e** (perfect-score bonus walk + locked-out bypass). Total ~116
unit/integration + 2 e2e.

## State atlas (inspection harness)

Not part of the assignment runtime. Wraps the app and mounts `/_atlas/`,
which shows every meaningfully-unique UI state side by side as iframes.
Useful for manual visual regression. Covers all lessons, all main-flow
quiz states, every post-burn-in variant (low/medium/high per quiz),
both bonus quizzes in fresh + locked-correct states, and result pages
with and without the bonus celebration banner.

```
make atlas     # runs tests/atlas_server.py on port 5001
```

Open `http://127.0.0.1:5001/_atlas/` in a browser. Each frame is rendered
from the real templates with a synthetic context (no session, no DB). The
frame catalog lives in `tests/atlas_server.py::_frame_catalog`.

`pytest tests/test_atlas.py` smoke-tests every frame (index + each frame
body returns 200, unknown slug 404s).

### Static atlas (CI artifact)

```
make atlas-static
```

Renders every frame to `tests/_atlas_output/` using headless Playwright:

- `atlas.png` — full-page contact sheet of `/_atlas/`.
- `frame-<slug>.png` — per-frame detail screenshot.

The GitHub Actions workflow `.github/workflows/atlas.yml` runs this on
every push/PR that touches `exposure_triangle_rv2459/**` and uploads the
PNGs as a workflow artifact named `atlas-<sha>`. No display server
required — Playwright runs `headless=True`.

On headless Linux without Xvfb, Playwright Chromium cannot open a display.
`xvfb-run -a` creates a virtual X display; `-a` picks a free display number
automatically.

## Layout

- `app.py` — thin Flask adapter. Routes call `reducer.reduce(...)` and let
  the reducer own all state decisions. Live-mode only: bonus URL guard
  + chapter-nav Bonus-pip injection via `context_processor`.
- `reducer.py` — pure `reduce(state, event, now_ms, *, answer_key)`.
  Python is authoritative. Implements burn-in + EWMA-damped bucket shift
  + bonus-path gate + bonus routing.
- `state_store.py` — SQLite (`instance/state.db`), session-id keyed.
  Backwards-compat via `.get()` defaults on every field.
- `data/lessons.json`, `data/quizzes.json` — content. 7 lessons, 10
  quizzes (8 main + 2 bonus). Every post-burn-in qid carries
  low / medium / high variants.
- `templates/` — Jinja templates. `quiz.html` threads `content` (active
  variant), `is_bonus`, and `bonus_index`; `result.html` threads the
  bonus-celebration context.
- `static/js/reducer.js` — exact mirror of `reducer.py` for the
  LocalBackend static build.
- `static/js/backend.js` — `Backend` interface + `FlaskBackend` +
  `LocalBackend` (localStorage-backed, `STORAGE_KEY = exposure_triangle_state_v2`).
- `static/js/app.js` — page wiring, widget auto-drift with global
  mousemove cancel, static-mode form intercepts, bonus chapter-nav
  JS injection, result-page bonus celebration injection.
- `tests/` — see "Tests" above.

## Flow

1. `/` — Start button, creates session, redirects to `/intro`.
2. `/intro` — Press-the-Shutter narrative + "why this page is dark"
   sidebar.
3. `/learn/1..7` — seven lessons. Iris slider (1), duration showcase (2)
   + slider (3), sensitivity showcase (4) + ISO toggle (5) + A/B compare
   (6), triangle summary (7).
4. `/quiz/1..8` — main-flow quizzes. Second-chance mechanic: first wrong
   grays out that option (retry allowed); second wrong locks the
   question and reveals the correct answer. Adaptive difficulty:
   q1–q3 are identical for every user (burn-in); q4–q8 serve
   low / medium / high variants based on the EWMA-damped bucket.
5. `/quiz/9..10` — bonus path. Only reachable when the learner clears
   the gate: ≥ 4 first-try correct across the first 5 answers
   (burn-in + first two activate quizzes). Direct-URL access to
   `/quiz/9` without the gate redirects to `/result` in live mode;
   the frozen-flask static build renders the HTML so LocalBackend can
   navigate once it unlocks bonus client-side.
6. `/result` — final score. Total extends from 8 to 10 when bonus was
   reached; a celebration banner + per-qid stars surface WHY the
   learner earned the bonus slots.
7. `/reference` — post-quiz cheat sheet with the motion-blur vocabulary
   bridge from HW9.

## HW12 adaptive difficulty v1 (de-risked early, formal ship at G3)

See `roadmap/ADAPTIVE_DIFFICULTY.md` for the full spec. Quick reference:

- **Burn-in** (qids 1–3): identical content for every user.
- **Proficiency**: `0.7 · first_try_rate + 0.3 · latency_factor`
  (latency 5 s → 1.0, 25 s+ → 0.0) computed on burn-in answers.
- **EWMA**: per-quiz update with `α = 0.3` after burn-in. Seeded from
  burn-in proficiency at the 3rd burn-in lock.
- **Damping**: bucket only shifts when EWMA wants the same *different*
  bucket on two consecutive post-burn-in quizzes.
- **Bonus gate**: ≥ 4 first-try correct in the first 5 answers.
  Sticky — revisits can't retract.
- **Replay-from-scratch**: `_recompute_adaptive` walks the full answer
  trace on every submit; revisits stay deterministic.

Variant-schema decision (see `roadmap/ADAPTIVE_VARIANT_SCHEMA.md`):
current shipped scope uses three pre-composed buckets per question
(Option A). Option D (axis-level overrides with render-time composition)
is documented as a future move if the research story expands.
