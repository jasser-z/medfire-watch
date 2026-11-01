# User guide

## Installation

Install Python 3.11 and create a virtual environment with `python -m venv .venv`.
Activate with `.venv\Scripts\Activate.ps1` on Windows PowerShell or
`source .venv/bin/activate` on Linux/macOS. Run `python -m pip install -r requirements.txt`.
Copy `.env.example` to `.env` and supply your own FIRMS and Telegram credentials locally.
FIRMS access is available through the [NASA API](https://firms.modaps.eosdis.nasa.gov/api/).
Start `python scripts/run_app.py` and visit [the dashboard](http://127.0.0.1:8501).

## Fire danger

Search a country or town and right-click a place for current weather and today's summary.
Heat observations default to 24 hours; controls offer 1, 3, 6, 12 or 24 hours.
The globe entrance animation runs on initial loading; tab switching preserves the view.
Weather follows the viewer's date and timezone. When today's forecast cannot be verified,
the weather layer is hidden with an unavailable/outdated warning.
Satellite freshness and retrieval errors appear beneath its controls.

## Live camera and alerts

Allow browser camera permission and press Start camera. Negotiated dimensions and fps
appear beside the detector update rate. Fullscreen includes video, boxes and status.
Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` locally. Open the bot, press Start,
and use Connect Telegram chat if needed. Alerts lists attempts and confirmed delivery.
Delete all clears local history and snapshots; existing Telegram messages stay in Telegram.

## Image and video inspection

Test contains Video studio and Image inspector. Images accept JPEG/PNG up to 10 MiB and
25 megapixels, matching the API. Video uploads go directly to FastAPI and accept configured
limits of 1,024 MiB, 600 seconds and 4K. Playback uses source quality; boxes follow the
analysed frame and the timeline shows analysis progress. Seeking gives that region priority.
Download the annotated export when processing finishes. Image/video tests do not send
Telegram photos; Live camera does.

## Troubleshooting

Use `python scripts/check_env.py --fast-dev` to inspect dependencies and provider access.
Check `logs/`, API `/health` and provider status. A missing FIRMS key prevents fresh
observations. Weather-provider failure leaves its category unavailable. A busy port requires
stopping the owner or selecting another port. The launcher reuses healthy workspace services;
`--restart` replaces them and refuses unrelated listeners. Install a CUDA-enabled PyTorch
build for supported NVIDIA hardware; CPU processing remains available. Camera permission
requires a trusted browser context. Browser fullscreen and device compatibility need local checks.

## Development

Install `requirements-dev.txt`, then `npm ci`. Run `ruff check .`, `pytest -q` and `npm test`.
CI also reports Python and JavaScript coverage. `npm run format` formats browser assets.
See [training](TRAINING.md), [deployment](DEPLOYMENT.md) and [demo](DEMO.md).
