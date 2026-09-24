from pathlib import Path

import cv2
import numpy as np

from keyframe_extractor.config import Settings, load_settings
from keyframe_extractor.config import Roi
from keyframe_extractor.pipeline import extract_video
from keyframe_extractor.selector import Selector
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
    settings = Settings(coarse_fps=2, anchor_interval=100, stable_frames=2, pseudo_keyframe_fallback=False)
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
    result = extract_video(video, tmp_path / "segmentation", Settings(coarse_fps=10, anchor_interval=100, pseudo_keyframe_fallback=False))
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
    result = extract_video(video, tmp_path / "segmentation", Settings(coarse_fps=10, anchor_interval=100, pseudo_keyframe_fallback=False))
    entries = [__import__("json").loads(line) for line in
               (tmp_path / "segmentation" / "combat" / "keyframes.jsonl").read_text().splitlines()]
    indices = [entry["frame_index"] for entry in entries]
    assert result["status"] == "success"
    assert indices == sorted(indices)
    assert any(25 <= index <= 60 for index in indices)
    assert any(70 <= index <= 105 for index in indices)


def test_beta_pre_coarse_fallback_uses_previous_sample() -> None:
    settings = Settings(
        coarse_fps=10,
        anchor_interval=100,
        stable_frames=1,
        pseudo_keyframe_fallback=True,
        rois=[Roi("combat_hand", 0.0, 0.0, 1.0, 1.0, 1.0)],
    )
    selector = Selector(settings, 30)
    base = np.full((20, 20, 3), 30, dtype=np.uint8)
    changed = base.copy()
    changed[5:15, 5:15] = 240
    assert selector.consider(0, 0.0, base) is not None
    selector.last_output = None
    selector.last_output_hash = None
    selector.consider(3, 0.1, base)
    selector.consider(6, 0.2, changed)
    selected = selector.finish()
    assert selected is not None
    assert selected.trigger.endswith("_pre_coarse")
    assert selected.frame_index == 3


def test_pseudo_keyframe_fallback_is_enabled_by_default():
    config_path = Path(__file__).parents[1] / "config" / "sts2_720p.json"
    assert Settings().pseudo_keyframe_fallback is True
    settings = load_settings(config_path)
    assert settings.pseudo_keyframe_fallback is True
    assert settings.pseudo_keyframe_scope == "global"
    assert settings.coarse_fps == 12
    assert settings.stable_frames == 3


def test_load_settings_reads_pseudo_keyframe_and_decision_parameters(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"pseudo_keyframe_scope":"global",'
        '"pseudo_keyframe_rois":["full_frame"],'
        '"decision_merge_window":2.5,'
        '"decision_merge_ssim":0.9,'
        '"decision_merge_phash_distance":9,'
        '"decision_merge_rois":["full_frame"]}',
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.pseudo_keyframe_scope == "global"
    assert settings.pseudo_keyframe_rois == ("full_frame",)
    assert settings.decision_merge_window == 2.5
    assert settings.decision_merge_ssim == 0.9
    assert settings.decision_merge_phash_distance == 9
    assert settings.decision_merge_rois == ("full_frame",)
