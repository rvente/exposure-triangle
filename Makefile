.PHONY: setup serve test test-e2e clean

setup:
	uv sync
	uv run playwright install chromium

serve:
	uv run flask --app app run --debug --port 5000

test:
	uv run pytest tests/test_reducer.py -v

test-e2e:
	xvfb-run -a uv run pytest tests/test_e2e.py -v

clean:
	rm -rf instance __pycache__ .pytest_cache tests/__pycache__
