from fastapi.testclient import TestClient

from app.main import app


def test_not_found_uses_standard_error_shape() -> None:
    client = TestClient(app)
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    for field in ("type", "title", "status", "code", "detail", "instance", "request_id", "errors"):
        assert field in body
    assert body["status"] == 404


def test_validation_error_lists_fields() -> None:
    client = TestClient(app)
    response = client.post("/api/v1/auth/login", json={"email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert len(body["errors"]) > 0
