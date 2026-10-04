"""Happy-path test for GET /health."""

from datetime import datetime

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_returns_200_and_payload() -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__

    # Timestamp should parse as ISO 8601.
    parsed = datetime.fromisoformat(body["timestamp"])
    assert parsed.tzinfo is not None
