import json
from datetime import datetime, timezone

import api.routers.detection as routes
import pytest
from alerts.manager import AlertManager
from api.main import app
from fastapi.testclient import TestClient


def test_camera_interval_is_shared_and_reset_preserves_history(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    manager = AlertManager(state_path=state)
    worker = AlertManager(state_path=state)
    now = datetime.now(timezone.utc).isoformat()
    state.write_text(json.dumps({"live_camera": now, "other_alert": now}))
    manager.log_path.write_text("historical delivery\n")
    monkeypatch.setattr("alerts.manager.get_setting", lambda key: "test-credential")
    assert worker.send("camera", "live_camera", "live_camera")["reason"] == "cooldown"
    manager.set_camera_cooldown(0)
    assert worker.camera_cooldown() == 0
    assert AlertManager(state_path=state).status()["camera_cooldown_minutes"] == 0
    manager.set_camera_cooldown(15)
    manager.reset_camera_cooldown()
    assert json.loads(state.read_text()) == {"other_alert": now}
    assert manager.log_path.read_text() == "historical delivery\n"
    assert worker.send("other", "test", "other_alert")["reason"] == "cooldown"

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 123}}

    monkeypatch.setattr("alerts.manager.requests.post", lambda *args, **kwargs: Response())
    assert worker.send("camera", "live_camera", "live_camera")["sent"] is True
    assert worker.send("camera", "live_camera", "live_camera")["reason"] == "cooldown"


def test_camera_cooldown_api_validates_and_clears_only_cooldown_notice(tmp_path, monkeypatch):
    manager = AlertManager(state_path=tmp_path / "state.json")
    monkeypatch.setattr(routes, "get_alert_manager", lambda: manager)
    monkeypatch.setattr(routes._browser_camera_monitor, "last_error", "Camera alert was suppressed by cooldown.")
    client = TestClient(app)
    assert client.get("/live-camera/cooldown").json() == {"minutes": 5}
    assert client.put("/live-camera/cooldown", json={"minutes": 12}).json() == {"minutes": 12}
    for invalid in [-1, 1441, 1.5, True, "5"]:
        assert client.put("/live-camera/cooldown", json={"minutes": invalid}).status_code == 422
    assert client.post("/live-camera/cooldown/reset").json() == {"reset": True}
    assert routes._browser_camera_monitor.last_error is None
    routes._browser_camera_monitor.last_error = "Network unavailable"
    assert client.post("/live-camera/cooldown/reset").status_code == 200
    assert routes._browser_camera_monitor.last_error == "Network unavailable"


def test_camera_settings_require_token_when_authentication_enabled(tmp_path, monkeypatch):
    manager = AlertManager(state_path=tmp_path / "state.json")
    monkeypatch.setattr(routes, "get_alert_manager", lambda: manager)
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "audit-test-token")
    client = TestClient(app)
    assert client.put("/live-camera/cooldown", json={"minutes": 12}).status_code == 401
    assert client.post("/live-camera/cooldown/reset").status_code == 401
    assert not manager.camera_settings_path.exists()
    response = client.put(
        "/live-camera/cooldown", json={"minutes": 12}, headers={"X-MedFire-Token": "audit-test-token"}
    )
    assert response.status_code == 200
    assert response.json() == {"minutes": 12}


@pytest.mark.parametrize("minutes", [-1, 1441, 1.5, True])
def test_invalid_interval_does_not_write_settings(tmp_path, minutes):
    manager = AlertManager(state_path=tmp_path / "state.json")
    with pytest.raises(ValueError):
        manager.set_camera_cooldown(minutes)
    assert not manager.camera_settings_path.exists()
