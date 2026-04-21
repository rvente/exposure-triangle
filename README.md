# The Exposure Triangle

Interactive teaching prototype covering the three pillars of photographic exposure: **Camera Iris** (aperture), **Capture Duration** (shutter speed), and **Sensor Sensitivity** (ISO).

Built as part of COMSW4170 (User Interface Design) at Columbia CVN, Spring 2026.

## Contents

| Path | Purpose |
|------|---------|
| `writeup/exposure_triangle.pptx` | Lo-Fi prototype as PowerPoint; opens in PowerPoint or imports into Google Slides |
| `writeup/hw10_warmup.pdf` | HW10 warm-up submission — iteration rationale and HW10 main-assignment implementation plan |
| `writeup/hw10_main.md`, `writeup/hw10_main.pdf` | HW10 main submission writeup — responsibilities, video link, rubric checklist |
| `app.py`, `reducer.py`, `state_store.py`, `templates/`, `static/`, `data/` | HW10 main — Flask technical prototype |
| `tests/` | Reducer unit tests + Playwright click-through e2e test |

## Run the Flask prototype

```
uv sync
uv run playwright install chromium
uv run flask --app app run --port 5000
```

Open <http://127.0.0.1:5000/> and click **Start**.

## Tests

```
uv run pytest tests/test_reducer.py -v
xvfb-run -a uv run pytest tests/test_e2e.py -v
```

## Flow

1. `/` — Start button; creates a session and redirects to `/learn/1`.
2. `/learn/1..3` — three lesson pages (iris, shutter, ISO).
3. `/quiz/1..5` — five quizzes. First wrong answer grays out the option and allows a retry; the second wrong answer locks the question and reveals the correct choice.
4. `/result` — final score.

## License

All rights reserved.
