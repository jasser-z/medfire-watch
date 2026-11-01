"""Non-blocking browser-camera detection and Telegram photo delivery."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any

import cv2
import numpy as np
from alerts.manager import AlertManager

from medfire_watch.config import PROJECT_ROOT
from medfire_watch.coordinates import scale_detections
from medfire_watch.drawing import draw_detections
from medfire_watch.live_alert import PersistentDetectionAlert


class BrowserCameraMonitor:
    """Accept small detector frames without ever pacing the browser video element."""

    def __init__(self, detector_width: int = 960) -> None:
        self.detector_width = max(320, detector_width)
        self.tracker = PersistentDetectionAlert(seconds=1.0, min_iou=0.3)
        self.alert_confidence = 0.5
        self.alert_min_box_fraction = 0.01
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._times: deque[float] = deque(maxlen=40)
        self._queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]] = queue.Queue(maxsize=8)
        self.delivery_count = 0
        self.failure_count = 0
        self.last_error: str | None = None
        self._sender = threading.Thread(target=self._send, name="browser-camera-alert-sender", daemon=True)
        self._sender.start()

    def process(self, image: np.ndarray, detector: Any) -> dict[str, Any]:
        height, width = image.shape[:2]
        scale = min(self.detector_width / max(width, 1), 1.0)
        reduced = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else image
        started = time.monotonic()
        result = detector.predict(reduced)
        detections = scale_detections(result["detections"], (reduced.shape[1], reduced.shape[0]), (width, height))
        candidates = [
            item for item in detections
            if item["class"] in {"fire", "smoke"}
            and float(item["confidence"]) >= self.alert_confidence
            and (
                max(0, item["xyxy"][2] - item["xyxy"][0])
                * max(0, item["xyxy"][3] - item["xyxy"][1])
                / max(width * height, 1)
                >= self.alert_min_box_fraction
            )
        ]
        now = time.monotonic()
        with self._lock:
            alert = self.tracker.update(candidates, now - self.started)
            alert_id = None
            if alert is not None:
                alert_id = uuid.uuid4().hex
                self._pending[alert_id] = {"detections": detections, "alert": alert, "expires": now + 8,
                                           "image_width": width, "image_height": height}
            self._pending = {key: value for key, value in self._pending.items() if value["expires"] >= now}
            self._times.append(now)
            updates = (len(self._times) - 1) / max(self._times[-1] - self._times[0], 1e-6) if len(self._times) > 1 else 0.0
        return {
            "detections": detections,
            "image_width": width,
            "image_height": height,
            "coordinate_space": "submitted_image_pixels",
            "alert_id": alert_id,
            "detector_ms": round((time.monotonic() - started) * 1000),
            "updates_per_second": round(updates, 2),
            "alert_active": self.tracker.alerted,
        }

    def submit_full_resolution_snapshot(self, alert_id: str, image: np.ndarray) -> bool:
        with self._lock:
            item = self._pending.pop(alert_id, None)
        if item is None:
            return False
        source_size = (item["image_width"], item["image_height"])
        target_size = (image.shape[1], image.shape[0])
        detections = scale_detections(item["detections"], source_size, target_size)
        alert = dict(item["alert"])
        alert["detection"] = scale_detections([alert["detection"]], source_size, target_size)[0]
        try:
            self._queue.put_nowait((image.copy(), detections, alert))
        except queue.Full:
            self.last_error = "Camera alert queue is full."
            self.failure_count += 1
            AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml").record_failure("live_camera", 0, "Queue full")
            return False
        return True

    def status(self) -> dict[str, Any]:
        return {"delivered": self.delivery_count, "failed": self.failure_count, "last_error": self.last_error}

    def _send(self) -> None:
        while True:
            image, detections, alert = self._queue.get()
            try:
                folder = PROJECT_ROOT / "runs" / "webcam_alerts"
                folder.mkdir(parents=True, exist_ok=True)
                photo = folder / f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
                if not cv2.imwrite(str(photo), draw_detections(image, detections)):
                    raise OSError("Snapshot encode failed")
                detection = alert["detection"]
                caption = (f"Live camera · {datetime.now().astimezone().isoformat(timespec='seconds')} · "
                           f"{detection['class']} · confidence {float(detection['confidence']):.0%}")
                manager = AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml")
                dedupe = f"live_camera:{uuid.uuid4().hex}"
                for attempt in range(1, 4):
                    try:
                        sent = manager.send(caption, kind="live_camera", dedupe_key=dedupe, photo=photo)
                        if sent.get("sent"):
                            self.delivery_count += 1
                            self.last_error = None
                            break
                        self.last_error = "Camera alert was suppressed by cooldown."
                        break
                    except Exception as exc:
                        self.last_error = f"Telegram delivery failed ({type(exc).__name__})."
                        manager.record_failure("live_camera", attempt, "Delivery failed; check configuration and network", photo.name)
                        if attempt == 3:
                            self.failure_count += 1
                        else:
                            time.sleep(2 ** (attempt - 1))
            except Exception as exc:
                self.last_error = f"Camera alert failed ({type(exc).__name__})."
                self.failure_count += 1
            finally:
                self._queue.task_done()
