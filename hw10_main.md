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
(`hw10_warmup.pdf` in this repo; PowerPoint source is
`exposure_triangle.pptx`). The implementation lines up 1:1 with it.

## What I did this week

- **Scaffolded the Flask app.** `app.py` exposes `/`, `/learn/<n>`, `/quiz/<n>`, `/result`, plus `POST` endpoints that persist user choices on every page.
- **Separated concerns.** `reducer.py` is a pure function `reduce(state, event, now_ms, *, answer_key)`; `state_store.py` persists sessions keyed by cookie in SQLite (`instance/state.db`).
- **Ported content to JSON.** `data/lessons.json` (3 lessons) and `data/quizzes.json` (5 quizzes with second-chance mechanic). No content is hard-coded in HTML — each route renders from the JSON.
- **Tests.** Reducer unit tests cover state transitions and scoring edge cases. Playwright e2e test walks the full click-through under `xvfb-run`.

## Rubric checklist

- [x] Flask backend, HTML/JS/jQuery/Bootstrap frontend.
- [x] Home screen with Start button.
- [x] Backend stores user choices on every page (quiz answers + lesson entry timestamps, via `state_store.py`).
- [x] Content in JSON (`data/lessons.json`, `data/quizzes.json`), rendered into templates — not hard-coded.
- [x] 4 routes: `/`, `/learn/<n>`, `/quiz/<n>`, `/result`.
- [x] Each page shows data, gives instructions, records data, and advances.
- [x] Quiz result page shows score reflecting correct/incorrect answers.
- [x] Single-user assumption (session cookie keyed).
