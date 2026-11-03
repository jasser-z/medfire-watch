"""GPU-scaled, bounded-queue analysis with playhead-first inference and backfill."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from medfire_watch.video_hardware import VideoReader


def analyse_video(
    path: Path,
    detector: Any,
    publish: Callable,
    batch_size: int = 8,
    initial_results: list | None = None,
    priority: Callable | None = None,
    cancelled: threading.Event | None = None,
    max_duration_seconds: float = 600,
) -> dict:
    """Publish batch predictions with seek priority and full backfill."""
    if batch_size < 1:
        raise ValueError("Video inference batch size must be at least one.")
    reader = VideoReader(path, inference_width=640)
    results: dict[int, dict] = {}
    started = time.perf_counter()
    decoded: queue.Queue = queue.Queue(maxsize=3)
    stopped = threading.Event()
    fps = reader.fps

    def infer(indexed: list[tuple[int, Any]], source: VideoReader) -> None:
        """Infer missing frames and scale boxes to source resolution."""
        pending = [(i, image) for i, image in indexed if i not in results]
        images = [image for _, image in pending]
        if not images:
            return
        batch = (
            detector.predict_batch(images)
            if hasattr(detector, "predict_batch")
            else [detector.predict(f) for f in images]
        )
        if len(batch) != len(pending):
            raise RuntimeError("Detector result count does not match the video batch.")
        for (index, _), result in zip(pending, batch):
            for item in result["detections"]:
                x1, y1, x2, y2 = item["xyxy"]
                sx, sy = source.source_width / source.width, source.source_height / source.height
                item["xyxy"] = [x1 * sx, y1 * sy, x2 * sx, y2 * sy]
            results[index] = result
            publish(result["detections"], index, fps)

    def decode() -> None:
        """Decode batches into the bounded analysis queue until stopped."""
        index = len(initial_results or [])
        try:
            while not stopped.is_set():
                images = []
                for _ in range(batch_size):
                    ok, frame = reader.read()
                    if not ok:
                        break
                    images.append((index, frame))
                    index += 1
                    if index > max(1, int(fps * max_duration_seconds)):
                        raise ValueError("Decoded video exceeds the configured duration limit.")
                while not stopped.is_set():
                    try:
                        decoded.put(images, timeout=0.1)
                        break
                    except queue.Full:
                        pass
                if not images:
                    break
        except Exception as exc:
            while not stopped.is_set():
                try:
                    decoded.put(exc, timeout=0.1)
                    break
                except queue.Full:
                    pass

    worker = None
    try:
        for index, result in enumerate(initial_results or []):
            ok, _ = reader.read()
            if not ok:
                break
            results[index] = result
            publish(result["detections"], index, fps)
        worker = threading.Thread(target=decode, name="video-analysis-decode", daemon=True)
        worker.start()
        decode_deadline = time.monotonic() + 30
        while True:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("Video job cancelled.")
            target = priority() if priority else None
            if target is not None:
                first = max(0, round(target * fps))
                if first not in results:
                    seeker = VideoReader(path, inference_width=640, start_seconds=first / fps)
                    try:
                        for offset in range(0, max(batch_size, round(1.5 * fps)), batch_size):
                            images = []
                            for n in range(batch_size):
                                ok, image = seeker.read()
                                if not ok:
                                    break
                                images.append((first + offset + n, image))
                            infer(images, seeker)
                            if not images:
                                break
                    finally:
                        seeker.close()
            try:
                images = decoded.get(timeout=0.5)
            except queue.Empty:
                if not worker.is_alive():
                    raise RuntimeError("Video decoder terminated without an end marker.") from None
                if time.monotonic() > decode_deadline:
                    raise RuntimeError("Video decoder stalled for 30 seconds.") from None
                continue
            decode_deadline = time.monotonic() + 30
            if isinstance(images, Exception):
                raise images
            if not images:
                break
            infer(images, reader)
        elapsed = time.perf_counter() - started
        if not results:
            raise ValueError("Video contains no decodable frames.")
        if sorted(results) != list(range(len(results))):
            raise RuntimeError("Video analysis contains missing frame results.")
        return {
            "results": [results[i] for i in sorted(results)],
            "analysis_fps": len(results) / max(elapsed, 1e-6),
            "analysis_seconds": elapsed,
            "decoder": reader.backend,
            "frames": len(results),
        }
    finally:
        stopped.set()
        if worker is not None:
            worker.join(timeout=5)
        reader.close()
