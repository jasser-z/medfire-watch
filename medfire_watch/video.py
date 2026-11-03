from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
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
        """Advance detection persistence and return a newly confirmed event."""
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
        """Report whether the current consecutive-frame event has fired."""
        return self._alerted


def _draw_detections(frame: np.ndarray, detections: list[dict[str, Any]]) -> np.ndarray:
    return draw_detections(frame, detections)


class VideoFrameReader(threading.Thread):
    """Worker thread that reads video frames into a bounded queue."""

    def __init__(
        self,
        capture: VideoReader,
        frame_queue: queue.Queue[np.ndarray | None],
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="medfire-video-reader", daemon=True)
        self.capture = capture
        self.frame_queue = frame_queue
        self.stop_event = stop_event
        self.frames_decoded = 0
        self.errors: list[Exception] = []

    def run(self) -> None:
        try:
            while not self.stop_event.is_set():
                success, frame = self.capture.read()
                if not success:
                    break
                self.frames_decoded += 1
                while not self.stop_event.is_set():
                    try:
                        self.frame_queue.put(frame, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except Exception as exc:
            self.errors.append(exc)
        finally:
            while not self.stop_event.is_set():
                try:
                    self.frame_queue.put(None, timeout=0.2)
                    break
                except queue.Full:
                    continue


class VideoFrameEncoder(threading.Thread):
    """Worker thread that annotates and writes frames into an FFmpeg stdin pipe."""

    def __init__(
        self,
        encoder: subprocess.Popen,
        encode_queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], int] | None],
    ) -> None:
        super().__init__(name="medfire-video-encoder", daemon=True)
        self.encoder = encoder
        self.encode_queue = encode_queue
        self.frames_encoded = 0
        self.errors: list[Exception] = []

    def run(self) -> None:
        try:
            while True:
                item = self.encode_queue.get()
                if item is None:
                    break
                frame, detections, _index = item
                annotated = _draw_detections(frame, detections)
                if self.encoder.stdin is None:
                    raise RuntimeError("FFmpeg input pipe is unavailable.")
                self.encoder.stdin.write(np.ascontiguousarray(annotated).tobytes())
                self.frames_encoded += 1
        except Exception as exc:
            self.errors.append(exc)


def build_detection_timeline(detection_seconds: set[int]) -> list[dict[str, int]]:
    """Merge individual detection seconds into continuous intervals."""
    timeline: list[dict[str, int]] = []
    for second in sorted(detection_seconds):
        if timeline and second <= timeline[-1]["end_seconds"] + 1:
            timeline[-1]["end_seconds"] = second
        else:
            timeline.append({"start_seconds": second, "end_seconds": second})
    return timeline


def start_raw_encoder(
    ffmpeg: str,
    width: int,
    height: int,
    fps: float,
    codec_arguments: list[str],
    raw_output_path: Path,
) -> subprocess.Popen:
    """Launch the raw video encoder subprocess."""
    return subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "pipe:0",
            "-an",
            *codec_arguments,
            "-pix_fmt",
            "yuv420p",
            str(raw_output_path),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def close_and_finalize_encoder(
    encoder: subprocess.Popen,
    writer: VideoFrameEncoder,
    encode_queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], int] | None],
) -> None:
    """Clean up and wait for the encoder worker and FFmpeg process."""
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
    if writer.errors:
        raise RuntimeError("Video encoder worker failed.") from writer.errors[0]


def finalize_video_output(ffmpeg: str, raw_output_path: Path, input_path: Path, output_path: Path) -> None:
    """Combine annotated raw video with source audio into faststart MP4."""
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
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raw_output_path.unlink(missing_ok=True)
        raise RuntimeError("Could not encode the annotated video as H.264 MP4.") from exc
    finally:
        raw_output_path.unlink(missing_ok=True)


def _fetch_frame_batch(
    frame_queue: queue.Queue[np.ndarray | None],
    batch_size: int,
    reader_is_alive: Callable[[], bool],
    cancelled: threading.Event | None = None,
) -> tuple[list[np.ndarray], bool]:
    """Retrieve a batch of frames from the frame queue."""
    frames: list[np.ndarray] = []
    reached_end = False
    deadline = time.monotonic() + 30
    while len(frames) < batch_size:
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("Video job cancelled.")
        try:
            item = frame_queue.get(timeout=1)
        except queue.Empty:
            if not reader_is_alive():
                reached_end = True
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Video decoder stalled for 30 seconds.") from None
            continue
        if item is None:
            reached_end = True
            break
        frames.append(item)
        deadline = time.monotonic() + 30
    return frames, reached_end


