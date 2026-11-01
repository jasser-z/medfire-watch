from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medfire_watch.config import PROJECT_ROOT  # noqa: E402
from medfire_watch.detection_data import build_merged_detection_dataset  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    detection_root = PROJECT_ROOT / "data" / "detection"
    parser = argparse.ArgumentParser(
        description="Merge verified Pyro-SDIS and D-Fire into leakage-safe unified YOLO splits."
    )
    parser.add_argument("--pyro-dir", type=Path, default=detection_root / "Pyro-SDIS")
    parser.add_argument("--dfire-dir", type=Path, default=detection_root / "dfire")
    parser.add_argument(
        "--official-train-list",
        type=Path,
        default=detection_root / "dfire_official_splits" / "dfire_train.txt",
    )
    parser.add_argument(
        "--official-test-list",
        type=Path,
        default=detection_root / "dfire_official_splits" / "dfire_test.txt",
    )
    parser.add_argument("--output-dir", type=Path, default=detection_root / "Merged")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_merged_detection_dataset(
        pyro_root=args.pyro_dir,
        dfire_root=args.dfire_dir,
        official_train_list=args.official_train_list,
        official_test_list=args.official_test_list,
        output_root=args.output_dir,
    )
    config_path = PROJECT_ROOT / "configs" / "detection_data.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.output_dir / "dataset.yaml", config_path)
    logger.info(
        "Verified official D-Fire split membership: %s",
        json.dumps(manifest["sources"]["D-Fire"]["official_split_audit"], sort_keys=True),
    )
    for split, totals in manifest["counts_by_split"].items():
        logger.info(
            "%s: images=%d, fire boxes=%d, smoke boxes=%d",
            split,
            totals["images"],
            totals["boxes"]["fire"],
            totals["boxes"]["smoke"],
        )
    logger.info(
        "Omitted %d invalid D-Fire annotation rows: %s",
        manifest["sources"]["D-Fire"]["invalid_annotation_rows_omitted"],
        manifest["sources"]["D-Fire"]["omitted_rows_by_reason"],
    )
    logger.info("Merged data config written to %s.", config_path)
    logger.info("Per-source reporting configs are under %s/evaluation.", args.output_dir)


if __name__ == "__main__":
    main()
