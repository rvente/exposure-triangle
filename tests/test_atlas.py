"""Smoke-test the atlas harness — every frame renders 200."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_server import _frame_catalog, build_app  # noqa: E402


@pytest.fixture(scope="module")
def atlas_client():
    app = build_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_atlas_index_lists_every_frame(atlas_client):
    r = atlas_client.get("/_atlas/")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    for slug, _title, _desc, _builder in _frame_catalog():
        assert f"/_atlas/frame/{slug}" in body, f"atlas index missing {slug}"


@pytest.mark.parametrize("slug", [s for s, *_ in _frame_catalog()])
def test_atlas_frame_renders(atlas_client, slug):
    r = atlas_client.get(f"/_atlas/frame/{slug}")
    assert r.status_code == 200, f"{slug} returned {r.status_code}"
    assert r.data  # non-empty body


def test_unknown_frame_404s(atlas_client):
    r = atlas_client.get("/_atlas/frame/does-not-exist")
    assert r.status_code == 404
