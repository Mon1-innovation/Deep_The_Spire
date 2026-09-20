from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

import cv2


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class VideoInfo:
    def __init__(self, path: Path, capture: cv2.VideoCapture):
        self.path = path
        self.width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        self.frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.duration_sec = self.frame_count / self.fps if self.fps > 0 else 0.0


def open_video(path: Path) -> tuple[cv2.VideoCapture, VideoInfo]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {path}")
    info = VideoInfo(path, capture)
    ok, frame = capture.read()
    if not ok or frame is None:
        capture.release()
        raise ValueError(f"first frame cannot be decoded: {path}")
    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    return capture, info


def frames(capture: cv2.VideoCapture) -> Iterator[tuple[int, float, object]]:
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        yield index, index / fps if fps > 0 else 0.0, frame
        index += 1

