import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from app import create_app  # noqa: E402


@pytest.fixture
def app(tmp_path):
    db = tmp_path / "state.db"
    flask_app = create_app(db_path=str(db))
    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
