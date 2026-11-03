from __future__ import annotations

import logging
import math
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from alerts.manager import AlertManager
from medfire_watch.config import PROJECT_ROOT, bounded_number

DETECTION_WEIGHTS_PATH = PROJECT_ROOT / "models" / "detection" / "weights" / "best.pt"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
DETECTION_CONFIG_PATH = PROJECT_ROOT / "configs" / "detection.yaml"
DEFAULT_VIDEO_UPLOAD_MB = 1024
DEFAULT_VIDEO_DURATION_SECONDS = 600.0
VIDEO_RESULT_DIR = PROJECT_ROOT / "runs" / "video_results"
VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
}
VIDEO_RESULT_PATHS: dict[str, Path] = {}
VIDEO_JOB_STATUS: dict[str, dict[str, Any]] = {}
VIDEO_JOB_LOCK = threading.Lock()
VIDEO_SOURCE_PATHS: dict[str, Path] = {}
VIDEO_FRAME_DETECTIONS: dict[str, list[dict[str, Any]]] = {}
VIDEO_PREPARED_INPUTS: dict[str, dict[str, Any]] = {}
VIDEO_SEEK_REQUESTS: dict[str, float] = {}
VIDEO_JOB_CANCEL_EVENTS: dict[str, threading.Event] = {}
VIDEO_DOWNLOAD_LEASES: dict[str, int] = {}
logger = logging.getLogger(__name__)


class DetectionService:
    def __init__(self) -> None:
        if not DETECTION_WEIGHTS_PATH.is_file():
            raise FileNotFoundError(f"Detection weights are missing: {DETECTION_WEIGHTS_PATH}")
        detection_config = yaml.safe_load(DETECTION_CONFIG_PATH.read_text(encoding="utf-8"))
        self.confidence_threshold = bounded_number(
            "confidence_threshold", detection_config["confidence_threshold"], 0, 1
        )
        if not 0 < self.confidence_threshold < 1:
            raise ValueError("Detector confidence threshold must be between zero and one.")
        self.consecutive_alert_frames = bounded_number(
            "temporal_alert.consecutive_frames",
            detection_config.get("temporal_alert", {}).get("consecutive_frames", 5),
            1,
            10000,
            integer=True,
        )
        video_cfg = detection_config.get("video", {})
        self.max_video_upload_bytes = (
            bounded_number(
                "video.maximum_upload_mb",
                video_cfg.get("maximum_upload_mb", DEFAULT_VIDEO_UPLOAD_MB),
                1,
                10240,
                integer=True,
            )
            * 1024
            * 1024
        )
        self.max_video_duration_seconds = bounded_number(
            "video.maximum_duration_seconds",
            video_cfg.get("maximum_duration_seconds", DEFAULT_VIDEO_DURATION_SECONDS),
            0.1,
            3600,
        )
        live_alert_cfg = detection_config.get("live_alert", {})
        for name, default, minimum, maximum in (
            ("confidence", 0.5, 0, 1),
            ("min_box_fraction", 0.01, 0, 1),
            ("persistence_seconds", 1.0, 0.01, 300),
            ("min_iou", 0.3, 0, 1),
        ):
            setattr(
                self,
                f"live_alert_{name}",
                bounded_number(f"live_alert.{name}", live_alert_cfg.get(name, default), minimum, maximum),
            )
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._warm_lock = threading.Lock()
        self._warmed = False

    def warmup(self) -> None:
        """Initialise inference once using a small blank frame."""
        with self._warm_lock:
            if not self._warmed:
                self.predict(np.zeros((360, 640, 3), dtype=np.uint8))
                self._warmed = True

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from ultralytics import YOLO

                    self._model = YOLO(str(DETECTION_WEIGHTS_PATH))
        return self._model

    @staticmethod
    def _format_result(result: Any, device: str) -> dict[str, Any]:
        boxes = result.boxes
        detections = []
        if boxes is not None:
            for xyxy, class_id, confidence in zip(
                boxes.xyxy.cpu().tolist(),
                boxes.cls.cpu().tolist(),
                boxes.conf.cpu().tolist(),
            ):
                if (
                    len(xyxy) != 4
                    or not all(math.isfinite(v) for v in [*xyxy, class_id, confidence])
                    or not 0 <= confidence <= 1
                    or class_id != int(class_id)
                ):
                    continue
                name = result.names.get(int(class_id))
                if name not in {"fire", "smoke"}:
                    continue
                shape = getattr(result, "orig_shape", None)
                if shape:
                    xyxy = [max(0, min(value, shape[1 if i % 2 == 0 else 0])) for i, value in enumerate(xyxy)]
                if xyxy[2] <= xyxy[0] or xyxy[3] <= xyxy[1]:
                    continue
                detections.append(
                    {
                        "class": name,
                        "confidence": float(confidence),
                        "xyxy": [float(value) for value in xyxy],
                    }
                )
        return {
            "detections": detections,
            "speed_ms": result.speed,
            "device": device,
            "confidence_threshold": 0.0,
        }

    def predict(self, image: np.ndarray) -> dict[str, Any]:
        """Run detection on one BGR image."""
        import torch
        from ultralytics.cfg import DEFAULT_CFG_DICT

        device = 0 if torch.cuda.is_available() else "cpu"
        precision = {"quantize": 16 if device == 0 else 32} if "quantize" in DEFAULT_CFG_DICT else {"half": device == 0}
        model = self._ensure_model()
        with self._lock:
            result = model.predict(
                source=image,
                imgsz=640,
                conf=self.confidence_threshold,
                device=device,
                **precision,
                verbose=False,
            )[0]
        formatted = self._format_result(result, str(device))
        formatted["confidence_threshold"] = self.confidence_threshold
        formatted["precision"] = "fp16" if model.predictor.model.fp16 else "fp32"
        return formatted

    def predict_batch(self, images: list[np.ndarray]) -> list[dict[str, Any]]:
        """Run detection on a batch of BGR images."""
        if not images:
            return []
        import torch
        from ultralytics.cfg import DEFAULT_CFG_DICT

        device = 0 if torch.cuda.is_available() else "cpu"
        precision = {"quantize": 16 if device == 0 else 32} if "quantize" in DEFAULT_CFG_DICT else {"half": device == 0}
        model = self._ensure_model()
        with self._lock:
            results = model.predict(
                source=images,
                imgsz=640,
                conf=self.confidence_threshold,
                device=device,
                **precision,
                batch=len(images),
                verbose=False,
            )
        formatted = [self._format_result(result, str(device)) for result in results]
        for item in formatted:
            item["confidence_threshold"] = self.confidence_threshold
            item["precision"] = "fp16" if model.predictor.model.fp16 else "fp32"
        return formatted


@lru_cache(maxsize=1)
def _detection_service() -> DetectionService:
    return DetectionService()


def get_detection_service() -> DetectionService:
    """Return the shared, lazily constructed detector."""
    return _detection_service()


def get_alert_manager() -> AlertManager:
    """Load the Telegram manager with local alert configuration."""
    return AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml")
