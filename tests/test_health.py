from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok():
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_documented_in_openapi():
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    assert "/health" in schema["paths"]
