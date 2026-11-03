from __future__ import annotations

import math
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
        load_dotenv(env_path, override=False, encoding="utf-8-sig")


def bounded_number(name: str, value: Any, minimum: float, maximum: float, *, integer: bool = False) -> float | int:
    """Reject non-finite and out-of-range settings with an actionable name."""
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be a number between {minimum:g} and {maximum:g}.") from None
    if isinstance(value, bool) or not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}.")
    if integer and not number.is_integer():
        raise ValueError(f"{name} must be an integer.")
    return int(number) if integer else number


def env_number(name: str, default: float, minimum: float, maximum: float, *, integer: bool = False) -> float | int:
    return bounded_number(name, os.getenv(name, str(default)), minimum, maximum, integer=integer)


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
