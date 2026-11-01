from __future__ import annotations

import traceback
from pathlib import Path

import numpy as np
import pytest
import requests
from alerts.manager import AlertManager
from medfire_watch.browser_camera import BrowserCameraMonitor
from medfire_watch.live_alert import PersistentDetectionAlert


def test_persistence_uses_elapsed_time_and_overlap() -> None:
    detection = {"class": "fire", "confidence": 0.9, "xyxy": [0, 0, 10, 10]}
    for interval in (0.1, 0.5):
        tracker = PersistentDetectionAlert(seconds=1, min_iou=0.3)
        result = None
        for i in range(round(1 / interval) + 1):
            result = tracker.update([detection], i * interval)
        assert result is not None
        assert result["alert_seconds"] == pytest.approx(1)
    tracker = PersistentDetectionAlert(seconds=1, min_iou=0.3)
    tracker.update([detection], 0)
    unrelated = {**detection, "xyxy": [50, 50, 60, 60]}
    assert tracker.update([unrelated], 1) is None
    assert tracker.update([], 2) is None
    assert not tracker.alerted


def test_telegram_network_exception_tracebacks_do_not_expose_token(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    token = "fake-token-for-redaction-check"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    def fail(*args, **kwargs):
        raise requests.ConnectionError(f"https://api.telegram.org/bot{token}/sendPhoto")

    monkeypatch.setattr(requests, "post", fail)
    manager = AlertManager(state_path=tmp_path / "state.json")
    with pytest.raises(RuntimeError) as error:
        manager.send("test", "test", "test")
    assert token not in "".join(traceback.format_exception(error.value))


def test_camera_sender_retries_and_records_safe_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manager = AlertManager(state_path=tmp_path / "state.json")
    calls = []

    def fake_send(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise RuntimeError("private upstream details must not be logged")
        return {"sent": True}

    monkeypatch.setattr(manager, "send", fake_send)
    monkeypatch.setattr(AlertManager, "from_config", lambda path: manager)
    monkeypatch.setattr("medfire_watch.browser_camera.time.sleep", lambda seconds: None)
    monkeypatch.setattr("medfire_watch.browser_camera.PROJECT_ROOT", tmp_path)
    processor = BrowserCameraMonitor()
    frame = np.full((100, 100, 3), 80, dtype=np.uint8)
    detection = {"class": "fire", "confidence": 0.9, "xyxy": [10, 10, 60, 60]}
    processor._queue.put((frame, [detection], {"detection": detection}))
    processor._queue.join()
    assert len(calls) == 3
    assert calls[-1]["photo"].is_file()
    attempts = manager.attempt_log()
    assert len(attempts) == 2 and all(not item["confirmed"] for item in attempts)
    assert "private upstream details" not in manager.failure_log_path.read_text()
