from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from medfire_watch.video import ConsecutiveDetectionAlert, iter_video_detections


def test_alert_requires_consecutive_positive_frames_and_rearms_after_gap() -> None:
    tracker = ConsecutiveDetectionAlert(3)
    assert tracker.update(True, 0.0) is None
    assert tracker.update(True, 0.1) is None
    assert tracker.update(False, 0.2) is None
    assert tracker.update(True, 0.3) is None
    assert tracker.update(True, 0.4) is None
    alert = tracker.update(True, 0.5)
    assert alert == {
        "first_detection_seconds": 0.3,
        "alert_seconds": 0.5,
        "consecutive_frames": 3,
    }
    assert tracker.update(True, 0.6) is None
    assert tracker.alerted
    assert tracker.update(False, 0.7) is None
    assert not tracker.alerted


def test_video_processor_writes_annotated_video_and_reports_alert(tmp_path: Path) -> None:
    input_path = tmp_path / "input.mp4"
    output_path = tmp_path / "annotated.mp4"
    writer = cv2.VideoWriter(
        str(input_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10,
        (64, 48),
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 encoder is unavailable.")
    for _ in range(5):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()

    def fake_inference(frame: np.ndarray) -> dict[str, object]:
        return {
            "detections": [{"class": "smoke", "confidence": 0.9, "xyxy": [5, 6, 30, 35]}],
            "speed_ms": {},
            "device": "cpu",
            "confidence_threshold": 0.3,
        }

    events = list(
        iter_video_detections(
            input_path,
            output_path,
            fake_inference,
            consecutive_frames=3,
        )
    )
    progress_events = [event for event in events if event["type"] == "progress"]
    summary = events[-1]
    assert progress_events
    assert all("frame_jpeg_b64" not in event for event in progress_events)
    assert summary["frames_processed"] == 5
    assert summary["detection_timeline"] == [{"start_seconds": 0, "end_seconds": 0}]
    assert summary["alert_count"] == 1
    assert summary["first_alert"] == {
        "first_detection_seconds": 0.0,
        "alert_seconds": 0.2,
        "consecutive_frames": 3,
    }
    assert summary["output_video_ready"]
    assert output_path.is_file()
    capture = cv2.VideoCapture(str(output_path))
    assert capture.isOpened()
    assert capture.get(cv2.CAP_PROP_FRAME_COUNT) == 5
    capture.release()
