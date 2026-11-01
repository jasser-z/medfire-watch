"""Record actual map and detector flows with private, empty alert history and Telegram disabled."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CITIES = {
    "tunis": {"center": [10.1833, 36.8000], "zoom": 16, "pitch": 60, "bearing": -30},
    "marseille": {"center": [5.3672, 43.3114], "zoom": 15.7, "pitch": 60, "bearing": -25},
}


def wait_ready(url: str, process: subprocess.Popen, timeout: float = 90) -> None:
    """Wait for a service without exposing response bodies or credentials."""
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


def map_action(page: Any, action: str, argument: Any = None) -> Any:
    """Access the real map through a capture-only module export."""
    return page.evaluate(
        """async ([action, argument]) => {
          const {captureMap: map} = await import(document.querySelector('script[type=module]').src);
          if (action === 'camera') { map.stop(); map.jumpTo(argument); return; }
          if (action === 'fly') { map.flyTo({...argument, essential: true}); return; }
          if (action === 'orbit') { map.easeTo({...argument, essential: true}); return; }
          if (action === 'stats') return {
            zoom: map.getZoom(), pitch: map.getPitch(),
            points: map.queryRenderedFeatures({layers:['observations']}).length,
            clusters: map.queryRenderedFeatures({layers:['observation-clusters']}).length,
            buildings: map.queryRenderedFeatures({layers:['buildings-3d']}).length,
            emptyHidden: getComputedStyle(document.querySelector('#satellite-empty')).display === 'none',
            observations: document.querySelector('#observations').textContent,
          };
          if (action === 'point') {
            const features = map.queryRenderedFeatures({layers:['observations']});
            if (!features.length) return null;
            const points = features.map(f => map.project(f.geometry.coordinates))
              .filter(p => p.x > 420 && p.x < innerWidth - 80 && p.y > 100 && p.y < innerHeight - 100)
              .sort((a,b) => Math.hypot(a.x-innerWidth/2,a.y-innerHeight/2)
                - Math.hypot(b.x-innerWidth/2,b.y-innerHeight/2));
            const point = points[0];
            if (!point) return null;
            return {x:point.x, y:point.y};
          }
        }""",
        [action, argument],
    )


def open_credits(page: Any) -> None:
    """Leave provider attribution visibly expanded in a static map capture."""
    page.locator(".maplibregl-ctrl-attrib").evaluate(
        "element => { element.classList.add('maplibregl-compact-show'); element.setAttribute('open',''); }"
    )


def encode_gif(ffmpeg: str, video: Path, target: Path, duration: int = 20) -> None:
    """Encode the final recording interval as a compact, looping GIF."""
    for width, colours in [(640, 80), (560, 64), (480, 64)]:
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-sseof",
                f"-{duration}",
                "-i",
                str(video),
                "-t",
                str(duration),
                "-filter_complex",
                f"fps=6,scale={width}:-1:flags=lanczos,split[a][b];"
                f"[a]palettegen=max_colors={colours}[p];[b][p]paletteuse",
                "-loop",
                "0",
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        if target.stat().st_size < 8_000_000:
            return
    raise RuntimeError(f"{target.name} exceeds 8 MB.")


def capture_maps(context: Any, api: str, output: Path, work: Path, ffmpeg: str) -> dict:
    """Capture real observations, city buildings and a globe-to-city camera journey."""
    page = context.new_page()
    page.goto(api + "/world-map?capture=review")
    page.wait_for_selector(".maplibregl-canvas")
    page.wait_for_timeout(10000)
    page.locator("#map-controls summary").click()
    stats = map_action(page, "stats")
    assert stats["emptyHidden"], "Populated satellite feed incorrectly displays its empty state."
    assert stats["points"] + stats["clusters"] > 0, "No satellite observations rendered."
    open_credits(page)
    page.screenshot(path=str(output / "fire-danger.png"))
    print("Captured globe with observed heat points", flush=True)

    with urlopen(api + "/world-map/data", timeout=30) as response:
        detections = json.load(response)["world"]["detections"]
    # Select an actual recent high-FRP observation, never a fabricated point near a chosen city.
    selected = max((d for d in detections if abs(d["latitude"]) < 55), key=lambda d: d.get("frp", 0))
    map_action(
        page, "camera", {"center": [selected["longitude"], selected["latitude"]], "zoom": 8, "pitch": 0, "bearing": 0}
    )
    page.wait_for_timeout(6000)
    point = map_action(page, "point")
    if point:
        page.mouse.click(point["x"], point["y"])
        page.wait_for_timeout(2000)
    page.locator("#map-controls").evaluate("element => { element.open = true; }")
    stats["satellite_scene"] = map_action(page, "stats")
    assert stats["satellite_scene"]["points"] > 0
    open_credits(page)
    page.screenshot(path=str(output / "satellite-detections.png"))
    print("Captured real satellite detections", flush=True)

    for name, camera in CITIES.items():
        page.locator("#map-controls").evaluate("element => { element.open = true; }")
        page.get_by_label("Weather danger areas", exact=False).uncheck()
        page.locator(".maplibregl-popup-close-button").evaluate_all("buttons => buttons.forEach(b => b.click())")
        page.locator("#place").fill(name.title())
        map_action(page, "camera", camera)
        page.wait_for_timeout(9000)
        # Search results are navigation chrome; the camera already points at the named city's real geometry.
        page.locator("#results").evaluate("element => element.replaceChildren()")
        page.locator("#place").evaluate("element => element.blur()")
        city = map_action(page, "stats")
        assert city["buildings"] > 0 and city["pitch"] >= 50, f"No visible 3D buildings in {name}."
        assert city["emptyHidden"]
        stats[name] = city
        open_credits(page)
        page.screenshot(path=str(output / f"map-{name}.png"))
        print("Captured tilted 3D city", name, city["buildings"], "buildings", flush=True)

    page.locator("#map-controls summary").click()
    (work / "map-checks.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    # Warm the target's real map tiles before recording the approach, then return to the globe.
    camera = CITIES["marseille"]
    for zoom in [4, 7, 10, 12, 14, camera["zoom"]]:
        map_action(page, "camera", {"center": camera["center"], "zoom": zoom, "pitch": 0, "bearing": -25})
        page.wait_for_function(
            """async () => {
              const {captureMap} = await import(document.querySelector('script[type=module]').src);
              return captureMap.areTilesLoaded();
            }""",
            timeout=30000,
        )
        page.wait_for_timeout(500)
    map_action(page, "camera", {"center": [10, 30], "zoom": 1.3, "pitch": 0, "bearing": 0})
    page.wait_for_timeout(4000)
    recording = page.video
    map_action(page, "orbit", {"center": [25, 30], "zoom": 1.5, "duration": 3000})
    page.wait_for_timeout(3000)
    map_action(page, "fly", {**camera, "pitch": 0, "duration": 10000, "curve": 1.25})
    page.wait_for_timeout(10000)
    map_action(page, "orbit", {"pitch": 60, "duration": 2000})
    page.wait_for_timeout(2000)
    map_action(page, "orbit", {"bearing": 35, "duration": 4000})
    page.wait_for_timeout(4000)
    page.wait_for_timeout(1000)
    page.close()
    encode_gif(ffmpeg, recording.path(), ROOT / "docs/media/earth-zoom.gif")
    print("Recorded Earth zoom and 3D orbit GIF", flush=True)
    (work / "map-checks.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    return stats


def capture_detection(context: Any, api: str, ui: str, output: Path, clip: Path, image: Path, ffmpeg: str) -> None:
    """Capture empty alert setup and actual detector overlays without manufacturing delivery success."""
    page = context.new_page()
    page.goto(ui)
    page.get_by_role("tab", name="Alerts", exact=True).click()
    page.get_by_text("No live-camera snapshot attempts have been recorded yet.", exact=True).wait_for()
    page.get_by_role("button", name="Connect Telegram chat", exact=True).wait_for()
    page.get_by_role("button", name="Delete all", exact=True).wait_for()
    page.wait_for_timeout(2000)
    assert page.get_by_text("Delivery failed; check configuration and network", exact=True).count() == 0
    page.screenshot(path=str(output / "alerts.png"))
    print("Captured clean alert setup, no simulated delivery records", flush=True)
    page.get_by_role("tab", name="Test", exact=True).click()
    page.get_by_role("tab", name="Image inspector", exact=True).click()
    page.locator('input[type="file"]').first.set_input_files(str(image))
    page.get_by_role("button", name="Inspect for fire and smoke").click()
    page.get_by_text("Detection result", exact=True).wait_for(timeout=60000)
    page.get_by_text("Detection result", exact=True).scroll_into_view_if_needed()
    page.screenshot(path=str(output / "image-inspector.png"))
    page.goto(api + "/video-test")
    page.locator("#file").set_input_files(str(clip))
    page.wait_for_function("!document.querySelector('#check').disabled", timeout=60000)
    page.locator("#check").click()
    page.wait_for_timeout(3000)
    page.screenshot(path=str(output / "video-studio.png"))
    page.goto(api + "/live-camera")
    page.get_by_role("button", name="Start camera").click()
    page.wait_for_function("/[1-9]\\d* boxes/.test(document.querySelector('#detect').textContent)", timeout=30000)
    page.wait_for_function(
        "Number(document.querySelector('#detect').textContent.match(/Detection ([\\d.]+)/)?.[1] || 0) > 0"
    )
    assert not page.locator("#notice").inner_text(), "Camera capture contains an error notice."
    page.screenshot(path=str(output / "live-camera.png"))
    assert "failed" not in page.locator("#notice").inner_text().lower()
    page.close()
    print("Captured camera detection before any delivery attempt", flush=True)

    demo = context.new_page()
    demo.goto(api + "/video-test")
    demo.locator("#file").set_input_files(str(clip))
    demo.wait_for_function("!document.querySelector('#check').disabled", timeout=60000)
    demo.locator("#check").click()
    demo.locator("video").evaluate("video => { video.loop = true; }")
    demo.wait_for_timeout(20000)
    recording = demo.video
    demo.close()
    encode_gif(ffmpeg, recording.path(), ROOT / "docs/media/demo.gif")
    print("Recorded live prediction GIF", flush=True)


def main() -> None:
    """Launch isolated services and capture real browser media at 1440×900."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path, help="License-cleared fire clip without faces.")
    parser.add_argument("--section", choices=["all", "map", "detection"], default="all")
    parser.add_argument("--api-port", type=int, default=18000)
    parser.add_argument("--dashboard-port", type=int, default=18501)
    args = parser.parse_args()
    import cv2
    import imageio_ffmpeg
    from playwright.sync_api import sync_playwright

    clip = args.video.resolve(strict=True)
    output, work = ROOT / "docs/screenshots", ROOT / "runs/capture"
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    (ROOT / "docs/media").mkdir(parents=True, exist_ok=True)
    isolated = Path(tempfile.mkdtemp(prefix="review-", dir=work))
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    fake, image = work / "fake-camera.y4m", work / "fire-frame.png"
    subprocess.run(
        [ffmpeg, "-y", "-i", str(clip), "-vf", "scale=640:360,fps=15", "-pix_fmt", "yuv420p", str(fake)],
        check=True,
        capture_output=True,
    )
    reader = cv2.VideoCapture(str(clip))
    ok, frame = reader.read()
    reader.release()
    if not ok:
        raise ValueError("The source clip has no readable frame.")
    cv2.imwrite(str(image), frame)
    api, ui = f"http://127.0.0.1:{args.api_port}", f"http://127.0.0.1:{args.dashboard_port}"
    env = {**os.environ, "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "MEDFIRE_API_URL": api}
    env["MEDFIRE_PUBLIC_API_URL"] = api
    # An isolated empty history shows connection setup, never fabricated success or intentional failure cards.
    relative = isolated.relative_to(ROOT).as_posix() + "/state.json"
    bootstrap = (
        "from pathlib import Path; from alerts.manager import AlertManager; "
        f"AlertManager.from_config=classmethod(lambda cls,p: cls(state_path=Path({relative!r}))); "
        f"import uvicorn; uvicorn.run('api.main:app',host='127.0.0.1',port={args.api_port})"
    )
    processes, handles = [], []
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
                record_video_dir=str(work / "recordings"),
                record_video_size={"width": 1440, "height": 900},
            )

            def expose_map(route: Any) -> None:
                response = route.fetch()
                # Only exports an automation handle; geometry, provider data, styling and app logic are unmodified.
                route.fulfill(response=response, body=response.text() + "\nexport {map as captureMap};\n")

            context.route("**/world-map/app.mjs*", expose_map)
            if args.section in {"all", "map"}:
                capture_maps(context, api, output, work, ffmpeg)
            if args.section in {"all", "detection"}:
                capture_detection(context, api, ui, output, clip, image, ffmpeg)
            context.close()
            browser.close()
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
