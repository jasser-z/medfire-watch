from api.main import app
from fastapi.testclient import TestClient


def test_text_alert_routes_are_removed():
    with TestClient(app) as client:
        for path in ("/alerts/digest", "/telegram/test", "/alerts/fire-danger"):
            assert client.post(path).status_code == 404
