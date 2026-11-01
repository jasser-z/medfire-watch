from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def count_class_boxes(dataset_root: Path) -> Counter[int]:
    """Count YOLO object rows by class across train and validation labels."""
    counts: Counter[int] = Counter()
    for split in ("train", "val"):
        label_dir = dataset_root / "labels" / split
        if not label_dir.is_dir():
            raise FileNotFoundError(f"Detection labels are missing for {split}: {label_dir}")
        for label_path in label_dir.rglob("*.txt"):
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                fields = line.split()
                if len(fields) != 5:
                    raise ValueError(f"Malformed YOLO annotation in {label_path}:{line_number}.")
                class_value = float(fields[0])
                class_id = int(class_value)
                if class_value != class_id or class_id not in {0, 1}:
                    raise ValueError(
                        f"Unexpected class ID {fields[0]!r} in {label_path}:{line_number}."
                    )
                counts[class_id] += 1
    return counts


def detection_metrics(metrics: Any) -> dict[str, Any]:
    box = getattr(metrics, "box", None)
    aggregate = getattr(metrics, "results_dict", {}) or {}
    result: dict[str, Any] = {
        "mAP50": aggregate.get("metrics/mAP50(B)"),
        "mAP50_95": aggregate.get("metrics/mAP50-95(B)"),
        "precision": aggregate.get("metrics/precision(B)"),
        "recall": aggregate.get("metrics/recall(B)"),
        "per_class": {},
    }
    class_indexes = list(getattr(box, "ap_class_index", [])) if box is not None else []
    class_ap50 = list(getattr(box, "ap50", [])) if box is not None else []
    class_ap = getattr(box, "ap", []) if box is not None else []
    class_precision = list(getattr(box, "p", [])) if box is not None else []
    class_recall = list(getattr(box, "r", [])) if box is not None else []
    for index, class_id in enumerate(class_indexes):
        class_name = {0: "fire", 1: "smoke"}.get(int(class_id), str(class_id))
        result["per_class"][class_name] = {
            "mAP50": float(class_ap50[index]) if index < len(class_ap50) else None,
            "mAP50_95": float(class_ap[index]) if index < len(class_ap) else None,
            "precision": float(class_precision[index]) if index < len(class_precision) else None,
            "recall": float(class_recall[index]) if index < len(class_recall) else None,
        }
    return result
