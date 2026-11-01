from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import mlflow
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medfire_watch.config import PROJECT_ROOT, read_yaml  # noqa: E402
from medfire_watch.detection import count_class_boxes, detection_metrics  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
RUNS_DIR = PROJECT_ROOT / "runs" / "detect" / "medfire_yolov8"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and evaluate YOLOv8 on verified, real wildfire imagery.")
    parser.add_argument(
        "--fast-dev",
        action="store_true",
        help="Use at most 500 real images and one epoch to smoke-test training.",
    )
    parser.add_argument(
        "--subset",
        type=int,
        default=None,
        help="Train on a balanced subset of N real images instead of all verified images.",
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from runs/detect/medfire_yolov8/weights/last.pt.",
    )
    parser.add_argument("--model", choices=("yolov8s", "yolov8n"), default=None)
    parser.add_argument("--patience", type=int, default=None)
    return parser.parse_args()


def _class_buckets(images_dir: Path, labels_dir: Path) -> dict[str, list[Path]]:
    buckets: dict[str, list[Path]] = defaultdict(list)
    for image_path in sorted(images_dir.rglob("*")):
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS or not image_path.is_file():
            continue
        label_path = labels_dir / image_path.relative_to(images_dir).with_suffix(".txt")
        if not label_path.is_file():
            raise FileNotFoundError(f"Missing label for {image_path}.")
        classes = {int(line.split()[0]) for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()}
        if 0 in classes:
            category = "fire"
        elif 1 in classes:
            category = "smoke"
        else:
            category = "negative"
        buckets[category].append(image_path)
    return buckets


