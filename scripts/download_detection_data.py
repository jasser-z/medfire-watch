from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medfire_watch.config import PROJECT_ROOT  # noqa: E402

DATASET_ID = "pyronear/pyro-sdis"
DATASET_REVISION = "ebfc02d0cba7f7dfe0623d13bcf0f0aa8a38e3ee"
DATASET_CARD_URL = f"https://huggingface.co/datasets/{DATASET_ID}/raw/main/README.md"
SPLITS = ("train", "val")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and export real Pyro-SDIS images as YOLO data.")
    parser.add_argument(
        "--fast-dev",
        action="store_true",
        help="Download at most 32 real images per split for a quick pipeline check.",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=None,
        help="Download at most this many real images per split; omit for the complete dataset.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "detection" / "Pyro-SDIS",
    )
    parser.add_argument(
        "--revision",
        default=DATASET_REVISION,
        help="Hugging Face commit/tag; the default pins the verified v2.0 data revision.",
    )
    parser.add_argument(
        "--dfire-dir",
        type=Path,
        default=None,
        help="Optional manually downloaded/extracted D-Fire root; never downloaded without consent.",
    )
    parser.add_argument(
        "--dfire-fire-class-id",
        type=int,
        default=None,
        help="D-Fire source class ID verified from its data metadata.",
    )
    parser.add_argument(
        "--dfire-smoke-class-id",
        type=int,
        default=None,
        help="D-Fire source class ID verified from its data metadata.",
    )
    return parser.parse_args()


def _safe_name(value: Any, fallback: str) -> str:
    name = Path(str(value or fallback)).name
    if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
        name = f"{Path(name).stem}.jpg"
    if not re.fullmatch(r"[\w.-]+", name, flags=re.UNICODE):
        raise ValueError(f"Unsafe image filename from dataset: {name!r}")
    return name


def _annotations_to_unified_yolo(annotations: Any) -> str:
    """Map the verified Pyro-SDIS source class 0 (smoke) to unified ID 1."""
    if annotations is None:
        return ""
    if isinstance(annotations, str):
        lines = annotations.splitlines()
    elif isinstance(annotations, list):
        lines = [str(line) for line in annotations]
    else:
        raise ValueError(f"Unsupported Pyro-SDIS annotation type: {type(annotations).__name__}")

    converted: list[str] = []
    for line in lines:
        values = line.split()
        if not values:
            continue
        if len(values) != 5:
            raise ValueError(f"Invalid Pyro-SDIS YOLO row with {len(values)} columns: {line!r}")
        class_id = int(float(values[0]))
        if class_id != 0:
            raise ValueError(f"Unexpected Pyro-SDIS source class ID {class_id}; expected smoke class 0.")
        values[0] = "1"
        converted.append(" ".join(values))
    return "\n".join(converted)


def _save_image(image_value: Any, target: Path) -> None:
    if hasattr(image_value, "save"):
        final_suffix = target.name.split(".")[-2].lower()
        image_format = "JPEG" if final_suffix in {"jpg", "jpeg"} else "PNG"
        image_value.save(target, format=image_format)
        return
    if isinstance(image_value, dict) and image_value.get("bytes"):
        target.write_bytes(image_value["bytes"])
        return
    raise ValueError(f"Unsupported image value for {target.name}: {type(image_value).__name__}")


def _download_split(
    *,
    dataset: Any,
    split: str,
    output_dir: Path,
    limit: int | None,
) -> tuple[int, int]:
    image_dir = output_dir / "images" / split
    label_dir = output_dir / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = 0

    for index, example in enumerate(dataset):
        if limit is not None and count >= limit:
            break
        fallback = f"{split}_{index:06d}.jpg"
        name = _safe_name(example.get("image_name"), fallback)
        image_path = image_dir / name
        label_path = label_dir / f"{Path(name).stem}.txt"
        if image_path.is_file() and label_path.is_file():
            skipped += 1
            count += 1
            continue

        image_value = example.get("image")
        if image_value is None:
            raise ValueError(f"Missing image in {split} record {index}.")
        temporary_image = image_path.with_suffix(image_path.suffix + ".part")
        temporary_label = label_path.with_suffix(".txt.part")
        try:
            _save_image(image_value, temporary_image)
            annotations = _annotations_to_unified_yolo(example.get("annotations", ""))
            temporary_label.write_text(annotations, encoding="utf-8")
            temporary_image.replace(image_path)
            temporary_label.replace(label_path)
        except Exception:
            temporary_image.unlink(missing_ok=True)
            temporary_label.unlink(missing_ok=True)
            raise

        count += 1
        if count % 100 == 0:
            logger.info("%s: exported %d real images (already present: %d).", split, count, skipped)

    return count, skipped


def _write_dataset_yaml(output_dir: Path) -> Path:
    config_path = PROJECT_ROOT / "configs" / "detection_data.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "path": str(output_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "nc": 2,
        "names": ["fire", "smoke"],
    }
    if any((output_dir / "images" / "test").glob("*")):
        document["test"] = "images/test"
    config_path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return config_path


def _find_dfire_split(source_dir: Path, split: str) -> tuple[Path, Path] | None:
    aliases = (split, "valid") if split == "val" else (split,)
    for alias in aliases:
        for image_path, label_path in (
            (source_dir / "images" / alias, source_dir / "labels" / alias),
            (source_dir / alias / "images", source_dir / alias / "labels"),
        ):
            if image_path.is_dir() and label_path.is_dir():
                return image_path, label_path
    return None


