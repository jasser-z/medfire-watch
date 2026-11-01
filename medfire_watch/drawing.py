from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def draw_detections(image: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    """Draw fire and smoke boxes with readable, image-scaled labels."""
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected a three-channel BGR image.")
    height, width = image.shape[:2]
    scale = max(min(width, height) / 720, 0.75)
    line_width = max(2, round(scale * 3))
    font_size = max(14, round(20 * scale))
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    rgb_image = Image.fromarray(image[:, :, ::-1])
    draw = ImageDraw.Draw(rgb_image)
    for detection in detections:
        x1, y1, x2, y2 = (
            int(round(value))
            for value in detection["xyxy"]
        )
        x1, x2 = sorted((max(0, min(width - 1, x1)), max(0, min(width - 1, x2))))
        y1, y2 = sorted((max(0, min(height - 1, y1)), max(0, min(height - 1, y2))))
        class_name = str(detection["class"]).lower()
        color = (226, 54, 54) if class_name == "fire" else (242, 154, 28)
        draw.rectangle((x1, y1, x2, y2), outline=color, width=line_width)

        label = f"{class_name} {float(detection['confidence']):.0%}"
        bounds = draw.textbbox((0, 0), label, font=font)
        label_width = bounds[2] - bounds[0]
        label_height = bounds[3] - bounds[1]
        padding = max(3, round(font_size * 0.2))
        tag_left = min(max(0, x1), max(0, width - label_width - 2 * padding))
        tag_top = y1 - label_height - 2 * padding
        if tag_top < 0:
            tag_top = min(height - label_height - 2 * padding, y2 + 1)
        tag_top = max(0, tag_top)
        tag_right = min(width, tag_left + label_width + 2 * padding)
        tag_bottom = min(height, tag_top + label_height + 2 * padding)
        draw.rectangle((tag_left, tag_top, tag_right, tag_bottom), fill=color)
        draw.text(
            (tag_left + padding, tag_top + padding - bounds[1]),
            label,
            fill=(255, 255, 255),
            font=font,
        )
    return np.asarray(rgb_image)[:, :, ::-1].copy()
