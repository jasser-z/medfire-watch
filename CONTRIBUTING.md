# Contributing to MedFire Watch

Thank you for your interest in contributing to MedFire Watch. This project is released under the AGPL-3.0 license.

## Prerequisites

- **Python 3.11** is strictly required (Python 3.12+ is not supported due to PyTorch and ecosystem constraints).
- **Node.js** (v18+) for running UI and client-side unit tests.
- **FFmpeg** installed and accessible on your system PATH.

## Development Setup

1. Clone the repository locally and navigate to the directory.
2. Create and activate a Python 3.11 virtual environment:

   **Windows PowerShell:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements-dev.txt
   npm ci
   ```

   **Linux / macOS:**
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install -r requirements-dev.txt
   npm ci
   ```

3. Copy `.env.example` to `.env` to configure optional credentials (such as your NASA FIRMS map key or Telegram bot credentials). Default settings allow running all local services without any API keys.

## Validation & Quality Gates

Before submitting any changes, all five quality checks must pass:

```bash
# 1. Python linting and code style
ruff check .

# 2. Python unit and integration test suite
pytest -q

# 3. Client-side JavaScript test suite
npm test

# 4. JavaScript and HTML formatting verification
npm run format:check

# 5. Local documentation link and image integrity
python scripts/check_docs.py
```

### Warm-up Skip in Tests

By default, the test suite sets `MEDFIRE_SKIP_WARMUP=1` via `tests/conftest.py` to prevent unnecessary model loading and GPU initialization during unit tests. A single smoke test (`test_real_warmup_smoke`) verifies full YOLO model weight loading.

## Code Style Guidelines

- **Python**: Follow PEP 8 conventions enforced by Ruff with a maximum line length of 120 characters. Always use type hints (`from __future__ import annotations`).
- **JavaScript**: Follow standard ES modules (`.mjs`) and modern DOM APIs without third-party frameworks. Formatting is enforced by Prettier (`npm run format`).
- **Documentation**: Keep `README.md` and `README.fr.md` strictly synchronized in structure and section ordering. Run `python scripts/check_docs.py` to ensure all relative links and referenced images resolve.

## Commit Style

Write clear, descriptive commit messages summarizing what changed and why. Prefer atomic commits that leave the test suite green.

## Repository Setup

For repository metadata, GitHub topics, and release procedures, see [GitHub Setup](docs/GITHUB_SETUP.md).

