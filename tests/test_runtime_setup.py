from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_check_env_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_env.py", "--help"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "environment" in result.stdout.lower()


def test_config_files_load() -> None:
    import yaml

    for name in ["train_detect.yaml", "alerts.yaml", "detection.yaml"]:
        path = ROOT / "configs" / name
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)


def test_api_health() -> None:
    from api.main import app

    client = __import__("fastapi.testclient").testclient.TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_real_warmup_smoke() -> None:
    """Run real warm-up smoke test against DetectionService."""
    from api.services import DetectionService

    service = DetectionService()
    assert not service._warmed
    service.warmup()
    assert service._warmed is True