def _import_dfire(
    source_dir: Path,
    output_dir: Path,
    fire_class_id: int | None,
    smoke_class_id: int | None,
) -> dict[str, int]:
    if fire_class_id is None or smoke_class_id is None:
        raise ValueError(
            "D-Fire import requires --dfire-fire-class-id and --dfire-smoke-class-id, "
            "verified from the downloaded dataset's class metadata."
        )
    if fire_class_id == smoke_class_id:
        raise ValueError("D-Fire fire and smoke class IDs must be different.")

    totals: dict[str, int] = {}
    for source_split, destination_split in (("train", "train"), ("val", "val"), ("test", "test")):
        folders = _find_dfire_split(source_dir, source_split)
        if folders is None:
            if source_split == "train":
                raise FileNotFoundError(f"Could not locate D-Fire {source_split}/images and labels.")
            continue
        image_dir, label_dir = folders
        count = 0
        target_images = output_dir / "images" / destination_split
        target_labels = output_dir / "labels" / destination_split
        target_images.mkdir(parents=True, exist_ok=True)
        target_labels.mkdir(parents=True, exist_ok=True)
        for source_image in sorted(image_dir.iterdir()):
            if not source_image.is_file() or source_image.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            source_label = label_dir / f"{source_image.stem}.txt"
            if not source_label.is_file():
                raise FileNotFoundError(f"Missing D-Fire label file: {source_label}")
            target_name = f"dfire_{source_image.name}"
            converted: list[str] = []
            for line_number, line in enumerate(source_label.read_text(encoding="utf-8-sig").splitlines(), 1):
                fields = line.split()
                if not fields:
                    continue
                if len(fields) != 5:
                    raise ValueError(f"Malformed D-Fire label at {source_label}:{line_number}.")
                source_class = float(fields[0])
                source_id = int(source_class)
                if source_class != source_id:
                    raise ValueError(f"Non-integer D-Fire class ID {fields[0]!r} at {source_label}:{line_number}.")
                if source_id == fire_class_id:
                    fields[0] = "0"
                elif source_id == smoke_class_id:
                    fields[0] = "1"
                else:
                    raise ValueError(f"Unmapped D-Fire class ID {source_id} at {source_label}:{line_number}.")
                converted.append(" ".join(fields))
            image_target = target_images / target_name
            label_target = target_labels / f"{Path(target_name).stem}.txt"
            shutil.copy2(source_image, image_target)
            label_target.write_text("\n".join(converted), encoding="utf-8")
            count += 1
        totals[destination_split] = count
        logger.info("Imported %d D-Fire images into the %s split.", count, destination_split)
    return totals


def main() -> None:
    args = parse_args()
    limit = min(args.subset, 32) if args.fast_dev and args.subset else 32 if args.fast_dev else args.subset
    if limit is not None and limit < 1:
        raise SystemExit("--subset must be a positive integer.")

    try:
        card = requests.get(DATASET_CARD_URL, timeout=30)
        card.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(f"Could not verify the Pyro-SDIS dataset card: {exc}") from exc
    if "license: apache-2.0" not in card.text.lower():
        raise SystemExit("Pyro-SDIS license metadata is missing or not Apache-2.0; refusing export.")
    logger.info("Verified %s dataset card and Apache-2.0 license.", DATASET_ID)

    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit("The datasets package is required. Install project dependencies in .venv first.") from exc

    args.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Streaming real Pyro-SDIS records to %s; per-split limit: %s.",
        args.output_dir,
        limit if limit is not None else "all",
    )
    for split in SPLITS:
        dataset = load_dataset(
            DATASET_ID,
            split=split,
            revision=args.revision,
            streaming=True,
        )
        count, skipped = _download_split(
            dataset=dataset,
            split=split,
            output_dir=args.output_dir,
            limit=limit,
        )
        logger.info("%s complete: %d images exported or resumed; %d already existed.", split, count, skipped)
        if count == 0:
            raise RuntimeError(f"No examples were exported from Pyro-SDIS split {split!r}.")

    dfire_totals: dict[str, int] = {}
    if args.dfire_dir is not None:
        dfire_totals = _import_dfire(
            args.dfire_dir,
            args.output_dir,
            args.dfire_fire_class_id,
            args.dfire_smoke_class_id,
        )

    config_path = _write_dataset_yaml(args.output_dir)
    logger.info("Ultralytics data config written to %s.", config_path)
    manifest = {
        "source": DATASET_ID,
        "revision": args.revision,
        "license": "Apache-2.0",
        "exported_per_split_limit": limit,
        "fast_dev": args.fast_dev,
        "unified_classes": {"0": "fire", "1": "smoke"},
        "source_class_mapping": {"Pyro-SDIS:0": "smoke"},
        "dfire_images_by_split": dfire_totals,
    }
    if dfire_totals:
        manifest["source_class_mapping"]["D-Fire"] = {
            "fire": args.dfire_fire_class_id,
            "smoke": args.dfire_smoke_class_id,
        }
    (args.output_dir / "dataset_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "Pyro-SDIS is smoke-only: source class 0 was mapped to unified class 1=smoke. "
        "No fire-positive images are claimed from this source."
    )
    if not dfire_totals:
        logger.info(
            "D-Fire is not present. Download the official archive manually and inspect its source "
            "class metadata before re-running with --dfire-dir and explicit class IDs."
        )


if __name__ == "__main__":
    main()
