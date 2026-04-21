---
title: "HW10 Main — Technical Prototype"
subtitle: "Exposure Triangle — click-through Flask prototype"
author: "Blake Vente (rv2459)"
date: "April 20, 2026"
---

## Prototype

Continuation of the HW9 low-fidelity prototype, now implemented as a Flask
application with an HTML/JS/jQuery/Bootstrap frontend. Learning arc + quiz
arc are reachable end-to-end; the click-through walks every screen the rubric
requires (home → 3 lessons → 5 quizzes → result).

- **Repo.** <https://github.com/rvente/exposure-triangle>
- **Run locally.** `uv sync && uv run playwright install chromium && uv run flask --app app run --port 5000` — opens on `localhost:5000`.
- **Main entry.** `/` (home + Start button).

## Video

~1 min click-through: <https://youtu.be/17tHtb9QTxc>

## Group — responsibilities

Solo CVN group of 1 — every role below was filled by me (Blake Vente, rv2459).

| Part | Role | Person |
|---|---|---|
| 1. Learning | Architecting the data (`data/lessons.json`) | Blake Vente |
| 1. Learning | Implementing the UI (`templates/home.html`, `templates/learn.html`) | Blake Vente |
| 1. Learning | Testing the click-through (`tests/test_e2e.py` — learning leg) | Blake Vente |
| 2. Quiz | Architecting the data (`data/quizzes.json`) | Blake Vente |
| 2. Quiz | Implementing the UI (`templates/quiz.html`, `templates/result.html`) | Blake Vente |
| 2. Quiz | Testing the click-through (`tests/test_e2e.py` — quiz leg) | Blake Vente |
| — | State + scoring logic (`reducer.py`, `state_store.py`) | Blake Vente |

## Low-fidelity prototype

The final low-fi prototype was submitted with the HW10 warm-up
(`writeup/hw10_warmup.pdf`; PowerPoint source is
`writeup/exposure_triangle.pptx`). The HW10 technical prototype covers the
core teaching-and-quiz flow shown in the lo-fi.

**Not yet implemented (next up, HW11):** the lo-fi also sketches an adaptive-
difficulty path where wrong quiz answers route the learner to an easier
variant and right answers unlock harder variants. For HW10 the quiz uses a
fixed 5-question sequence with a second-chance mechanic (first wrong grays
out the option; second wrong reveals the correct answer). The adaptive
branching is the primary HW11 iteration.

## What I did this week

- **Scaffolded the Flask app.** `app.py` exposes `/`, `/learn/<n>`, `/quiz/<n>`, `/result`, plus `POST` endpoints that persist user choices on every page.
- **Separated concerns.** `reducer.py` is a pure function `reduce(state, event, now_ms, *, answer_key)`; `state_store.py` persists sessions keyed by cookie in SQLite (`instance/state.db`).
- **Ported content to JSON.** `data/lessons.json` (3 lessons) and `data/quizzes.json` (5 quizzes with second-chance mechanic). No content is hard-coded in HTML — each route renders from the JSON.
- **Tests.** Reducer unit tests cover state transitions and scoring edge cases. Playwright e2e test walks the full click-through under `xvfb-run`.

## Note on the reducer

Writing the core as a `reduce(state, event)` pure function looks like
overkill for an app this small, but the call paid for itself quickly:

1. **Speed.** The reducer was fast to write — once the state shape was
   named, each event became a 3–5 line case. The bulk of the work was
   content (lessons + quizzes JSON), not control flow.
2. **Testability under branching paths.** Adaptive difficulty (HW11) turns
   the quiz into a branching tree rather than a fixed sequence. A pure
   reducer means I can unit-test every branch in isolation without
   spinning up Flask, Playwright, or a DB — just feed it events and assert
   on the returned state.
3. **Two-backend symmetry → local-first deployment.** The `Backend`
   interface (`static/js/backend.js`) has a `FlaskBackend` and a stub
   `LocalBackend`. Because the reducer is pure JS/Python-portable logic,
   the `LocalBackend` can run the same transitions entirely in the browser
   with `localStorage` — no server required. That lets the site be
   statically served (e.g. Cloudflare Pages) and run local-first, which
   matters for learner accessibility: no account, no network, no
   tracking. The reducer is the shared kernel that makes both paths real.

## Rubric checklist

- [x] Flask backend, HTML/JS/jQuery/Bootstrap frontend.
- [x] Home screen with Start button.
- [x] Backend stores user choices on every page (quiz answers + lesson entry timestamps, via `state_store.py`).
- [x] Content in JSON (`data/lessons.json`, `data/quizzes.json`), rendered into templates — not hard-coded.
- [x] 4 routes: `/`, `/learn/<n>`, `/quiz/<n>`, `/result`.
- [x] Each page shows data, gives instructions, records data, and advances.
- [x] Quiz result page shows score reflecting correct/incorrect answers.
- [x] Single-user assumption (session cookie keyed).
