"""FFmpeg hardware video I/O. Pixel annotation still runs in host memory."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np


@lru_cache(maxsize=1)
def nvenc_available() -> bool:
    """Exercise the encoder/driver, rather than just trusting an encoder listing."""
    try:
        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=size=320x180:rate=60",
                "-frames:v",
                "1",
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def encoder_arguments(width: int, height: int) -> tuple[str, list[str]]:
    """Choose hardware encoding when available, otherwise CPU H.264."""
    if width >= 256 and height >= 128 and nvenc_available():
        return "h264_nvenc", [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-tune",
            "ll",
            "-cq",
            "16",
            "-b:v",
            "0",
            "-bf",
            "0",
        ]
    return "libx264", ["-c:v", "libx264", "-preset", "fast", "-crf", "16"]


class VideoReader:
    """Try NVDEC, falling back before frame zero for unsupported sources/hardware."""

    def __init__(self, path: Path, inference_width: int | None = None, start_seconds: float = 0) -> None:
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError("Could not open the video.")
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        raw_fps = self.capture.get(cv2.CAP_PROP_FPS)
        self.fps = float(raw_fps) if np.isfinite(raw_fps) and raw_fps > 0 else 25.0
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if start_seconds:
            self.capture.set(cv2.CAP_PROP_POS_MSEC, start_seconds * 1000)
        self.source_width, self.source_height = self.width, self.height
        if inference_width and self.width > inference_width:
            self.width = inference_width - inference_width % 2
            self.height = max(2, round(self.source_height * self.width / self.source_width / 2) * 2)
        self.backend = "opencv-cpu"
        self.process: subprocess.Popen | None = None
        self.first_frame: np.ndarray | None = None
        if self.width < 1 or self.height < 1 or self.width * self.height > 8_294_400:
            self.close()
            raise ValueError("Video dimensions are invalid or exceed 4K.")
        if self.width >= 256 and self.height >= 128 and nvenc_available():
            # Scale on the GPU before downloading BGR pixels; CPU decode is the fallback before frame zero.
            filters = "hwdownload,format=nv12,format=bgr24"
            if inference_width:
                filters = f"scale_cuda={self.width}:{self.height}," + filters
            self.process = subprocess.Popen(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-hwaccel",
                    "cuda",
                    "-hwaccel_output_format",
                    "cuda",
                    *(["-ss", str(start_seconds)] if start_seconds else []),
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-vf",
                    filters,
                    "-an",
                    "-sn",
                    "-fps_mode",
                    "passthrough",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "bgr24",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                self.first_frame = self._read_gpu()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                self.first_frame = None
            if self.first_frame is not None:
                self.backend = "cuda-nvdec"
                self.capture.release()
            else:
                self._close_process()
        if inference_width and self.backend == "opencv-cpu" and self.source_width > self.width:
            self.process = subprocess.Popen(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *(["-ss", str(start_seconds)] if start_seconds else []),
                    "-i",
                    str(path),
                    "-map",
                    "0:v:0",
                    "-vf",
                    f"scale={self.width}:{self.height},format=bgr24",
                    "-an",
                    "-sn",
                    "-fps_mode",
                    "passthrough",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "bgr24",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.first_frame = self._read_gpu()
            if self.first_frame is None:
                self.close()
                raise ValueError("Could not decode small inference frames.")
            self.backend = "ffmpeg-cpu-scaled"
            self.capture.release()

    def _read_gpu(self) -> np.ndarray | None:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("GPU video decoder process is not running.")
        size = self.width * self.height * 3
        data = self.process.stdout.read(size)
        if not data:
            if self.process.wait(timeout=15) != 0:
                raise RuntimeError("GPU video decoding failed.")
            return None
        if len(data) != size:
            raise RuntimeError("GPU decoder produced a partial frame.")
        return np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3).copy()

    def read(self) -> tuple[bool, np.ndarray | None]:
        """Read the next frame from the selected decode backend."""
        if self.first_frame is not None:
            frame, self.first_frame = self.first_frame, None
            return True, frame
        if self.backend in {"cuda-nvdec", "ffmpeg-cpu-scaled"}:
            frame = self._read_gpu()
            return frame is not None, frame
        ok, frame = self.capture.read()
        if ok and (self.width, self.height) != (self.source_width, self.source_height):
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        return ok, frame

    def _close_process(self) -> None:
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            if self.process.stdout is not None:
                self.process.stdout.close()
            self.process = None

    def close(self) -> None:
        """Release decoder processes and video capture handles."""
        self.capture.release()
        self._close_process()
