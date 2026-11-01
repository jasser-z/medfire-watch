from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml
from medfire_watch.detection import detection_metrics
from medfire_watch.detection_data import build_merged_detection_dataset


def _write_image_and_label(root: Path, split: str, name: str, labels: str) -> None:
    image_dir = root / split / "images"
    label_dir = root / split / "labels"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / f"{name}.jpg").write_bytes(b"image")
    (label_dir / f"{name}.txt").write_text(labels, encoding="utf-8")


def _make_sources(root: Path) -> tuple[Path, Path, Path, Path]:
    pyro = root / "Pyro-SDIS"
    _write_image_and_label(pyro, "train", "smoke-train", "1 0.5 0.5 0.2 0.2\n")
    _write_image_and_label(pyro, "val", "smoke-val", "1 0.5 0.5 0.2 0.2\n")

    dfire = root / "dfire"
    data = dfire / "data"
    _write_image_and_label(data, "train", "fire-train", "1 0.5 0.5 0.2 0.2\n0 0.5 0.5 0 0\n")
    _write_image_and_label(data, "val", "fire-val", "0 0.5 0.5 0.2 0.2\n")
    _write_image_and_label(data, "test", "fire-test", "1 0.5 0.5 0.2 0.2\n0 0.5 0.5 1.2 0.2\n")
    (dfire / "data.yaml").write_text(
        yaml.safe_dump({"nc": 2, "names": ["smoke", "fire"]}),
        encoding="utf-8",
    )

    train_list = root / "dfire_train.txt"
    train_list.write_text("fire-train.jpg\nfire-val.jpg\n", encoding="utf-8")
    test_list = root / "dfire_test.txt"
    test_list.write_text("fire-test.jpg\n", encoding="utf-8")
    return pyro, dfire, train_list, test_list


def test_merge_maps_classes_sanitizes_rows_and_keeps_official_test_held_out(tmp_path: Path) -> None:
    pyro, dfire, train_list, test_list = _make_sources(tmp_path)
    output = tmp_path / "Merged"

    manifest = build_merged_detection_dataset(
        pyro_root=pyro,
        dfire_root=dfire,
        official_train_list=train_list,
        official_test_list=test_list,
        output_root=output,
    )

    assert manifest["sources"]["D-Fire"]["official_split_audit"][
        "official_test_in_kaggle_train_or_val"
    ] == 0
    assert manifest["sources"]["D-Fire"]["invalid_annotation_rows_omitted"] == 2
    assert manifest["counts_by_split"]["train"]["images"] == 2
    assert manifest["counts_by_split"]["val"]["images"] == 2
    assert manifest["counts_by_split"]["test"]["images"] == 1
    assert manifest["counts_by_split"]["train"]["boxes"] == {"fire": 1, "smoke": 1}
    assert manifest["counts_by_split"]["test"]["boxes"] == {"fire": 1, "smoke": 0}
    assert (output / "images" / "test" / "dfire" / "dfire_fire-test.jpg").is_file()
    test_label = (output / "labels" / "test" / "dfire" / "dfire_fire-test.txt").read_text(
        encoding="utf-8"
    )
    assert test_label == "0 0.5 0.5 0.2 0.2"
    dataset_config = yaml.safe_load((output / "dataset.yaml").read_text(encoding="utf-8"))
    assert dataset_config["path"] == str(output.resolve())
    assert dataset_config["test"] == "images/test"
    assert (output / "evaluation" / "pyro_sdis_validation.yaml").is_file()
    assert (output / "evaluation" / "dfire_official_test.yaml").is_file()
    written_manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert written_manifest["held_out_test"].startswith("D-Fire official test list only")


def test_merge_refuses_official_test_leakage_before_creating_output(tmp_path: Path) -> None:
    pyro, dfire, train_list, test_list = _make_sources(tmp_path)
    train_list.write_text("fire-train.jpg\nfire-val.jpg\nfire-test.jpg\n", encoding="utf-8")
    output = tmp_path / "Merged"

    try:
        build_merged_detection_dataset(
            pyro_root=pyro,
            dfire_root=dfire,
            official_train_list=train_list,
            official_test_list=test_list,
            output_root=output,
        )
    except ValueError as exc:
        assert "train and test lists overlap" in str(exc)
    else:
        raise AssertionError("Expected overlapping official split lists to be rejected.")

    assert not output.exists()


def test_detection_metrics_exposes_per_class_fire_and_smoke() -> None:
    metrics = SimpleNamespace(
        results_dict={
            "metrics/mAP50(B)": 0.4,
            "metrics/mAP50-95(B)": 0.2,
            "metrics/precision(B)": 0.5,
            "metrics/recall(B)": 0.6,
        },
        box=SimpleNamespace(
            ap_class_index=[0, 1],
            ap50=[0.3, 0.5],
            ap=[0.3, 0.4],
            p=[0.4, 0.6],
            r=[0.5, 0.7],
        ),
    )

    result = detection_metrics(metrics)

    assert result["mAP50"] == 0.4
    assert result["per_class"]["fire"]["mAP50"] == 0.3
    assert result["per_class"]["fire"]["mAP50_95"] == 0.3
    assert result["per_class"]["smoke"]["recall"] == 0.7
