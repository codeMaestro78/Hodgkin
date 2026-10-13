from fastapi.testclient import TestClient

from research_api.main import app


def test_health_alias_matches_liveness() -> None:
    client = TestClient(app)

    assert client.get("/health").json() == {
        "status": "ok",
        "service": "research-api",
    }
    assert client.get("/health/live").json() == {
        "status": "ok",
        "service": "research-api",
    }
