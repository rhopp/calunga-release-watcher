import json
import os
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests requiring Vertex AI credentials")


@pytest.fixture(autouse=True)
def _require_vertex():
    project = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        pytest.skip("ANTHROPIC_VERTEX_PROJECT_ID / GOOGLE_CLOUD_PROJECT not set — skipping e2e")


@pytest.fixture()
def load_fixture():
    def _load(name: str) -> dict:
        path = FIXTURES_DIR / name
        with open(path) as f:
            return json.load(f)
    return _load
