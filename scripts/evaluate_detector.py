from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medfire_watch.config import PROJECT_ROOT  # noqa: E402
from medfire_watch.detection import IMAGE_EXTENSIONS, detection_metrics  # noqa: E402

DEFAULT_DATA_ROOT = PROJECT_ROOT / "data" / "detection" / "Merged"
RESULTS_DIR = PROJECT_ROOT / "docs" / "results"
CLASS_NAMES = {0: "fire", 1: "smoke"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the final held-out D-Fire test and Pyro-SDIS validation evaluations."
    )
    parser.add_argument("--weights", type=Path, required=True, help="Trained YOLO weights to evaluate.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS_DIR / "detection_final_metrics.json",
    )
    parser.add_argument(
        "--only-source",
        choices=("dfire_official_test", "dfire_validation", "pyro_sdis_validation"),
        help="Run a single source when another source was already evaluated once.",
    )
    parser.add_argument(
        "--include-metrics",
        type=Path,
        help="Include an existing source-metrics JSON without rerunning that evaluation.",
    )
    parser.add_argument(
        "--only-samples",
        action="store_true",
        help="Generate prediction artifacts only, using existing metrics and plots.",
    )
    parser.add_argument(
        "--skip-samples",
        action="store_true",
        help="Do not run the test-set sample-prediction pass.",
    )
    return parser.parse_args()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _complete_class_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    per_class = metrics["per_class"]
    for class_name in CLASS_NAMES.values():
        per_class.setdefault(
            class_name,
            {"mAP50": None, "mAP50_95": None, "precision": None, "recall": None},
        )
    return metrics


def _read_ground_truth(label_path: Path, width: int, height: int) -> list[tuple[int, list[float]]]:
    if not label_path.is_file():
        raise FileNotFoundError(f"Missing label file for evaluation image: {label_path}")
    boxes: list[tuple[int, list[float]]] = []
    for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"Malformed YOLO annotation in {label_path}:{line_number}.")
        class_id = int(fields[0])
        center_x, center_y, box_width, box_height = map(float, fields[1:])
        if class_id not in CLASS_NAMES:
            raise ValueError(f"Unknown class {class_id} in {label_path}:{line_number}.")
        boxes.append(
            (
                class_id,
                [
                    (center_x - box_width / 2) * width,
                    (center_y - box_height / 2) * height,
                    (center_x + box_width / 2) * width,
                    (center_y + box_height / 2) * height,
                ],
            )
        )
    return boxes


def _iou(first: list[float], second: list[float]) -> float:
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _prediction_errors(
    ground_truth: list[tuple[int, list[float]]],
    predictions: list[tuple[int, list[float], float]],
) -> tuple[bool, bool, set[int]]:
    matched_predictions: set[int] = set()
    false_negative = False
    for true_class, true_box in ground_truth:
        candidates = [
            (_iou(true_box, predicted_box), index)
            for index, (predicted_class, predicted_box, _) in enumerate(predictions)
            if predicted_class == true_class and index not in matched_predictions
        ]
        best_iou, best_index = max(candidates, default=(0.0, -1))
        if best_iou >= 0.5:
            matched_predictions.add(best_index)
        else:
            false_negative = True
    false_positive = len(matched_predictions) != len(predictions)
    return false_negative, false_positive, matched_predictions


def _result_predictions(result: Any) -> list[tuple[int, list[float], float]]:
    if result.boxes is None or len(result.boxes) == 0:
        return []
    coordinates = result.boxes.xyxy.detach().cpu().tolist()
    class_ids = result.boxes.cls.detach().cpu().tolist()
    confidences = result.boxes.conf.detach().cpu().tolist()
    return [
        (int(class_id), list(box), float(confidence))
        for box, class_id, confidence in zip(coordinates, class_ids, confidences)
    ]


