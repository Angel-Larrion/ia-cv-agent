import os

# Must be set before app.py is imported: it reads these at import time
os.environ["AGENT_API_KEY"] = "test-key"
os.environ["RATE_LIMIT_PER_MIN"] = "1000"
os.environ["GEMINI_API_KEY"] = "fake-key-for-tests"

import pytest
from fastapi.testclient import TestClient

import app as app_module

HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture
def client(monkeypatch):
    """Test client with Gemini replaced by a fixed answer; no network is used."""
    app_module.recent_requests.clear()
    monkeypatch.setattr(app_module.agente, "responder", lambda mensajes: "respuesta simulada")
    return TestClient(app_module.app)
