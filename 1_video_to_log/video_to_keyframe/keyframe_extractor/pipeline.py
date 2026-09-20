from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import Settings
from .output import write_jpeg, write_json_atomic
from .selector import Selector
from .video import frames, open_video, sha256_file


def extract_video(video_path: Path, output_root: Path, settings: Settings, force: bool = False, dry_run: bool = False) -> dict:
    output_dir = output_root / video_path.stem
    manifest_path = output_dir / "manifest.json"
    source_hash = sha256_file(video_path)
    if manifest_path.exists() and not force:
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if existing.get("source", {}).get("sha256") == source_hash and existing.get("status") == "success":
                return existing | {"skipped": True}
        except (OSError, json.JSONDecodeError):
            pass
    output_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = output_dir / "keyframes"
    keyframes_dir.mkdir(exist_ok=True)
    jsonl_path = output_dir / "keyframes.jsonl"
    warnings_path = output_dir / "warnings.log"
    warnings: list[str] = []
    capture = None
    selected_count = 0
    entries: list[dict] = []
    try:
        capture, info = open_video(video_path)
        warnings.extend(_validate(info.width, info.height, info.fps, video_path))
        selector = Selector(settings, info.fps)
        if not dry_run:
            jsonl_path.write_text("", encoding="utf-8")
        decode_errors = 0
        for index, timestamp, frame in frames(capture):
            try:
                selected = selector.consider(index, timestamp, frame)
            except Exception as error:
                decode_errors += 1
                warnings.append(f"frame {index}: {error}")
                if decode_errors > settings.max_decode_errors:
                    raise RuntimeError("maximum decode/processing errors exceeded")
                continue
            if selected is None:
                continue
            selected_count += 1
            name = f"kf_{selected_count:06d}_t_{selected.timestamp_sec:010.3f}.jpg"
            relative = Path("keyframes") / name
            entry = {"keyframe_id": f"{video_path.stem}-kf-{selected_count:06d}", "frame_index": selected.frame_index, "timestamp_sec": round(selected.timestamp_sec, 6), "path": relative.as_posix(), "trigger": selected.trigger, "changed_rois": selected.changed_rois, "change_score": round(selected.change_score, 6), "stable_frames": selected.stable_frames, "dedup_distance": None, "confidence": selected.confidence, "source": {"video": video_path.name, "sha256": source_hash}}
            entries.append(entry)
            if not dry_run:
                write_jpeg(output_dir / relative, selected.frame, settings.jpeg_quality)
                with jsonl_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=True) + "\n")
        selected = selector.finish()
        if selected is not None:
            selected_count += 1
            name = f"kf_{selected_count:06d}_t_{selected.timestamp_sec:010.3f}.jpg"
            relative = Path("keyframes") / name
            entry = {"keyframe_id": f"{video_path.stem}-kf-{selected_count:06d}", "frame_index": selected.frame_index, "timestamp_sec": round(selected.timestamp_sec, 6), "path": relative.as_posix(), "trigger": selected.trigger, "changed_rois": selected.changed_rois, "change_score": round(selected.change_score, 6), "stable_frames": selected.stable_frames, "dedup_distance": None, "confidence": selected.confidence, "source": {"video": video_path.name, "sha256": source_hash}}
            entries.append(entry)
            if not dry_run:
                write_jpeg(output_dir / relative, selected.frame, settings.jpeg_quality)
                with jsonl_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception as error:
        warnings.append(str(error))
        status = "failed"
        info = locals().get("info")
    else:
        status = "success"
    finally:
        if capture is not None:
            capture.release()
    if warnings:
        warnings_path.write_text("\n".join(warnings) + "\n", encoding="utf-8")
    elif warnings_path.exists():
        warnings_path.unlink()
    manifest = {"schema_version": 1, "status": status, "source": {"path": str(video_path.resolve()), "sha256": source_hash, "name": video_path.name}, "video": {"width": getattr(info, "width", None), "height": getattr(info, "height", None), "fps": getattr(info, "fps", None), "frame_count": getattr(info, "frame_count", None), "duration_sec": getattr(info, "duration_sec", None)}, "script_version": "0.2.0", "parameters": {"coarse_fps": settings.coarse_fps, "change_threshold": settings.change_threshold, "page_threshold": settings.page_threshold, "roi_change_threshold": settings.roi_change_threshold, "combat_change_threshold": settings.combat_change_threshold, "event_change_threshold": settings.event_change_threshold, "black_mean_threshold": settings.black_mean_threshold, "black_std_threshold": settings.black_std_threshold, "black_dark_ratio": settings.black_dark_ratio, "stable_frames": settings.stable_frames, "stable_threshold": settings.stable_threshold, "anchor_interval": settings.anchor_interval, "phash_distance": settings.phash_distance, "ssim_threshold": settings.ssim_threshold}, "output_count": selected_count, "warnings_count": len(warnings)}
    write_json_atomic(manifest_path, manifest)
    return manifest


def _validate(width: int, height: int, fps: float, path: Path) -> list[str]:
    warnings = []
    if width != 1280 or height != 720:
        warnings.append(f"{path.name}: expected 1280x720, got {width}x{height}")
    if not 29.97 <= fps <= 30.03:
        warnings.append(f"{path.name}: expected 30 FPS, got {fps:.4f}")
    return warnings
