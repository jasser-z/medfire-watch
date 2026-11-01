from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "configs"


def load_env() -> None:
    """Load local environment variables from .env if present."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def read_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML file and return a Python dictionary."""
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Missing config file: {resolved}")
    with resolved.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file must contain a dictionary: {resolved}")
    return data


def get_setting(name: str, default: Any | None = None) -> Any:
    """Read an environment variable or return a safe default."""
    load_env()
    return os.getenv(name, default)

