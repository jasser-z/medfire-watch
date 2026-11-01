from __future__ import annotations

import json
import math
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
UNIFIED_NAMES = ["fire", "smoke"]


def _image_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _find_split(data_root: Path, split: str) -> tuple[Path, Path]:
    aliases = (split, "valid") if split == "val" else (split,)
    for alias in aliases:
        for image_dir, label_dir in (
            (data_root / "images" / alias, data_root / "labels" / alias),
            (data_root / alias / "images", data_root / alias / "labels"),
        ):
            if image_dir.is_dir() and label_dir.is_dir():
                return image_dir, label_dir
    raise FileNotFoundError(f"Could not locate D-Fire {split} images and labels under {data_root}.")


def _read_file_list(path: Path) -> set[str]:
    rows = [
        line.strip().replace("\\", "/").rsplit("/", 1)[-1].casefold()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    names = set(rows)
    if not names:
        raise ValueError(f"Official split list is empty: {path}")
    if len(rows) != len(names):
        raise ValueError(f"Official split list contains duplicate filenames: {path}")
    return names


def _validate_official_splits(
    data_root: Path,
    train_list: Path,
    test_list: Path,
) -> dict[str, int]:
    official_train = _read_file_list(train_list)
    official_test = _read_file_list(test_list)
    if official_train & official_test:
        raise ValueError("Official D-Fire train and test lists overlap.")

    split_names: dict[str, set[str]] = {}
    for split in ("train", "val", "test"):
        image_dir, _ = _find_split(data_root, split)
        names = [path.name.casefold() for path in _image_files(image_dir)]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate image filenames exist in D-Fire {split}.")
        split_names[split] = set(names)

    train_and_val = split_names["train"] | split_names["val"]
    if train_and_val != official_train:
        missing = len(official_train - train_and_val)
        unexpected = len(train_and_val - official_train)
        raise ValueError(
            "Kaggle D-Fire train/val does not exactly match the official train list "
            f"(missing={missing}, unexpected={unexpected})."
        )
    if split_names["test"] != official_test:
        missing = len(official_test - split_names["test"])
        unexpected = len(split_names["test"] - official_test)
        raise ValueError(
            "Kaggle D-Fire test does not exactly match the official test list "
            f"(missing={missing}, unexpected={unexpected})."
        )
    leakage = (split_names["train"] | split_names["val"]) & official_test
    if leakage:
        raise ValueError(
            f"Official test leakage found in Kaggle train/val ({len(leakage)} images); refusing merge."
        )
    return {
        "official_train_images": len(official_train),
        "official_test_images": len(official_test),
        "kaggle_train_images": len(split_names["train"]),
        "kaggle_val_images": len(split_names["val"]),
        "kaggle_test_images": len(split_names["test"]),
        "official_test_in_kaggle_train_or_val": len(leakage),
    }


def _class_mapping(metadata_path: Path) -> tuple[dict[int, int], dict[str, int]]:
    document = yaml.safe_load(metadata_path.read_text(encoding="utf-8-sig"))
    names: Any = document.get("names")
    if isinstance(names, dict):
        names = [names[key] for key in sorted(names, key=lambda item: int(item))]
    if not isinstance(names, list) or len(names) != 2:
        raise ValueError(f"D-Fire metadata must define exactly two class names: {metadata_path}")
    normalized = [str(name).strip().casefold() for name in names]
    if set(normalized) != {"fire", "smoke"}:
        raise ValueError(f"Expected D-Fire class names fire/smoke, found {names!r}.")
    source_to_unified = {
        source_id: UNIFIED_NAMES.index(name)
        for source_id, name in enumerate(normalized)
    }
    return source_to_unified, {name: index for index, name in enumerate(normalized)}


def _convert_label_file(
    label_path: Path,
    *,
    source_to_unified: dict[int, int],
    source_name: str,
    split: str,
    image_name: str,
    dropped_rows: list[dict[str, str | int]],
) -> tuple[str, Counter[int]]:
    converted: list[str] = []
    counts: Counter[int] = Counter()
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8-sig").splitlines(), 1):
        fields = line.split()
        if not fields:
            continue
        reason: str | None = None
        if len(fields) != 5:
            reason = "expected_five_columns"
        else:
            try:
                class_value = float(fields[0])
                coordinates = [float(value) for value in fields[1:]]
            except ValueError:
                reason = "non_numeric_value"
            else:
                class_id = int(class_value) if math.isfinite(class_value) else -1
                if not math.isfinite(class_value) or class_value != class_id or class_id not in source_to_unified:
                    reason = "invalid_class_id"
                elif any(not math.isfinite(value) or value < 0 or value > 1 for value in coordinates):
                    reason = "coordinate_out_of_range"
                elif coordinates[2] <= 0 or coordinates[3] <= 0:
                    reason = "zero_size_box"
        if reason is not None:
            dropped_rows.append(
                {
                    "source": source_name,
                    "split": split,
                    "image": image_name,
                    "line": line_number,
                    "reason": reason,
                }
            )
            continue

        unified_id = source_to_unified[class_id]
        fields[0] = str(unified_id)
        converted.append(" ".join(fields))
        counts[unified_id] += 1
    return "\n".join(converted), counts


def _validated_pair_paths(data_root: Path, split: str) -> tuple[Path, Path, list[Path]]:
    image_dir, label_dir = _find_split(data_root, split)
    images = _image_files(image_dir)
    image_stems = {path.relative_to(image_dir).with_suffix("").as_posix().casefold() for path in images}
    labels = sorted(path for path in label_dir.rglob("*.txt") if path.is_file())
    label_stems = {path.relative_to(label_dir).with_suffix("").as_posix().casefold() for path in labels}
    if not images or image_stems != label_stems:
        raise ValueError(
            f"D-Fire {split} image/label mismatch: images={len(images)}, labels={len(labels)}, "
            f"images_without_labels={len(image_stems - label_stems)}, "
            f"labels_without_images={len(label_stems - image_stems)}."
        )
    return image_dir, label_dir, images


def _copy_split(
    *,
    source_data_root: Path,
    output_root: Path,
    source_name: str,
    source_split: str,
    output_split: str,
    source_to_unified: dict[int, int],
    dropped_rows: list[dict[str, str | int]],
) -> dict[str, Any]:
    image_dir, label_dir, images = _validated_pair_paths(source_data_root, source_split)
    output_images = output_root / "images" / output_split / source_name
    output_labels = output_root / "labels" / output_split / source_name
    output_images.mkdir(parents=True, exist_ok=True)
    output_labels.mkdir(parents=True, exist_ok=True)
    box_counts: Counter[int] = Counter()
    for image_path in images:
        label_path = label_dir / image_path.relative_to(image_dir).with_suffix(".txt")
        target_name = f"{source_name}_{image_path.name}"
        shutil.copy2(image_path, output_images / target_name)
        converted, counts = _convert_label_file(
            label_path,
            source_to_unified=source_to_unified,
            source_name=source_name,
            split=source_split,
            image_name=image_path.name,
            dropped_rows=dropped_rows,
        )
        target_label = output_labels / f"{Path(target_name).stem}.txt"
        target_label.write_text(converted, encoding="utf-8")
        box_counts.update(counts)
    return {
        "images": len(images),
        "labels": len(images),
        "boxes": {UNIFIED_NAMES[index]: box_counts[index] for index in range(len(UNIFIED_NAMES))},
    }


def _copy_pyro_split(
    *,
    pyro_root: Path,
    output_root: Path,
    split: str,
) -> dict[str, Any]:
    dropped_rows: list[dict[str, str | int]] = []
    result = _copy_split(
        source_data_root=pyro_root,
        output_root=output_root,
        source_name="pyro-sdis",
        source_split=split,
        output_split=split,
        source_to_unified={1: 1},
        dropped_rows=dropped_rows,
    )
    if dropped_rows:
        raise ValueError(
            f"Pyro-SDIS {split} contains invalid or unexpected label rows; refusing to sanitize this source."
        )
    return result


def _write_dataset_configs(output_root: Path, *, dataset_path: Path) -> None:
    common = {
        "path": str(dataset_path.resolve()),
        "train": "images/train",
        "nc": 2,
        "names": UNIFIED_NAMES,
    }
    (output_root / "dataset.yaml").write_text(
        yaml.safe_dump(
            {**common, "val": "images/val", "test": "images/test"},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    evaluation_dir = output_root / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    configs = {
        "combined_validation.yaml": "images/val",
        "dfire_validation.yaml": "images/val/dfire",
        "pyro_sdis_validation.yaml": "images/val/pyro-sdis",
        "dfire_official_test.yaml": "images/test/dfire",
    }
    for filename, val_path in configs.items():
        (evaluation_dir / filename).write_text(
            yaml.safe_dump({**common, "val": val_path}, sort_keys=False),
            encoding="utf-8",
        )
    (evaluation_dir / "combined_test_and_pyro_val.yaml").write_text(
        yaml.safe_dump(
            {
                **common,
                "val": ["images/test/dfire", "images/val/pyro-sdis"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def build_merged_detection_dataset(
    *,
    pyro_root: Path,
    dfire_root: Path,
    official_train_list: Path,
    official_test_list: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing merged dataset: {output_root}")
    pyro_root = pyro_root.resolve()
    dfire_root = dfire_root.resolve()
    source_data_root = dfire_root / "data" if (dfire_root / "data").is_dir() else dfire_root
    split_audit = _validate_official_splits(source_data_root, official_train_list, official_test_list)
    source_to_unified, source_names = _class_mapping(dfire_root / "data.yaml")

    pyro_splits = {
        split: _validated_pair_paths(pyro_root, split)
        for split in ("train", "val")
    }
    if any(not paths[2] for paths in pyro_splits.values()):
        raise ValueError("Pyro-SDIS train and val splits must both contain images.")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}-staging-", dir=output_root.parent)
    )
    dropped_rows: list[dict[str, str | int]] = []
    try:
        counts: dict[str, dict[str, Any]] = {
            "train": {},
            "val": {},
            "test": {},
        }
        counts["train"]["dfire"] = _copy_split(
            source_data_root=source_data_root,
            output_root=staging_root,
            source_name="dfire",
            source_split="train",
            output_split="train",
            source_to_unified=source_to_unified,
            dropped_rows=dropped_rows,
        )
        counts["val"]["dfire"] = _copy_split(
            source_data_root=source_data_root,
            output_root=staging_root,
            source_name="dfire",
            source_split="val",
            output_split="val",
            source_to_unified=source_to_unified,
            dropped_rows=dropped_rows,
        )
        counts["test"]["dfire"] = _copy_split(
            source_data_root=source_data_root,
            output_root=staging_root,
            source_name="dfire",
            source_split="test",
            output_split="test",
            source_to_unified=source_to_unified,
            dropped_rows=dropped_rows,
        )
        for split in ("train", "val"):
            counts[split]["pyro-sdis"] = _copy_pyro_split(
                pyro_root=pyro_root,
                output_root=staging_root,
                split=split,
            )

        totals = {
            split: {
                "images": sum(source.get("images", 0) for source in sources.values()),
                "labels": sum(source.get("labels", 0) for source in sources.values()),
                "boxes": {
                    class_name: sum(source.get("boxes", {}).get(class_name, 0) for source in sources.values())
                    for class_name in UNIFIED_NAMES
                },
            }
            for split, sources in counts.items()
        }
        _write_dataset_configs(staging_root, dataset_path=output_root)
        manifest = {
            "classes": {"0": "fire", "1": "smoke"},
            "sources": {
                "D-Fire": {
                    "class_names": source_names,
                    "source_to_unified": {str(key): value for key, value in source_to_unified.items()},
                    "official_split_audit": split_audit,
                    "invalid_annotation_rows_omitted": len(dropped_rows),
                    "omitted_rows_by_reason": dict(Counter(row["reason"] for row in dropped_rows)),
                    "omitted_rows": dropped_rows,
                },
                "Pyro-SDIS": {"source_class_0": "smoke", "unified_class": 1},
            },
            "counts_by_split_and_source": counts,
            "counts_by_split": totals,
            "held_out_test": "D-Fire official test list only; excluded from train and validation.",
            "validation_policy": "D-Fire Kaggle val plus separate Pyro-SDIS val; both derived from official train.",
        }
        (staging_root / "dataset_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        staging_root.replace(output_root)
        return manifest
    except Exception:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise
