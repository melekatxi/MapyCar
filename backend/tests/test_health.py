from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_includes_request_id_header() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert "X-Request-ID" in response.headers
