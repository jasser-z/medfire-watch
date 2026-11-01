from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np

from medfire_watch.drawing import draw_detections
from medfire_watch.video_hardware import VideoReader, encoder_arguments

LOGGER = logging.getLogger(__name__)


class ConsecutiveDetectionAlert:
    def __init__(self, consecutive_frames: int) -> None:
        if consecutive_frames < 1:
            raise ValueError("consecutive_frames must be at least one.")
        self.consecutive_frames = consecutive_frames
        self._streak = 0
        self._first_detection_seconds: float | None = None
        self._alerted = False

    def update(self, detected: bool, timestamp_seconds: float) -> dict[str, Any] | None:
        if not detected:
            self._streak = 0
            self._first_detection_seconds = None
            self._alerted = False
            return None
        if self._streak == 0:
            self._first_detection_seconds = timestamp_seconds
        self._streak += 1
        if self._streak < self.consecutive_frames or self._alerted:
            return None
        self._alerted = True
        return {
            "first_detection_seconds": self._first_detection_seconds,
            "alert_seconds": timestamp_seconds,
            "consecutive_frames": self.consecutive_frames,
        }

    @property
    def alerted(self) -> bool:
        return self._alerted


def _draw_detections(frame: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    return draw_detections(frame, detections)




def iter_video_detections(
    input_path: Path,
    output_path: Path,
    infer: Callable[[np.ndarray], dict[str, Any]],
    consecutive_frames: int = 5,
    max_duration_seconds: float = 120,
    infer_batch: Callable[[list[np.ndarray]], list[dict[str, Any]]] | None = None,
    batch_size: int = 8,
    initial_results: list[dict[str, Any]] | None = None,
) -> Iterator[dict[str, Any]]:
    if batch_size < 1:
        raise ValueError("Video inference batch size must be at least one.")
    elapsed_start = time.perf_counter()
    capture = VideoReader(input_path)
    fps, width, height, frame_count = capture.fps, capture.width, capture.height, capture.frame_count
    duration_seconds = frame_count / fps if frame_count > 0 else 0
    if duration_seconds > max_duration_seconds:
        capture.close()
        raise ValueError(f"Video duration exceeds the {max_duration_seconds:g}-second limit.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    raw_output_path = output_path.with_name(f"{output_path.stem}.video-only.mp4")
    encoder_name, codec_arguments = encoder_arguments(width, height)
    encoder = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{width}x{height}", "-r", str(fps), "-i", "pipe:0", "-an", *codec_arguments,
         "-pix_fmt", "yuv420p", str(raw_output_path)],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    alert_tracker = ConsecutiveDetectionAlert(consecutive_frames)
    frame_index = 0
    alert_events: list[dict[str, Any]] = []
    detection_seconds: set[int] = set()
    frame_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=batch_size * 4)
    encode_queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], int] | None] = queue.Queue(maxsize=batch_size * 2)
    stop_reader = threading.Event()
    reader_errors: list[Exception] = []
    encoder_errors: list[Exception] = []
    frames_encoded = 0
    frames_decoded = 0
    detector_device = "unknown"
    detector_precision = "unknown"
    first_detection_seconds: float | None = None

    def encode_frames() -> None:
        nonlocal frames_encoded
        try:
            while True:
                item = encode_queue.get()
                if item is None:
                    break
                frame, detections, index = item
                annotated = _draw_detections(frame, detections)
                if encoder.stdin is None:
                    raise RuntimeError("FFmpeg input pipe is unavailable.")
                encoder.stdin.write(np.ascontiguousarray(annotated).tobytes())
                frames_encoded += 1
        except Exception as exc:
            encoder_errors.append(exc)

    writer = threading.Thread(target=encode_frames, name="medfire-video-encoder", daemon=True)
    writer.start()

    def read_frames() -> None:
        nonlocal frames_decoded
        try:
            while not stop_reader.is_set():
                success, frame = capture.read()
                if not success:
                    break
                frames_decoded += 1
                while not stop_reader.is_set():
                    try:
                        frame_queue.put(frame, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:
            reader_errors.append(exc)
        finally:
            while not stop_reader.is_set():
                try:
                    frame_queue.put(None, timeout=0.2)
                    break
                except queue.Full:
                    continue

    reader = threading.Thread(target=read_frames, name="medfire-video-reader", daemon=True)
    reader.start()
    try:
        while True:
            frames: list[np.ndarray] = []
            reached_end = False
            while len(frames) < batch_size:
                try:
                    item = frame_queue.get(timeout=1)
                except queue.Empty:
                    if not reader.is_alive():
                        reached_end = True
                        break
                    continue
                if item is None:
                    reached_end = True
                    break
                frames.append(item)
            if not frames and reached_end:
                break
            cached = (initial_results or [])[frame_index:frame_index + len(frames)]
            pending = frames[len(cached):]
            fresh = (infer_batch(pending) if infer_batch is not None else [infer(frame) for frame in pending]) if pending else []
            results = [*cached, *fresh]
            if results:
                detector_device = results[0].get("device", "unknown")
                detector_precision = results[0].get("precision", "unknown")
            if len(results) != len(frames):
                raise RuntimeError("The batched detector returned a different number of results than input frames.")
            for frame, result in zip(frames, results):
                timestamp_seconds = frame_index / fps
                detections = result["detections"]
                detected = any(item["class"] in {"fire", "smoke"} for item in detections)
                if detected:
                    detection_seconds.add(int(timestamp_seconds))
                alert = alert_tracker.update(detected, timestamp_seconds)
                if alert is not None:
                    alert_events.append(alert)
                if first_detection_seconds is None:
                    first_detection_seconds = time.perf_counter() - elapsed_start
                while True:
                    if encoder_errors:
                        raise RuntimeError("Video encoder worker failed.") from encoder_errors[0]
                    try:
                        encode_queue.put((frame, detections, frame_index), timeout=0.2)
                        break
                    except queue.Full:
                        continue
                if frame_index % max(1, round(fps * 2)) == 0:
                    yield {
                        "type": "progress",
                        "index": frame_index,
                        "frames_processed": frame_index + 1,
                        "fraction": min(1.0, (frame_index + 1) / frame_count) if frame_count > 0 else 0.0,
                        "timestamp_seconds": timestamp_seconds,
                    }
                frame_index += 1
            if reached_end:
                break
        if reader_errors:
            raise RuntimeError("Video frame reader failed.") from reader_errors[0]
    except Exception:
        LOGGER.exception("Video detection failed while processing %s.", input_path.name)
        raise
    finally:
        stop_reader.set()
        reader.join(timeout=3)
        capture.close()
        writer_deadline = time.perf_counter() + 60
        while writer.is_alive() and time.perf_counter() < writer_deadline:
            try:
                encode_queue.put(None, timeout=0.2)
                break
            except queue.Full:
                continue
        writer.join(timeout=60)
        if writer.is_alive():
            encoder.kill()
            writer.join(timeout=3)
            raise RuntimeError("Video encoder worker timed out.")
        if encoder.stdin is not None:
            encoder.stdin.close()
        try:
            encoder_status = encoder.wait(timeout=300)
        except subprocess.TimeoutExpired:
            encoder.kill()
            encoder.wait()
            raise RuntimeError("Video encoder timed out.") from None
        if encoder_status != 0:
            raise RuntimeError("Video encoder failed; verify codec availability.")
        if encoder_errors:
            raise RuntimeError("Video encoder worker failed.") from encoder_errors[0]

    if frames_encoded != frame_index or frames_decoded != frame_index:
        raise RuntimeError(f"Frame counts differ: decoded={frames_decoded}, inferred={frame_index}, encoded={frames_encoded}.")

    output_duration_seconds = frame_index / fps
    try:
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(raw_output_path),
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raw_output_path.unlink(missing_ok=True)
        raise RuntimeError("Could not encode the annotated video as H.264 MP4.") from exc
    finally:
        raw_output_path.unlink(missing_ok=True)

    elapsed = time.perf_counter() - elapsed_start
    timeline = []
    for second in sorted(detection_seconds):
        if timeline and second <= timeline[-1]["end_seconds"] + 1:
            timeline[-1]["end_seconds"] = second
        else:
            timeline.append({"start_seconds": second, "end_seconds": second})
    yield {
        "type": "complete",
        "frames_processed": frame_index,
        "frames_encoded": frames_encoded,
        "input_frames": frames_decoded,
        "source_metadata_frames": frame_count,
        "video_decoder": capture.backend,
        "video_encoder": encoder_name,
        "detector_device": detector_device,
        "detector_precision": detector_precision,
        "first_detection_seconds": first_detection_seconds,
        "source_fps": fps,
        "width": width,
        "height": height,
        "processing_fps": frame_index / elapsed if elapsed > 0 else 0.0,
        "elapsed_seconds": elapsed,
        "output_duration_seconds": output_duration_seconds,
        "consecutive_frames_required": consecutive_frames,
        "alert_count": len(alert_events),
        "first_alert": alert_events[0] if alert_events else None,
        "alerts": alert_events,
        "detection_timeline": timeline,
        "output_video_ready": output_path.is_file() and output_path.stat().st_size > 0,
    }


