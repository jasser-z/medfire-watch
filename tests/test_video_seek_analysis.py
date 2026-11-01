from pathlib import Path

import cv2
import numpy as np
from medfire_watch.video_analysis import analyse_video


def test_seek_prioritises_playhead_then_backfills_every_frame_once(tmp_path: Path):
    source = tmp_path / "seek.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
    for i in range(30):
        writer.write(np.full((24, 32, 3), i * 5, dtype=np.uint8))
    writer.release()

    class Detector:
        def predict_batch(self, images):
            return [{"detections": []} for _ in images]

    requested = [1.5]
    published = []
    result = analyse_video(
        source,
        Detector(),
        lambda d, i, fps: published.append(i),
        priority=lambda: requested.pop() if requested else None,
    )
    assert published[0] == 15
    assert sorted(published) == list(range(30))
    assert len(result["results"]) == result["frames"] == 30
