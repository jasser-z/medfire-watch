# Detector training

Use Python 3.11 and install `requirements-training.txt` plus a suitable PyTorch build.
Read [dataset rights](../THIRD_PARTY_NOTICES.md) before downloading or redistributing images.
Runtime does not require training data.

1. Run `python scripts/download_detection_data.py --help` for the pinned Pyro-SDIS revision,
   subset options and optional D-Fire import. Obtain D-Fire from its official repository;
   verify source class IDs from dataset metadata.
2. Run `python scripts/verify_detection_data.py --help` to validate images and YOLO labels.
3. Run `python scripts/merge_detection_data.py --help` to merge sources using official
   D-Fire train/test lists and leakage checks. Configuration is in `configs/detection_data.yaml`.
4. Run `python scripts/train_detector.py --help`. `configs/train_detect.yaml` defines training;
   `--fast-dev` uses at most 500 images and one epoch. MLflow stores local experiment records.
5. Select confidence using validation only. Run `python scripts/evaluate_detector.py --help`
   for source-specific evaluation with an explicit weights path. Evaluate the held-out test once.

The deployed artifact is `models/detection/weights/best.pt`. Training runs live under `runs/`
and do not enter Git. [Model card](MODEL_CARD.md) records current split metrics and protocol.
