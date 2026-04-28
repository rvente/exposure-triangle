.PHONY: setup serve atlas atlas-static freeze serve-static test test-e2e test-freeze clean

setup:
	uv sync
	uv run playwright install chromium

serve:
	uv run flask --app app run --debug --port 5000

atlas:
	uv run python tests/atlas_server.py

atlas-static:
	uv run python tests/build_atlas_static.py

freeze:
	uv run python freeze.py

serve-static: freeze
	cd _static_build && python3 -m http.server 8000

test:
	uv run pytest tests/test_reducer.py -v

test-e2e:
	xvfb-run -a uv run pytest tests/test_e2e.py -v

test-freeze:
	uv run pytest tests/test_freeze.py -v

clean:
	rm -rf instance __pycache__ .pytest_cache tests/__pycache__ _static_build
