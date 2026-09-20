from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_settings
from .pipeline import extract_video


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract evidence keyframes from STS2 recordings")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--video", type=Path, help="process one MP4")
    group.add_argument("--input-dir", type=Path, default=Path("temp/video"), help="directory containing MP4 files")
    parser.add_argument("--output-dir", type=Path, default=Path("segmentation"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--roi-config", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug-video", action="store_true", help="reserved for debug overlays")
    args = parser.parse_args()
    settings = load_settings(args.roi_config or args.config)
    videos = [args.video] if args.video else sorted(args.input_dir.glob("*.mp4"))
    if not videos:
        parser.error("no MP4 files found")
    failures = 0
    for video in videos:
        try:
            result = extract_video(video, args.output_dir, settings, args.force, args.dry_run)
            state = "skipped" if result.get("skipped") else result["status"]
            print(f"{video.name}: {state}, keyframes={result.get('output_count', 0)}")
            failures += result.get("status") == "failed"
        except Exception as error:
            failures += 1
            print(f"{video.name}: failed: {error}")
    raise SystemExit(2 if failures == len(videos) else (1 if failures else 0))

