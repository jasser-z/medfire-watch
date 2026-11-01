from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from medfire_watch.world_hotspots import refresh_if_old  # noqa: E402

LOG = ROOT / "logs" / "world_refresh.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")


def main() -> None:
    try:
        refresh_if_old()
        from medfire_watch.fire_weather import metadata
        metadata()
        logging.info("World observations refreshed. No Telegram messages sent.")
        if sys.stdout is not None:
            print("World observations refreshed.")
    except Exception as exc:
        logging.error("World refresh failed (%s); cached data retained.", type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
