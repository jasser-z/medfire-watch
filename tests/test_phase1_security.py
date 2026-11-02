from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from alerts.manager import AlertManager
from api.main import app
from api.services import get_alert_manager, get_detection_service
from fastapi.testclient import TestClient
from PIL import Image


class FakeDetectionService:
    confidence_threshold = 0.3
    consecutive_alert_frames = 5
    max_video_upload_bytes = 100 * 1024 * 1024
    max_video_duration_seconds = 120

    def predict(self, image: np.ndarray) -> dict[str, object]:
        return {
            "detections": [{"class": "fire", "confidence": 0.8, "xyxy": [1.0, 2.0, 8.0, 9.0]}],
            "speed_ms": {"inference": 5.0},
            "device": "cpu",
            "confidence_threshold": self.confidence_threshold,
        }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("alerts.manager.get_setting", lambda name: None)
    app.dependency_overrides[get_detection_service] = FakeDetectionService
    app.dependency_overrides[get_alert_manager] = lambda: AlertManager(state_path=tmp_path / "state.json")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_foreign_host_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Foreign host rejected with 400
    res = client.get("/health", headers={"host": "evil.com"})
    assert res.status_code == 400
    assert "not allowed" in res.json()["detail"]

    res_port = client.get("/health", headers={"host": "attacker.org:8000"})
    assert res_port.status_code == 400

    # Local hosts allowed
    res_local = client.get("/health", headers={"host": "localhost:8000"})
    assert res_local.status_code == 200

    res_ip = client.get("/health", headers={"host": "127.0.0.1:8000"})
    assert res_ip.status_code == 200

    res_ipv6 = client.get("/health", headers={"host": "[::1]:8000"})
    assert res_ipv6.status_code == 200

    # Allowed via MEDFIRE_ALLOWED_HOSTS
    monkeypatch.setenv("MEDFIRE_ALLOWED_HOSTS", "custom.domain.local, other.domain.org:9000")
    res_custom = client.get("/health", headers={"host": "custom.domain.local"})
    assert res_custom.status_code == 200
    res_custom_port = client.get("/health", headers={"host": "other.domain.org:9000"})
    assert res_custom_port.status_code == 200


def test_cross_origin_post_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Cross-origin POST rejected with 403
    res = client.post("/video-test/prepare", headers={"origin": "http://evil.com"})
    assert res.status_code == 403
    assert "Cross-origin" in res.json()["detail"]

    # Same-origin POST allowed (host is testserver for TestClient)
    res_same = client.post("/video-test/prepare", headers={"origin": "http://testserver"})
    assert res_same.status_code == 200

    # Dashboard origin allowed (localhost:8501)
    res_dash = client.post("/video-test/prepare", headers={"host": "localhost:8000", "origin": "http://localhost:8501"})
    assert res_dash.status_code == 200

    # Allowed via MEDFIRE_ALLOWED_ORIGINS
    monkeypatch.setenv("MEDFIRE_ALLOWED_ORIGINS", "https://trusted-dashboard.com")
    res_custom = client.post("/video-test/prepare", headers={"origin": "https://trusted-dashboard.com"})
    assert res_custom.status_code == 200

    # GET request with cross-origin is not blocked by origin check
    res_get = client.get("/health", headers={"origin": "http://evil.com"})
    assert res_get.status_code == 200


def test_no_origin_post_allowed(client: TestClient) -> None:
    # POST without Origin header is allowed
    res = client.post("/video-test/prepare")
    assert res.status_code == 200


def test_token_required_when_set(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "secure-api-key")

    # DELETE /alerts/history requires token
    res_del_no_token = client.delete("/alerts/history")
    assert res_del_no_token.status_code == 401

    res_del_bad_token = client.delete("/alerts/history", headers={"x-medfire-token": "wrong"})
    assert res_del_bad_token.status_code == 401

    res_del_good = client.delete("/alerts/history", headers={"x-medfire-token": "secure-api-key"})
    assert res_del_good.status_code == 200

    # POST /video-test/prepare requires token
    res_post_no_token = client.post("/video-test/prepare")
    assert res_post_no_token.status_code == 401

    res_post_good = client.post("/video-test/prepare", headers={"x-medfire-token": "secure-api-key"})
    assert res_post_good.status_code == 200


def test_oversized_and_huge_dimension_camera_upload_rejected(client: TestClient) -> None:
    # Oversized upload (> 10 MiB)
    oversized = b"A" * (10 * 1024 * 1024 + 2)
    res = client.post(
        "/live-camera/detect",
        files={"image": ("frame.jpg", oversized, "image/jpeg")},
    )
    assert res.status_code == 413
    assert "10 MiB" in res.json()["detail"]

    # Huge-dimension camera upload (> 25 megapixels)
    huge_img = Image.new("RGB", (5001, 5001), color="red")
    buf = BytesIO()
    huge_img.save(buf, format="JPEG")
    huge_bytes = buf.getvalue()

    res_dim = client.post(
        "/live-camera/detect",
        files={"image": ("huge.jpg", huge_bytes, "image/jpeg")},
    )
    assert res_dim.status_code == 413
    assert "25-megapixel" in res_dim.json()["detail"]


def test_detect_chat_with_two_chats_raises_lookup_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import alerts.manager as manager_module

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")

    class MockResponse:
        def __init__(self, updates: list) -> None:
            self._updates = updates

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"ok": True, "result": self._updates}

    # Case 1: Two distinct private chats -> raises LookupError
    two_chats_updates = [
        {"message": {"chat": {"type": "private", "id": 11111}}},
        {"message": {"chat": {"type": "private", "id": 22222}}},
    ]
    monkeypatch.setattr(manager_module.requests, "get", lambda *a, **k: MockResponse(two_chats_updates))
    manager = AlertManager(state_path=tmp_path / "state.json")

    with pytest.raises(LookupError, match="Multiple private chats found"):
        manager.detect_chat()

    # Case 2: One distinct private chat (even if multiple updates) -> succeeds
    one_chat_multiple_updates = [
        {"message": {"chat": {"type": "private", "id": 11111}}},
        {"message": {"chat": {"type": "private", "id": 11111}}},
    ]
    monkeypatch.setattr(manager_module.requests, "get", lambda *a, **k: MockResponse(one_chat_multiple_updates))
    saved_ids: list[str] = []
    monkeypatch.setattr(manager, "_save_chat_id", lambda cid: saved_ids.append(cid))
    chat_id = manager.detect_chat()
    assert chat_id == "11111"
    assert saved_ids == ["11111"]

    # Case 3: Zero private chats -> raises LookupError
    zero_chats_updates = [
        {"message": {"chat": {"type": "group", "id": 99999}}},
    ]
    monkeypatch.setattr(manager_module.requests, "get", lambda *a, **k: MockResponse(zero_chats_updates))
    with pytest.raises(LookupError, match="No private chat was found"):
        manager.detect_chat()

