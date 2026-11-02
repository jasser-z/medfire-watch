from __future__ import annotations

import os

import pytest

# Set env before importing any FastAPI or service modules
os.environ["MEDFIRE_SKIP_WARMUP"] = "1"


@pytest.fixture(autouse=True, scope="session")
def configure_test_environment() -> None:
    os.environ["MEDFIRE_SKIP_WARMUP"] = "1"

