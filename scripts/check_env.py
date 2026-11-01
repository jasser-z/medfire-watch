from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from medfire_watch.secrets import mask_secret, read_firms_key  # noqa: E402

VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
FIRMS_TEST_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/-9,30,12,45/1"


def run_cmd(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, shell=False)
    output = completed.stdout.strip() or completed.stderr.strip()
    return completed.returncode, output


def verify_venv() -> tuple[bool, str]:
    if not VENV_PYTHON.exists():
        return False, (
            "Missing .venv. Create it with:\npython -m venv .venv\nThen activate with: .\\.venv\\Scripts\\Activate.ps1"
        )
    _, version = run_cmd([str(VENV_PYTHON), "-c", "import sys; print(sys.version.split()[0])"])
    if version.startswith("3.11"):
        return True, version
    return False, f"Wrong Python version in .venv: {version}. Expected 3.11.x"


def check_git() -> bool:
    return shutil.which("git") is not None


def disk_space_gb() -> float:
    _, _, free = shutil.disk_usage(str(ROOT))
    return free / (1024**3)


def memory_gb() -> float:
    try:
        import psutil
    except ImportError:
        return 0.0
    return psutil.virtual_memory().available / (1024**3)


def test_firms_key() -> tuple[bool, str]:
    key = read_firms_key(ROOT / ".env")
    if not key:
        return False, "FIRMS_MAP_KEY is missing."

    try:
        response = requests.get(FIRMS_TEST_URL.format(key=key), timeout=30)
    except requests.RequestException as exc:
        detail = mask_secret(str(exc), key)
        return False, f"FIRMS test request failed: {detail}"

    preview = mask_secret(response.text[:80].replace("\r", " ").replace("\n", " "), key)
    summary = f"HTTP {response.status_code}; response preview (first 80 chars, key masked): {preview!r}"
    valid = response.status_code == 200 and bool(response.text.strip())
    return valid, summary


def check_torch() -> tuple[bool, str]:
    if not VENV_PYTHON.exists():
        return False, "Cannot inspect torch because the venv Python is missing."

    code = (
        "import importlib.util; "
        "spec = importlib.util.find_spec('torch'); "
        "print('MISSING' if spec is None else 'INSTALLED'); "
        'exec("if spec is not None:\\n import torch\\n '
        "print(f'torch_version={torch.__version__}')\\n "
        "print(f'cuda_available={torch.cuda.is_available()}')\\n "
        'print(f\'gpu_name={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \\"NONE\\"}\')")'
    )
    returncode, output = run_cmd([str(VENV_PYTHON), "-c", code])
    if returncode != 0 or "MISSING" in output:
        return False, output or "Torch is not installed in the venv."
    return "cuda_available=True" in output, output


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the MedFire Watch runtime environment.")
    parser.add_argument(
        "--fast-dev",
        action="store_true",
        help="Quick environment validation without long runs.",
    )
    args = parser.parse_args()

    print("=== MedFire Watch environment check ===")
    ok_venv, venv_msg = verify_venv()
    print(f"venv: {venv_msg}")
    if not ok_venv:
        print("Create it with:")
        print("python -m venv .venv")
        print("Then activate with: .\\.venv\\Scripts\\Activate.ps1")

    git_ok = check_git()
    print(f"git: {'OK' if git_ok else 'MISSING'}")
    free_gb = disk_space_gb()
    print(f"disk free: {free_gb:.2f} GB")
    if free_gb < 60:
        print("WARNING: Less than 60 GB free space; downloads and training may fail.")
    print(f"RAM free: {memory_gb():.2f} GB")

    nvidia_code, nvidia = run_cmd(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
    print(f"nvidia-smi: {nvidia if nvidia_code == 0 else 'NOT DETECTED'}")

    torch_ok, torch_status = check_torch()
    print(f"torch: {torch_status}")
    if not torch_ok:
        print("CUDA PyTorch install command:")
        print("python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121")

    key_ok, key_status = test_firms_key()
    print(f"FIRMS test: {key_status}")

    if args.fast_dev:
        print("Fast-dev mode enabled.")
    if not (ok_venv and git_ok and torch_ok and key_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
