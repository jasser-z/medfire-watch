"""Cooperative pause boundaries shared by analysis and video export."""

import threading


def wait_for_video(
    paused: threading.Event | None,
    cancelled: threading.Event | None,
    stopped: threading.Event | None = None,
) -> bool:
    """Wait without spinning; cancellation still wakes a paused worker."""
    while True:
        if stopped is not None and stopped.is_set():
            return False
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("Video job cancelled.")
        if paused is None or not paused.is_set():
            return True
        if cancelled is not None:
            cancelled.wait(0.1)
        else:
            threading.Event().wait(0.1)
