"""Explicit conversion between detector-image and source-image coordinates."""

from __future__ import annotations

from typing import Any


def scale_detections(
    detections: list[dict[str, Any]], source_size: tuple[int, int], target_size: tuple[int, int]
) -> list[dict[str, Any]]:
    """Map boxes between source and target image dimensions."""
    sw, sh = source_size
    tw, th = target_size
    if min(sw, sh, tw, th) <= 0:
        raise ValueError("Image dimensions must be positive.")
    output = []
    for detection in detections:
        item = dict(detection)
        item["xyxy"] = [
            max(0.0, min(float(value) * (tw / sw if i % 2 == 0 else th / sh), tw if i % 2 == 0 else th))
            for i, value in enumerate(detection["xyxy"])
        ]
        output.append(item)
    return output