def _select_prediction_samples(model: Any, data_root: Path) -> list[tuple[Path, str]]:
    import cv2

    image_root = data_root / "images" / "test" / "dfire"
    label_root = data_root / "labels" / "test" / "dfire"
    image_paths = sorted(
        path for path in image_root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if len(image_paths) != 4306:
        raise ValueError(f"Expected 4,306 official D-Fire test images; found {len(image_paths)}.")

    candidates: dict[str, list[Path]] = {"false_negative": [], "false_positive": [], "correct": []}
    for result in model.predict(
        source=str(image_root),
        imgsz=640,
        conf=0.25,
        iou=0.7,
        batch=1,
        device=0,
        stream=True,
        verbose=False,
    ):
        image_path = Path(result.path)
        image = result.orig_img
        height, width = image.shape[:2]
        label_path = label_root / image_path.relative_to(image_root).with_suffix(".txt")
        truth = _read_ground_truth(label_path, width, height)
        predictions = _result_predictions(result)
        false_negative, false_positive, _ = _prediction_errors(truth, predictions)
        if false_negative:
            category = "false_negative"
        elif false_positive:
            category = "false_positive"
        else:
            category = "correct"
        if len(candidates[category]) < 18:
            candidates[category].append(image_path)

    selected: list[tuple[Path, str]] = []
    for category, limit in (("false_negative", 6), ("false_positive", 6)):
        for image_path in candidates[category]:
            if len([item for item in selected if item[1] == category]) >= limit:
                break
            if len(selected) < 12 and image_path not in {path for path, _ in selected}:
                selected.append((image_path, category))
    for category in ("correct", "false_negative", "false_positive"):
        for image_path in candidates[category]:
            if len(selected) >= 12:
                break
            if image_path not in {path for path, _ in selected}:
                selected.append((image_path, category))
    if len(selected) != 12:
        raise RuntimeError(f"Could select only {len(selected)} prediction samples, expected 12.")

    sample_dir = RESULTS_DIR / "detection_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_number = 0
    for result in model.predict(
        source=[str(path) for path, _ in selected],
        imgsz=640,
        conf=0.25,
        iou=0.7,
        batch=8,
        device=0,
        stream=True,
        verbose=False,
    ):
        image_path = Path(result.path)
        _, category = next(item for item in selected if item[0] == image_path)
        image = result.orig_img.copy()
        height, width = image.shape[:2]
        label_path = label_root / image_path.relative_to(image_root).with_suffix(".txt")
        truth = _read_ground_truth(label_path, width, height)
        predictions = _result_predictions(result)
        for class_id, box in truth:
            x1, y1, x2, y2 = map(round, box)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 200, 0), 2)
            cv2.putText(
                image,
                f"GT {CLASS_NAMES[class_id]}",
                (x1, max(18, y1 - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 200, 0),
                2,
            )
        for class_id, box, confidence in predictions:
            x1, y1, x2, y2 = map(round, box)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(
                image,
                f"Pred {CLASS_NAMES[class_id]} {confidence:.2f}",
                (x1, min(height - 4, y2 + 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 0, 255),
                2,
            )
        sample_number += 1
        filename = f"dfire_test_{category}_{sample_number:02d}_{image_path.stem}.jpg"
        output_path = sample_dir / filename
        if not cv2.imwrite(str(output_path), image):
            raise OSError(f"Could not save prediction sample: {output_path}")
        logger.info("Saved %s prediction sample: %s", category, output_path)
    return selected


def _copy_plots_from_dir(source_dir: Path, report_name: str) -> list[str]:
    copied: list[str] = []
    for source_name, output_name in (
        ("confusion_matrix.png", f"{report_name}_confusion_matrix.png"),
        ("BoxPR_curve.png", f"{report_name}_PR_curve.png"),
    ):
        source_path = source_dir / source_name
        if not source_path.is_file():
            raise FileNotFoundError(f"Expected evaluation plot was not created: {source_path}")
        output_path = RESULTS_DIR / output_name
        shutil.copy2(source_path, output_path)
        copied.append(output_path.name)
    return copied


def _copy_eval_plots(evaluation: Any, report_name: str) -> list[str]:
    return _copy_plots_from_dir(Path(evaluation.save_dir), report_name)


def main() -> None:
    args = parse_args()
    if not args.weights.is_file():
        raise FileNotFoundError(f"Model weights not found: {args.weights}")
    if not args.data_dir.is_dir():
        raise FileNotFoundError(f"Merged detection dataset not found: {args.data_dir}")
    eval_dir = args.data_dir / "evaluation"
    config_names = {
        "dfire_validation": "dfire_validation.yaml",
        "pyro_sdis_validation": "pyro_sdis_validation.yaml",
        "dfire_official_test": "dfire_official_test.yaml",
    }
    for config_name in config_names.values():
        if not (eval_dir / config_name).is_file():
            raise FileNotFoundError(f"Missing evaluation config: {eval_dir / config_name}")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("Ultralytics is required to evaluate detection weights.") from exc

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(args.weights))
    results: dict[str, Any] = {}
    artifact_names: list[str] = []
    prior_metrics_source_note = None
    prior_report: dict[str, Any] = {}
    if args.only_samples and args.include_metrics is None:
        raise ValueError("--only-samples requires --include-metrics.")
    if args.include_metrics is not None:
        prior_report = json.loads(args.include_metrics.read_text(encoding="utf-8"))
        prior_metrics_source_note = prior_report.get("metric_source_note")
        prior_metrics = prior_report.get("metrics")
        if not isinstance(prior_metrics, dict):
            raise ValueError(f"Existing metrics file has no metrics object: {args.include_metrics}")
        results.update(prior_metrics)
        if args.only_source in results:
            raise ValueError(
                f"Refusing to reevaluate {args.only_source}: it is already present in {args.include_metrics}."
            )
        if "dfire_official_test" in prior_metrics:
            plot_dir = RESULTS_DIR / "plots" / "dfire_official_test"
            artifact_names.extend(_copy_plots_from_dir(plot_dir, "dfire_official_test"))
        if "pyro_sdis_validation" in prior_metrics:
            plot_dir = RESULTS_DIR / "plots" / "pyro_sdis_validation"
            artifact_names.extend(_copy_plots_from_dir(plot_dir, "pyro_sdis_validation"))
        if "dfire_validation" in prior_metrics:
            plot_dir = RESULTS_DIR / "plots" / "dfire_validation"
            artifact_names.extend(_copy_plots_from_dir(plot_dir, "dfire_validation"))
    if args.skip_samples:
        artifact_names.extend(prior_report.get("artifacts", []))

    sources_to_run = (
        {}
        if args.only_samples
        else ({args.only_source: config_names[args.only_source]} if args.only_source else config_names)
    )
    for report_name, config_name in sources_to_run.items():
        config_path = eval_dir / config_name
        evaluation = model.val(
            data=str(config_path),
            imgsz=640,
            batch=8,
            workers=2,
            plots=True,
            project=str(RESULTS_DIR / "plots"),
            name=report_name,
            exist_ok=True,
            device=0,
        )
        results[report_name] = _complete_class_metrics(detection_metrics(evaluation))
        artifact_names.extend(_copy_eval_plots(evaluation, report_name))
        logger.info("%s metrics: %s", report_name, results[report_name])

    if args.skip_samples:
        samples = prior_report.get("prediction_samples", [])
    else:
        samples = _select_prediction_samples(model, args.data_dir)
        artifact_names.extend(
            path.name for path in sorted((RESULTS_DIR / "detection_samples").glob("dfire_test_*.jpg"))
        )
    report = {
        "weights": str(args.weights.resolve()),
        "class_names": ["fire", "smoke"],
        "evaluation_policy": (
            "Each source has one final metric evaluation pass. "
            "The D-Fire test set is held out and must not be used for tuning. "
            "Pyro-SDIS contains smoke and negative images only; fire class scores are undefined."
        ),
        "metrics": results,
        "prior_metrics_source_note": prior_metrics_source_note,
        "prediction_samples": samples
        if args.skip_samples
        else [
            {"file": f"detection_samples/dfire_test_{category}_{index:02d}_{path.stem}.jpg", "error_category": category}
            for index, (path, category) in enumerate(samples, 1)
        ],
        "artifacts": list(dict.fromkeys(artifact_names)),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    logger.info("Final evaluation report written to %s.", args.output)


if __name__ == "__main__":
    main()
