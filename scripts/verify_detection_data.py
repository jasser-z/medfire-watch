from __future__ import annotations

import argparse
import logging
import math
import sys
from collections import Counter
from pathlib import Path

import yaml
from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medfire_watch.config import PROJECT_ROOT  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = {0: "fire", 1: "smoke"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate image/label pairs and unified YOLO class IDs.")
    parser.add_argument(
        "--fast-dev",
        action="store_true",
        help="Inspect only the first 100 images per split.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Dataset root; defaults to the root in configs/detection_data.yaml.",
    )
    return parser.parse_args()


def _validate_label(label_path: Path, class_counts: Counter[int]) -> None:
    if not label_path.exists():
        raise ValueError(f"Missing matching label file: {label_path}")
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        columns = line.split()
        if len(columns) != 5:
            raise ValueError(f"{label_path}:{line_number}: expected 5 YOLO columns.")
        try:
            class_value = float(columns[0])
            coordinates = [float(value) for value in columns[1:]]
        except ValueError as exc:
            raise ValueError(f"{label_path}:{line_number}: non-numeric YOLO value.") from exc
        class_id = int(class_value)
        if class_value != class_id or class_id not in CLASS_NAMES:
            raise ValueError(f"{label_path}:{line_number}: class ID {columns[0]!r} is not in {CLASS_NAMES}.")
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in coordinates):
            raise ValueError(f"{label_path}:{line_number}: normalized coordinates must be in [0, 1].")
        if coordinates[2] == 0 or coordinates[3] == 0:
            raise ValueError(f"{label_path}:{line_number}: box width/height must be positive.")
        class_counts[class_id] += 1


def verify_split(
    data_dir: Path,
    split: str,
    *,
    image_limit: int | None = None,
) -> tuple[int, int, Counter[int]]:
    image_dir = data_dir / "images" / split
    label_dir = data_dir / "labels" / split
    if not image_dir.is_dir() or not label_dir.is_dir():
        raise FileNotFoundError(f"Expected image and label directories for {split}: {image_dir}, {label_dir}")

    images = sorted(path for path in image_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if image_limit is not None:
        images = images[:image_limit]
    if not images:
        raise ValueError(f"No images found for split {split!r} under {image_dir}.")

    labels_by_stem = {
        path.relative_to(label_dir).with_suffix("").as_posix().casefold(): path
        for path in label_dir.rglob("*.txt")
        if path.is_file()
    }
    counts: Counter[int] = Counter()
    for image_path in images:
        try:
            with Image.open(image_path) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError(f"Unreadable image: {image_path}") from exc
        label_path = label_dir / image_path.relative_to(image_dir).with_suffix(".txt")
        _validate_label(label_path, counts)

    matched_stems = {path.relative_to(image_dir).with_suffix("").as_posix().casefold() for path in images}
    orphan_labels = sorted(set(labels_by_stem) - matched_stems)
    if orphan_labels and image_limit is None:
        raise ValueError(f"Orphan label files in {split}: {orphan_labels[:5]}")
    return len(images), sum(counts.values()), counts


def main() -> None:
    args = parse_args()
    config = PROJECT_ROOT / "configs" / "detection_data.yaml"
    if not config.is_file():
        raise FileNotFoundError(f"Missing generated Ultralytics config: {config}")
    config_data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data_dir = args.data_dir or Path(config_data["path"])

    total_images = 0
    total_boxes = 0
    total_classes: Counter[int] = Counter()
    image_limit = 100 if args.fast_dev else None
    splits = ("train", "val", "test") if (data_dir / "images" / "test").is_dir() else ("train", "val")
    for split in splits:
        image_count, box_count, class_counts = verify_split(
            data_dir,
            split,
            image_limit=image_limit,
        )
        total_images += image_count
        total_boxes += box_count
        total_classes.update(class_counts)
        logger.info(
            "%s: %d images; %d boxes; fire=%d, smoke=%d.",
            split,
            image_count,
            box_count,
            class_counts[0],
            class_counts[1],
        )

    if config_data.get("nc") != 2 or config_data.get("names") != ["fire", "smoke"]:
        raise ValueError("Detection config class mapping must be 0=fire, 1=smoke.")

    logger.info(
        "Detection verification passed: %d real images, %d boxes; class totals fire=%d, smoke=%d.",
        total_images,
        total_boxes,
        total_classes[0],
        total_classes[1],
    )
    if total_classes[0] == 0:
        logger.warning(
            "No fire-positive boxes are present. Pyro-SDIS is smoke-only; add reviewed D-Fire labels "
            "before claiming fire detection or using this dataset for the complete two-class task."
        )


if __name__ == "__main__":
    main()
