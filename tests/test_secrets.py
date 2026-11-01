from __future__ import annotations

from pathlib import Path

import pytest
from medfire_watch.secrets import mask_secret, read_firms_key


def test_firms_key_reader_strips_bom_whitespace_and_quotes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('\ufeffFIRMS_MAP_KEY = "  test-key-value  "\n', encoding="utf-8")
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)

    secret = read_firms_key(env_file)

    assert secret == "test-key-value"
    assert mask_secret(f"masked={secret}", secret) == "masked=[REDACTED]"
