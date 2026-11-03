from __future__ import annotations

import os

import pytest

# Set env before importing any FastAPI or service modules
os.environ["MEDFIRE_SKIP_WARMUP"] = "1"


@pytest.fixture(autouse=True, scope="session")
def configure_test_environment():
    """Keep local credentials out of tests and never trigger live provider/Telegram calls."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("MEDFIRE_SKIP_WARMUP", "1")
        for name in ("FIRMS_MAP_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "MEDFIRE_API_TOKEN"):
            patch.setenv(name, "")
        yield

