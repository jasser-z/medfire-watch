"""Capture license-cleared demo media with isolated alert history and no Telegram delivery."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 90) -> None:
    """Wait for a local service without printing response bodies or credentials."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Capture service exited; inspect runs/capture logs locally.")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    raise TimeoutError("Capture service did not become ready.")


def main() -> None:
    """Record real UI flows using an explicitly supplied, license-cleared fire clip."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video", required=True, type=Path, help="License-cleared clip without faces or personal footage."
    )
    parser.add_argument("--api-port", type=int, default=18000)
    parser.add_argument("--dashboard-port", type=int, default=18501)
    args = parser.parse_args()
    clip = args.video.resolve(strict=True)
    import cv2
    import imageio_ffmpeg
    from playwright.sync_api import sync_playwright

    output = ROOT / "docs/screenshots"
    work = ROOT / "runs/capture"
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fake = work / "fake-camera.y4m"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(clip), "-vf", "scale=640:360,fps=15", "-pix_fmt", "yuv420p", str(fake)],
        check=True,
        capture_output=True,
    )
    capture = cv2.VideoCapture(str(clip))
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise ValueError("Capture clip contains no readable frame.")
    image = work / "fire-frame.png"
    cv2.imwrite(str(image), frame)
    api = f"http://127.0.0.1:{args.api_port}"
    ui = f"http://127.0.0.1:{args.dashboard_port}"
    env = {**os.environ, "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "MEDFIRE_API_URL": api}
    env["MEDFIRE_PUBLIC_API_URL"] = api
    # Empty explicit variables prevent dotenv from loading the author's Telegram credentials.
    # Capture history is separate from the user's actual snapshots and delivery records.
    bootstrap = (
        "from pathlib import Path; from alerts.manager import AlertManager; "
        "AlertManager.from_config=classmethod(lambda cls,p: cls(state_path=Path('runs/capture/alerts/state.json'))); "
        f"import uvicorn; uvicorn.run('api.main:app',host='127.0.0.1',port={args.api_port})"
    )
    processes = []
    handles = []
    try:
        for name, command in [
            ("api", [sys.executable, "-c", bootstrap]),
            (
                "ui",
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    "dashboard/app.py",
                    "--server.port",
                    str(args.dashboard_port),
                    "--server.headless",
                    "true",
                ],
            ),
        ]:
            handle = (work / f"{name}.log").open("wb")
            handles.append(handle)
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            )
        wait_ready(api + "/health", processes[0])
        wait_ready(ui + "/_stcore/health", processes[1])
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--use-fake-ui-for-media-stream",
                    "--use-fake-device-for-media-stream",
                    f"--use-file-for-fake-video-capture={fake}",
                    "--autoplay-policy=no-user-gesture-required",
                    "--enable-unsafe-swiftshader",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                permissions=["camera"],
                reduced_motion="reduce",
                record_video_dir=str(work / "recordings"),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.goto(ui)
            page.get_by_role("tab", name="Fire danger", exact=True).wait_for()
            page.wait_for_timeout(12000)
            page.screenshot(path=str(output / "fire-danger.png"))
            print("Captured dashboard globe")
            for name, coords in [
                ("tunis", "lng=10.1815&lat=36.8065&z=11"),
                ("marseille", "lng=5.3698&lat=43.2965&z=11"),
            ]:
                page.goto(api + "/world-map?capture=" + name + "#" + coords)
                page.wait_for_timeout(5000)
                # The entrance sets a globe view; use its recent-place UI to reach the requested city afterwards.
                values = dict(part.split("=") for part in coords.split("&"))
                page.evaluate(
                    "item => localStorage.setItem('medfire-searches', JSON.stringify([item]))",
                    {"label": name.title(), "center": [float(values["lng"]), float(values["lat"])], "zoom": 12},
                )
                page.locator("#map-controls summary").click()
                page.locator("#place").focus()
                page.locator("#results button").first.click()
                page.wait_for_timeout(8000)
                page.locator(".maplibregl-popup-close-button").click()
                page.locator(".maplibregl-ctrl-attrib summary").click()
                page.screenshot(path=str(output / f"map-{name}.png"))
                print("Captured map", name)
            page.goto(ui)
            page.get_by_role("tab", name="Test", exact=True).click()
            page.get_by_role("tab", name="Image inspector", exact=True).click()
            page.locator('input[type="file"]').first.set_input_files(str(image))
            page.get_by_role("button", name="Inspect for fire and smoke").click()
            page.get_by_text("Detection result", exact=True).wait_for(timeout=60000)
            page.get_by_text("Detection result", exact=True).scroll_into_view_if_needed()
            page.screenshot(path=str(output / "image-inspector.png"))
            print("Captured annotated image")
            page.goto(api + "/video-test")
            page.locator("#file").set_input_files(str(clip))
            page.locator("#check").wait_for()
            page.wait_for_function("!document.querySelector('#check').disabled", timeout=60000)
            page.locator("#check").click()
            page.wait_for_timeout(4000)
            page.screenshot(path=str(output / "video-studio.png"))
            print("Captured video studio")
            page.goto(api + "/live-camera")
            page.get_by_role("button", name="Start camera").click()
            page.wait_for_timeout(6000)
            page.screenshot(path=str(output / "live-camera.png"))
            print("Captured fake-camera detection; Telegram disabled")
            page.goto(ui)
            page.get_by_role("tab", name="Alerts", exact=True).click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(output / "alerts.png"))
            print("Captured isolated alerts page")
            # A separate recording contains exactly the 20-second demonstration sequence.
            demo = context.new_page()
            recording = demo.video
            demo.goto(api + "/video-test")
            demo.locator("#file").set_input_files(str(clip))
            demo.wait_for_function("!document.querySelector('#check').disabled", timeout=60000)
            demo.locator("#check").click()
            demo.locator("video").evaluate("video => { video.loop = true; }")
            demo.wait_for_timeout(20000)
            demo.close()
            recorded = recording.path()
            context.close()
            browser.close()
        media = ROOT / "docs/media"
        media.mkdir(exist_ok=True)
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-sseof",
                "-20",
                "-i",
                str(recorded),
                "-t",
                "20",
                "-filter_complex",
                "fps=5,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=80[p];[b][p]paletteuse",
                "-loop",
                "0",
                str(media / "demo.gif"),
            ],
            check=True,
            capture_output=True,
        )
        if (media / "demo.gif").stat().st_size >= 8_000_000:
            raise RuntimeError("Demo GIF exceeds 8 MB; lower resolution or frame rate and re-encode.")
        print("Captured 20-second demo GIF")
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
