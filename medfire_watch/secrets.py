from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def read_firms_key(env_file: Path) -> str | None:
    """Read the FIRMS key without exposing it, tolerating BOMs and quotes."""
    load_dotenv(env_file, override=False, encoding="utf-8-sig")
    value = os.getenv("FIRMS_MAP_KEY", "")
    if not value:
        try:
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                key, separator, candidate = line.partition("=")
                if separator and key.strip().lstrip("\ufeff") == "FIRMS_MAP_KEY":
                    value = candidate
                    break
        except FileNotFoundError:
            return None

    value = value.strip().lstrip("\ufeff").strip().strip("'\"").strip()
    return value or None


def mask_secret(text: str, secret: str | None) -> str:
    """Redact the supplied secret from status text and exception messages."""
    return text.replace(secret, "[REDACTED]") if secret else text
