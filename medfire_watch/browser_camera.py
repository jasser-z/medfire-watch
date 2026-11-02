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
import yaml
from alerts.manager import AlertManager

from medfire_watch.config import PROJECT_ROOT
from medfire_watch.coordinates import scale_detections
from medfire_watch.drawing import draw_detections
from medfire_watch.live_alert import PersistentDetectionAlert

MAX_QUEUE_BYTES = 256 * 1024 * 1024  # 256 MB byte budget


def _load_live_alert_defaults() -> dict[str, float]:
    cfg_path = PROJECT_ROOT / "configs" / "detection.yaml"
    if cfg_path.is_file():
        try:
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            live = data.get("live_alert", {})
            return {
                "confidence": float(live.get("confidence", 0.5)),
                "min_box_fraction": float(live.get("min_box_fraction", 0.01)),
                "persistence_seconds": float(live.get("persistence_seconds", 1.0)),
                "min_iou": float(live.get("min_iou", 0.3)),
            }
        except Exception:
            pass
    return {
        "confidence": 0.5,
        "min_box_fraction": 0.01,
        "persistence_seconds": 1.0,
        "min_iou": 0.3,
    }


class BrowserCameraMonitor:
    """Accept small detector frames without ever pacing the browser video element."""

    def __init__(
        self,
        detector_width: int = 960,
        alert_confidence: float | None = None,
        alert_min_box_fraction: float | None = None,
        persistence_seconds: float | None = None,
        min_iou: float | None = None,
    ) -> None:
        self.detector_width = max(320, detector_width)
        defaults = _load_live_alert_defaults()
        self.alert_confidence = alert_confidence if alert_confidence is not None else defaults["confidence"]
        self.alert_min_box_fraction = (
            alert_min_box_fraction if alert_min_box_fraction is not None else defaults["min_box_fraction"]
        )
        self.persistence_seconds = (
            persistence_seconds if persistence_seconds is not None else defaults["persistence_seconds"]
        )
        self.min_iou = min_iou if min_iou is not None else defaults["min_iou"]

        self._trackers: dict[str, tuple[PersistentDetectionAlert, float]] = {}
        self.started = time.monotonic()
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._times: deque[float] = deque(maxlen=40)
        self._queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]] = queue.Queue(maxsize=8)
        self._queued_bytes = 0
        self.delivery_count = 0
        self.failure_count = 0
        self.last_error: str | None = None
        self._sender = threading.Thread(target=self._send, name="browser-camera-alert-sender", daemon=True)
        self._sender.start()

    def _get_tracker(self, session_id: str, now: float) -> PersistentDetectionAlert:
        """Retrieve or create a tracker for the session; evict idle trackers after 5 minutes."""
        cutoff = now - 300.0
        self._trackers = {sid: (trk, t) for sid, (trk, t) in self._trackers.items() if t >= cutoff}
        if session_id in self._trackers:
            trk, _ = self._trackers[session_id]
            self._trackers[session_id] = (trk, now)
            return trk
        trk = PersistentDetectionAlert(seconds=self.persistence_seconds, min_iou=self.min_iou)
        self._trackers[session_id] = (trk, now)
        return trk

    @property
    def tracker(self) -> PersistentDetectionAlert:
        """Maintain backward compatibility for callers expecting a single tracker property."""
        now = time.monotonic()
        with self._lock:
            return self._get_tracker("default", now)

    def process(self, image: np.ndarray, detector: Any, session_id: str = "default") -> dict[str, Any]:
        """Detect a reduced camera frame and update alert persistence."""
        height, width = image.shape[:2]
        scale = min(self.detector_width / max(width, 1), 1.0)
        reduced = (
            cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
            if scale < 1
            else image
        )
        started = time.monotonic()
        result = detector.predict(reduced)
        detections = scale_detections(result["detections"], (reduced.shape[1], reduced.shape[0]), (width, height))

        conf = getattr(detector, "live_alert_confidence", self.alert_confidence)
        min_box = getattr(detector, "live_alert_min_box_fraction", self.alert_min_box_fraction)

        candidates = [
            item
            for item in detections
            if item["class"] in {"fire", "smoke"}
            and float(item["confidence"]) >= conf
            and (
                max(0, item["xyxy"][2] - item["xyxy"][0])
                * max(0, item["xyxy"][3] - item["xyxy"][1])
                / max(width * height, 1)
                >= min_box
            )
        ]
        now = time.monotonic()
        with self._lock:
            active_tracker = self._get_tracker(session_id, now)
            alert = active_tracker.update(candidates, now - self.started)
            alert_id = None
            if alert is not None:
                alert_id = uuid.uuid4().hex
                self._pending[alert_id] = {
                    "detections": detections,
                    "alert": alert,
                    "expires": now + 8,
                    "image_width": width,
                    "image_height": height,
                }
            self._pending = {key: value for key, value in self._pending.items() if value["expires"] >= now}
            self._times.append(now)
            updates = (
                (len(self._times) - 1) / max(self._times[-1] - self._times[0], 1e-6) if len(self._times) > 1 else 0.0
            )
            is_alerted = active_tracker.alerted

        return {
            "detections": detections,
            "image_width": width,
            "image_height": height,
            "coordinate_space": "submitted_image_pixels",
            "alert_id": alert_id,
            "detector_ms": round((time.monotonic() - started) * 1000),
            "updates_per_second": round(updates, 2),
            "alert_active": is_alerted,
        }

    def submit_full_resolution_snapshot(self, alert_id: str, image: np.ndarray) -> bool:
        """Queue the matching source frame for a pending alert, respecting the byte budget."""
        with self._lock:
            item = self._pending.get(alert_id)
            if item is None:
                return False
            frame_bytes = image.nbytes
            if self._queued_bytes + frame_bytes > MAX_QUEUE_BYTES:
                self.last_error = "Camera alert queue byte budget exceeded."
                self.failure_count += 1
                AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml").record_failure(
                    "live_camera", 0, "Queue byte budget exceeded"
                )
                return False
            del self._pending[alert_id]

        source_size = (item["image_width"], item["image_height"])
        target_size = (image.shape[1], image.shape[0])
        detections = scale_detections(item["detections"], source_size, target_size)
        alert = dict(item["alert"])
        alert["detection"] = scale_detections([alert["detection"]], source_size, target_size)[0]

        try:
            self._queue.put_nowait((image.copy(), detections, alert))
            with self._lock:
                self._queued_bytes += frame_bytes
        except queue.Full:
            self.last_error = "Camera alert queue is full."
            self.failure_count += 1
            AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml").record_failure(
                "live_camera", 0, "Queue full"
            )
            return False
        return True

    def status(self) -> dict[str, Any]:
        """Return the current configuration and delivery status."""
        return {"delivered": self.delivery_count, "failed": self.failure_count, "last_error": self.last_error}

    def _send(self) -> None:
        while True:
            image, detections, alert = self._queue.get()
            with self._lock:
                self._queued_bytes = max(0, self._queued_bytes - image.nbytes)
            try:
                folder = PROJECT_ROOT / "runs" / "webcam_alerts"
                folder.mkdir(parents=True, exist_ok=True)
                photo = folder / f"alert_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
                if not cv2.imwrite(str(photo), draw_detections(image, detections)):
                    raise OSError("Snapshot encode failed")
                detection = alert["detection"]
                caption = (
                    f"Live camera · {datetime.now().astimezone().isoformat(timespec='seconds')} · "
                    f"{detection['class']} · confidence {float(detection['confidence']):.0%}"
                )
                manager = AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml")
                dedupe = "live_camera"
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
                        detail = str(exc).strip()
                        self.last_error = detail if detail else f"Telegram delivery failed ({type(exc).__name__})."
                        manager.record_failure(
                            "live_camera", attempt, "Delivery failed; check configuration and network", photo.name
                        )
                        if attempt == 3:
                            self.failure_count += 1
                        else:
                            time.sleep(2 ** (attempt - 1))
            except Exception as exc:
                detail = str(exc).strip()
                self.last_error = detail if detail else f"Camera alert failed ({type(exc).__name__})."
                self.failure_count += 1
            finally:
                self._queue.task_done()