def _build_subset(source_root: Path, subset_size: int, fast_dev: bool) -> Path:
    if subset_size < 3:
        raise ValueError("--subset must be at least 3 to allow category balancing.")
    target_root = (
        PROJECT_ROOT / "data" / "detection" / "subsets" / ("fast-dev" if fast_dev else f"subset-{subset_size}")
    )
    for split in ("train", "val"):
        for folder in ("images", "labels"):
            target_dir = target_root / folder / split
            target_dir.mkdir(parents=True, exist_ok=True)
            for old_file in target_dir.iterdir():
                if old_file.is_file():
                    old_file.unlink()

    train_buckets = _class_buckets(source_root / "images" / "train", source_root / "labels" / "train")
    selected: dict[str, list[Path]] = {}
    nonempty_categories = [key for key in ("fire", "smoke", "negative") if train_buckets[key]]
    if not nonempty_categories:
        raise ValueError("No images available for subset training.")
    budget_per_category = max(1, subset_size // len(nonempty_categories))
    for category in nonempty_categories:
        random.Random(42).shuffle(train_buckets[category])
        selected[category] = train_buckets[category][:budget_per_category]
    selected_images = [image for group in selected.values() for image in group]
    if len(selected_images) < subset_size:
        chosen = {image.resolve() for image in selected_images}
        remaining = [image for group in train_buckets.values() for image in group if image.resolve() not in chosen]
        selected_images.extend(remaining[: subset_size - len(selected_images)])

    for image in selected_images:
        label = (
            source_root / "labels" / "train" / image.relative_to(source_root / "images" / "train").with_suffix(".txt")
        )
        shutil.copy2(image, target_root / "images" / "train" / image.name)
        shutil.copy2(label, target_root / "labels" / "train" / label.name)

    val_root = source_root / "images" / "val"
    val_by_source_category: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for path in sorted(val_root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            relative = path.relative_to(val_root)
            source = relative.parts[0] if len(relative.parts) > 1 else "default"
            label = source_root / "labels" / "val" / relative.with_suffix(".txt")
            classes = {int(line.split()[0]) for line in label.read_text(encoding="utf-8").splitlines() if line.strip()}
            category = "fire" if 0 in classes else "smoke" if 1 in classes else "negative"
            val_by_source_category[(source, category)].append(path)
    val_image_count = sum(len(images) for images in val_by_source_category.values())
    val_limit = min(max(1, subset_size // 10), val_image_count)
    val_images: list[Path] = []
    while len(val_images) < val_limit:
        added = False
        for source_category in sorted(val_by_source_category):
            if val_by_source_category[source_category]:
                val_images.append(val_by_source_category[source_category].pop(0))
                added = True
                if len(val_images) == val_limit:
                    break
        if not added:
            break
    for image in val_images:
        label = source_root / "labels" / "val" / image.relative_to(val_root).with_suffix(".txt")
        shutil.copy2(image, target_root / "images" / "val" / image.name)
        shutil.copy2(label, target_root / "labels" / "val" / label.name)

    source_config = yaml.safe_load((PROJECT_ROOT / "configs" / "detection_data.yaml").read_text(encoding="utf-8"))
    subset_config = {
        "path": str(target_root.resolve()),
        "train": "images/train",
        "val": "images/val",
        "nc": source_config["nc"],
        "names": source_config["names"],
    }
    subset_yaml = target_root / "dataset.yaml"
    subset_yaml.write_text(yaml.safe_dump(subset_config, sort_keys=False), encoding="utf-8")
    logger.info(
        "Built balanced subset with %d training images across %s; validation images=%d.",
        len(selected_images),
        {name: len(paths) for name, paths in selected.items()},
        val_limit,
    )
    return subset_yaml


def _is_oom_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "out of memory" in message or "cuda error: out of memory" in message


def _is_worker_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "dataloader worker" in message or "worker process" in message


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


def _epoch_timing_callbacks(total_epochs: int) -> tuple[Any, Any, list[float]]:
    starts: dict[int, float] = {}
    durations: list[float] = []

    def on_epoch_start(trainer: Any) -> None:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        starts[int(trainer.epoch)] = time.perf_counter()

    def on_epoch_end(trainer: Any) -> None:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        epoch = int(trainer.epoch)
        started = starts.pop(epoch, None)
        if started is None:
            logger.warning("Could not measure epoch %d duration.", epoch + 1)
            return
        per_epoch_seconds = time.perf_counter() - started
        durations.append(per_epoch_seconds)
        completed = epoch + 1
        remaining = max(0, total_epochs - completed)
        logger.info(
            "Epoch %d/%d finished in %.2f seconds (epoch wall time, excluding startup); "
            "projected remaining training time %.2f seconds.",
            completed,
            total_epochs,
            per_epoch_seconds,
            per_epoch_seconds * remaining,
        )

    return on_epoch_start, on_epoch_end, durations


def _train_with_fallback(
    model: Any,
    *,
    data_yaml: Path,
    args: argparse.Namespace,
    epochs: int,
    patience: int,
) -> tuple[Any, list[float], dict[str, int | None]]:
    import torch

    settings = read_yaml(PROJECT_ROOT / "configs" / "train_detect.yaml")
    on_epoch_start, on_epoch_end, epoch_durations = _epoch_timing_callbacks(epochs)
    model.add_callback("on_train_epoch_start", on_epoch_start)
    model.add_callback("on_train_epoch_end", on_epoch_end)
    batch = int(settings.get("batch", 16))
    min_batch = int(settings.get("batch_min", 8))
    workers = int(settings.get("workers", 6))
    min_workers = int(settings.get("workers_min", 2))
    image_size = int(settings.get("imgsz", 640))
    while True:
        try:
            if torch.cuda.is_available():
                torch.cuda.reset_peak_memory_stats()
            results = model.train(
                data=str(data_yaml),
                imgsz=image_size,
                epochs=epochs,
                batch=batch,
                workers=workers,
                cache=bool(settings.get("cache", False)),
                amp=bool(settings.get("amp", True)),
                patience=patience,
                save_period=int(settings.get("save_period", 1)),
                project=str(RUNS_DIR.parent),
                name=RUNS_DIR.name,
                exist_ok=True,
                resume=args.resume,
                pretrained=bool(settings.get("pretrained", True)),
                verbose=True,
            )
            memory = {
                "peak_allocated_bytes": (int(torch.cuda.max_memory_allocated()) if torch.cuda.is_available() else None),
                "peak_reserved_bytes": (int(torch.cuda.max_memory_reserved()) if torch.cuda.is_available() else None),
            }
            logger.info(
                "Training peak CUDA memory: allocated=%.2f GiB, reserved=%.2f GiB.",
                (memory["peak_allocated_bytes"] or 0) / (1024**3),
                (memory["peak_reserved_bytes"] or 0) / (1024**3),
            )
            return results, epoch_durations, memory
        except (RuntimeError, MemoryError) as exc:
            if _is_oom_error(exc) and batch > min_batch:
                batch = min_batch
                logger.warning("CUDA out of memory at batch size; retrying with batch=%d.", batch)
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except ImportError:
                    logger.warning("Could not import torch to clear the CUDA cache.")
                continue
            if _is_worker_error(exc) and workers > min_workers:
                workers = min_workers
                logger.warning("DataLoader worker failure; retrying with workers=%d.", workers)
                continue
            raise


def main() -> None:
    args = parse_args()
    if args.subset is not None and args.subset < 3:
        raise SystemExit("--subset must be at least 3.")
    if args.epochs is not None and args.epochs < 1:
        raise SystemExit("--epochs must be positive.")

    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit(
            "Ultralytics is required for YOLO training. Install project dependencies in .venv first."
        ) from exc

    config = read_yaml(PROJECT_ROOT / "configs" / "train_detect.yaml")
    model_name = args.model or config.get("model", "yolov8s")
    source_yaml = PROJECT_ROOT / "configs" / "detection_data.yaml"
    if not source_yaml.is_file():
        raise SystemExit("Detection data is not verified. Run scripts/01 and scripts/02 first.")
    data_config = yaml.safe_load(source_yaml.read_text(encoding="utf-8"))
    source_root = Path(data_config["path"])
    if not (source_root / "images" / "train").is_dir() or not (source_root / "images" / "val").is_dir():
        raise SystemExit("Verified train/val image directories are missing; download real data first.")

    use_subset = args.fast_dev or args.subset is not None
    subset_size = min(args.subset or 500, 500) if args.fast_dev else args.subset
    data_yaml = (
        _build_subset(source_root, subset_size, args.fast_dev)
        if use_subset and subset_size is not None
        else source_yaml
    )
    epochs = 1 if args.fast_dev else args.epochs or int(config.get("epochs", 20))
    patience = args.patience or int(config.get("patience", 5))
    weight_path = RUNS_DIR / "weights" / "last.pt"
    if args.resume:
        if not weight_path.is_file():
            raise SystemExit(f"Cannot resume: checkpoint not found at {weight_path}.")
        weights = str(weight_path)
    else:
        weights = f"{model_name}.pt"

    if not args.fast_dev:
        counts = count_class_boxes(source_root)
        if counts.get(0, 0) == 0 or counts.get(1, 0) == 0:
            raise SystemExit(
                "Full two-class training requires real fire and smoke boxes in the verified dataset. "
                f"Observed boxes: fire={counts.get(0, 0)}, smoke={counts.get(1, 0)}. "
                "Pyro-SDIS is smoke-only; add D-Fire after inspecting its real source labels."
            )

    model = YOLO(weights)
    mlflow.set_tracking_uri(f"sqlite:///{(PROJECT_ROOT / 'mlflow.db').as_posix()}")
    mlflow.set_experiment("medfire-watch-detection")
    with mlflow.start_run(run_name=f"{model_name}{'-fast-dev' if args.fast_dev else ''}"):
        mlflow.log_params(
            {
                "model": model_name,
                "epochs": epochs,
                "subset": subset_size or "full",
                "image_size": 640,
                "amp": True,
                "batch_initial": 16,
                "workers_initial": 6,
                "resume": args.resume,
                "fast_dev": args.fast_dev,
            }
        )
        results, epoch_durations, peak_gpu_memory = _train_with_fallback(
            model,
            data_yaml=data_yaml,
            args=args,
            epochs=epochs,
            patience=patience,
        )
        evaluation = model.val(data=str(data_yaml), imgsz=640, batch=8, workers=2, plots=True)
        metrics = detection_metrics(evaluation)
        metrics["training_results"] = _json_safe(getattr(results, "results_dict", {}))
        metrics["data_yaml"] = str(data_yaml)
        metrics["real_data_only"] = True
        metrics["training_measurements"] = {
            "epoch_wall_seconds_excluding_startup": epoch_durations,
            "peak_cuda_memory_bytes": peak_gpu_memory,
        }
        metrics_path = RUNS_DIR / "metrics_detection.json"
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(_json_safe(metrics), indent=2), encoding="utf-8")
        mlflow.log_metrics(
            {
                key: float(value)
                for key, value in metrics.items()
                if isinstance(value, (int, float)) and value is not None
            }
        )
        mlflow.log_artifact(str(metrics_path))
        best_weights = RUNS_DIR / "weights" / "best.pt"
        last_weights = RUNS_DIR / "weights" / "last.pt"
        if best_weights.is_file():
            mlflow.log_artifact(str(best_weights))
        if last_weights.is_file():
            mlflow.log_artifact(str(last_weights))
        validation_dir = Path(yaml.safe_load(data_yaml.read_text(encoding="utf-8"))["path"]) / "images" / "val"
        sample_images = sorted(
            path for path in validation_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )[:12]
        if sample_images:
            model.predict(
                source=[str(path) for path in sample_images],
                imgsz=640,
                save=True,
                project=str(RUNS_DIR.parent),
                name=f"{RUNS_DIR.name}-predictions",
                exist_ok=True,
            )
        logger.info("Real-data evaluation metrics saved to %s: %s", metrics_path, metrics)
        logger.info(
            "Sample prediction images and plots are saved by Ultralytics under %s.",
            RUNS_DIR,
        )


if __name__ == "__main__":
    main()
