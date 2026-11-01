from __future__ import annotations

import time

import numpy as np
from medfire_watch.browser_camera import BrowserCameraMonitor


class _Detector:
    def __init__(self) -> None:
        self.shapes: list[tuple[int, ...]] = []

    def predict(self, image: np.ndarray) -> dict:
        self.shapes.append(image.shape)
        return {"detections": [{"class": "smoke", "confidence": 0.9, "xyxy": [20, 20, 180, 180]}]}


def test_browser_camera_detector_is_resized_but_boxes_are_full_resolution() -> None:
    monitor = BrowserCameraMonitor(detector_width=960)
    detector = _Detector()
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    result = monitor.process(image, detector)
    assert detector.shapes == [(540, 960, 3)]
    assert result["detections"][0]["xyxy"] == [40.0, 40.0, 360.0, 360.0]


def test_browser_camera_requires_persistent_overlapping_detection_before_snapshot() -> None:
    monitor = BrowserCameraMonitor(detector_width=960)
    monitor.tracker.seconds = 0.01
    detector = _Detector()
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    first = monitor.process(image, detector)
    time.sleep(0.03)
    second = monitor.process(image, detector)
    assert first["alert_id"] is None
    assert second["alert_id"]


def test_full_resolution_photo_scales_pending_detector_coordinates_without_mutation(monkeypatch):
    monitor = BrowserCameraMonitor()
    detection = {'class': 'fire', 'confidence': .9, 'xyxy': [300, 150, 600, 450]}
    monitor._pending['event'] = {'detections': [detection], 'alert': {'detection': detection},
                                 'image_width': 960, 'image_height': 540}
    queued = []
    monkeypatch.setattr(monitor._queue, 'put_nowait', queued.append)
    assert monitor.submit_full_resolution_snapshot('event', np.zeros((720, 1280, 3), dtype=np.uint8))
    image, boxes, alert = queued[0]
    assert image.shape == (720, 1280, 3)
    assert boxes[0]['xyxy'] == [400, 200, 800, 600]
    assert alert['detection']['xyxy'] == [400, 200, 800, 600]
    assert detection['xyxy'] == [300, 150, 600, 450]


def test_response_declares_submitted_image_coordinate_space():
    result = BrowserCameraMonitor().process(np.zeros((540, 960, 3), dtype=np.uint8), _Detector())
    assert (result['image_width'], result['image_height']) == (960, 540)
    assert result['coordinate_space'] == 'submitted_image_pixels'