def iter_video_detections(
    input_path: Path,
    output_path: Path,
    infer: Callable[[np.ndarray], dict[str, Any]],
    consecutive_frames: int = 5,
    max_duration_seconds: float = 120,
    infer_batch: Callable[[list[np.ndarray]], list[dict[str, Any]]] | None = None,
    batch_size: int = 8,
    initial_results: list[dict[str, Any]] | None = None,
    cancelled: threading.Event | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield export progress and final frame-preserving video results."""
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

    raw_output_path = output_path.with_name(f"{output_path.stem}.video-only.mp4")
    try:
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        encoder_name, codec_arguments = encoder_arguments(width, height)
        encoder = start_raw_encoder(ffmpeg, width, height, fps, codec_arguments, raw_output_path)
    except BaseException:
        capture.close()
        raw_output_path.unlink(missing_ok=True)
        raise

    alert_tracker = ConsecutiveDetectionAlert(consecutive_frames)
    frame_index = 0
    alert_events: list[dict[str, Any]] = []
    detection_seconds: set[int] = set()
    frame_queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=batch_size * 4)
    encode_queue: queue.Queue[tuple[np.ndarray, list[dict[str, Any]], int] | None] = queue.Queue(maxsize=batch_size * 2)
    stop_reader = threading.Event()

    writer = VideoFrameEncoder(encoder, encode_queue)
    writer.start()

    reader = VideoFrameReader(capture, frame_queue, stop_reader)
    reader.start()

    detector_device = "unknown"
    detector_precision = "unknown"
    first_detection_seconds: float | None = None
    processing_complete = False

    try:
        while True:
            if cancelled is not None and cancelled.is_set():
                raise RuntimeError("Video job cancelled.")
            frames, reached_end = _fetch_frame_batch(frame_queue, batch_size, reader.is_alive, cancelled)
            if not frames and reached_end:
                break
            cached = (initial_results or [])[frame_index : frame_index + len(frames)]
            pending = frames[len(cached) :]
            fresh = (
                (infer_batch(pending) if infer_batch is not None else [infer(frame) for frame in pending])
                if pending
                else []
            )
            results = [*cached, *fresh]
            if results:
                detector_device = results[0].get("device", "unknown")
                detector_precision = results[0].get("precision", "unknown")
            if len(results) != len(frames):
                raise RuntimeError("The batched detector returned a different number of results than input frames.")
            for frame, result in zip(frames, results):
                if frame_index >= max(1, int(fps * max_duration_seconds)):
                    raise ValueError("Decoded video exceeds the configured duration limit.")
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
                encode_deadline = time.monotonic() + 30
                while True:
                    if cancelled is not None and cancelled.is_set():
                        raise RuntimeError("Video job cancelled.")
                    if writer.errors:
                        raise RuntimeError("Video encoder worker failed.") from writer.errors[0]
                    try:
                        encode_queue.put((frame, detections, frame_index), timeout=0.2)
                        break
                    except queue.Full:
                        if time.monotonic() > encode_deadline:
                            raise RuntimeError("Video encoder stalled for 30 seconds.") from None
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
        if reader.errors:
            raise RuntimeError("Video frame reader failed.") from reader.errors[0]
        processing_complete = True
    except Exception:
        LOGGER.exception("Video detection failed while processing %s.", input_path.name)
        raise
    finally:
        primary_error = sys.exception()
        stop_reader.set()
        reader.join(timeout=3)
        capture.close()
        try:
            close_and_finalize_encoder(encoder, writer, encode_queue)
        except BaseException as exc:
            raw_output_path.unlink(missing_ok=True)
            if primary_error is None:
                raise
            LOGGER.warning("Video encoder cleanup failed (%s); preserving the processing error.", type(exc).__name__)
        finally:
            if encoder.poll() is None:
                encoder.kill()
                encoder.wait(timeout=5)
            if not processing_complete or frame_index == 0:
                raw_output_path.unlink(missing_ok=True)

    if frame_index == 0:
        raise ValueError("Video contains no decodable frames.")
    if writer.frames_encoded != frame_index or reader.frames_decoded != frame_index:
        raw_output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Frame counts differ: decoded={reader.frames_decoded}, inferred={frame_index}, "
            f"encoded={writer.frames_encoded}."
        )

    output_duration_seconds = frame_index / fps
    finalize_video_output(ffmpeg, raw_output_path, input_path, output_path)

    elapsed = time.perf_counter() - elapsed_start
    timeline = build_detection_timeline(detection_seconds)
    yield {
        "type": "complete",
        "frames_processed": frame_index,
        "frames_encoded": writer.frames_encoded,
        "input_frames": reader.frames_decoded,
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
