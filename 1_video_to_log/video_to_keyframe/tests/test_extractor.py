from pathlib import Path

import cv2
import numpy as np

from keyframe_extractor.config import Settings
from keyframe_extractor.pipeline import extract_video
from keyframe_extractor.scores import is_black_frame


def make_video(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1280, 720))
    for i in range(90):
        value = 30 if i < 30 else (180 if i < 60 else 60)
        frame = np.full((720, 1280, 3), value, dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_extract_writes_provenance_and_keyframes(tmp_path: Path) -> None:
    video = tmp_path / "run_001.mp4"
    make_video(video)
    settings = Settings(coarse_fps=2, anchor_interval=100, stable_frames=2)
    result = extract_video(video, tmp_path / "segmentation", settings)
    output = tmp_path / "segmentation" / "run_001"
    assert result["status"] == "success"
    assert result["output_count"] >= 2
    assert (output / "manifest.json").exists()
    assert len((output / "keyframes.jsonl").read_text().splitlines()) == result["output_count"]


def test_matching_manifest_is_skipped(tmp_path: Path) -> None:
    video = tmp_path / "run_001.mp4"
    make_video(video)
    output = tmp_path / "segmentation"
    extract_video(video, output, Settings())
    result = extract_video(video, output, Settings())
    assert result["skipped"] is True


def test_black_transition_is_not_a_keyframe(tmp_path: Path) -> None:
    video = tmp_path / "transition.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1280, 720))
    for value in (80, 0, 170):
        for _ in range(30):
            writer.write(np.full((720, 1280, 3), value, dtype=np.uint8))
    writer.release()
    result = extract_video(video, tmp_path / "segmentation", Settings(coarse_fps=10, anchor_interval=100))
    entries = [__import__("json").loads(line) for line in
               (tmp_path / "segmentation" / "transition" / "keyframes.jsonl").read_text().splitlines()]
    assert is_black_frame(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert result["status"] == "success"
    assert all(entry["frame_index"] // 30 != 1 for entry in entries)


def test_sensitive_roi_change_is_retained_in_order(tmp_path: Path) -> None:
    video = tmp_path / "combat.mp4"
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (1280, 720))
    for i in range(120):
        frame = np.full((720, 1280, 3), 60, dtype=np.uint8)
        if 30 <= i < 45:
            frame[470:680, 220:1060] = 220
        if 75 <= i < 90:
            frame[180:540, 300:980] = 180
        writer.write(frame)
    writer.release()
    result = extract_video(video, tmp_path / "segmentation", Settings(coarse_fps=10, anchor_interval=100))
    entries = [__import__("json").loads(line) for line in
               (tmp_path / "segmentation" / "combat" / "keyframes.jsonl").read_text().splitlines()]
    indices = [entry["frame_index"] for entry in entries]
    assert result["status"] == "success"
    assert indices == sorted(indices)
    assert any(25 <= index <= 60 for index in indices)
    assert any(70 <= index <= 105 for index in indices)
