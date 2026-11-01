from __future__ import annotations

from typing import Any


def box_iou(first: list[float], second: list[float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    area_a = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    area_b = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


class PersistentDetectionAlert:
    """Track one overlapping detection using elapsed time, not frame count."""

    def __init__(self, seconds: float, min_iou: float, max_gap: float = 2.0) -> None:
        if seconds <= 0 or not 0 <= min_iou <= 1 or max_gap <= 0:
            raise ValueError("Invalid live alert persistence settings.")
        self.seconds = seconds
        self.min_iou = min_iou
        self.max_gap = max_gap
        self.previous: dict[str, Any] | None = None
        self.started: float | None = None
        self.last_seen: float | None = None
        self.alerted = False

    def update(self, detections: list[dict[str, Any]], now: float) -> dict[str, Any] | None:
        # Short detector dropouts must not erase an otherwise persistent track.
        if not detections and self.last_seen is not None and now - self.last_seen <= 0.35:
            return None
        match = None
        if self.previous is not None and self.last_seen is not None and now - self.last_seen <= self.max_gap:
            candidates = [d for d in detections if d['class'] == self.previous['class']]
            match = max(candidates, key=lambda d: box_iou(d['xyxy'], self.previous['xyxy']), default=None)
            if match and box_iou(match['xyxy'], self.previous['xyxy']) < self.min_iou:
                match = None
        if match is None:
            self.alerted = False
            self.started = now if detections else None
            match = max(detections, key=lambda d: float(d['confidence']), default=None)
        self.previous = dict(match) if match else None
        self.last_seen = now if match else None
        if match and self.started is not None and now - self.started >= self.seconds and not self.alerted:
            self.alerted = True
            return {"first_detection_seconds": self.started, "alert_seconds": now, "detection": dict(match)}
        return None
