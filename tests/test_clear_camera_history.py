import json

import api.routers.alerts as api
from alerts.manager import AlertManager
from api.main import app
from fastapi.testclient import TestClient


def test_delete_all_clears_attempts_and_only_camera_snapshots(tmp_path, monkeypatch):
    manager = AlertManager(state_path=tmp_path / "alerts" / "state.json")
    manager.state_path.parent.mkdir()
    manager.state_path.write_text('{"camera_event": "2026-10-31T00:00:00+00:00"}')
    manager.state_path.with_name("unrelated_config.json").write_text('{"keep": true}')
    manager.log_path.write_text(json.dumps({"kind": "live_camera", "confirmed": True}) + "\n")
    manager.record_failure("live_camera", 1, "Network unavailable", "alert_old.jpg")
    photos = tmp_path / "runs" / "webcam_alerts"
    photos.mkdir(parents=True)
    (photos / "alert_old.jpg").write_bytes(b"image")
    (photos / "unrelated.jpg").write_bytes(b"preserve")
    nested = photos / "nested"
    nested.mkdir()
    (nested / "alert_keep.jpg").write_bytes(b"preserve")
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    app.dependency_overrides[api.get_alert_manager] = lambda: manager
    try:
        client = TestClient(app)
        response = client.delete("/alerts/history")
        assert response.status_code == 200
        assert response.json() == {"deleted_attempts": 2, "deleted_snapshots": 1, "remaining_snapshots": 0}
        assert client.get("/alerts/log").json()["messages"] == []
        assert client.post("/alerts/snapshots/alert_old.jpg/send").status_code == 404
        assert not (photos / "alert_old.jpg").exists()
        assert (photos / "unrelated.jpg").read_bytes() == b"preserve"
        assert (nested / "alert_keep.jpg").exists()
        assert "camera_event" in manager.state_path.read_text()
        assert manager.state_path.with_name("unrelated_config.json").read_text() == '{"keep": true}'
        # Retries for deleted photos stay cleared, but subsequent camera events are recorded.
        manager.record_failure("live_camera", 2, "Network unavailable", "alert_old.jpg")
        assert manager.attempt_log() == []
        (photos / "alert_new.jpg").write_bytes(b"new image")
        manager.record_failure("live_camera", 1, "Network unavailable", "alert_new.jpg")
        assert len(manager.attempt_log()) == 1
    finally:
        app.dependency_overrides.clear()


def test_delete_during_delivery_does_not_restore_old_history(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    import alerts.manager as manager_module
    import requests

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 31, 1, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(manager_module, "datetime", Clock)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "unit-test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "unit-test-chat")
    manager = AlertManager(state_path=tmp_path / "state.json")
    photo = tmp_path / "alert_inflight.jpg"
    photo.write_bytes(b"photo payload")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 123}}

    def deliver(*args, **kwargs):
        assert kwargs["files"]["photo"][1] == b"photo payload"
        manager.clear_history(tmp_path)
        assert not photo.exists()  # No network-held image handle prevents deletion on Windows.
        return Response()

    monkeypatch.setattr(requests, "post", deliver)
    result = manager.send("Live camera", "live_camera", "event", photo=photo)
    assert result["sent"] is True
    assert manager.attempt_log() == []
    assert "event" in manager.state_path.read_text()  # Preserve cooldown despite history deletion.
