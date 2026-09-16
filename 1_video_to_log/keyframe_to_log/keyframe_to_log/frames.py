from __future__ import annotations
import re
from pathlib import Path
from .models import Keyframe

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_TIME_PATTERNS = (re.compile(r"(?:^|[_-])t(?:ime)?[_-]?(\d+(?:\.\d+)?)", re.I), re.compile(r"(?:^|[_-])(\d+(?:\.\d+)?)s(?:[_-]|$)", re.I))
_FRAME_PATTERN = re.compile(r"(?:^|[_-])(?:frame|f)[_-]?(\d+)(?:[_-]|\.|$)", re.I)

def _number_from_name(path: Path) -> float | None:
    for pattern in _TIME_PATTERNS:
        match = pattern.search(path.stem)
        if match:
            return float(match.group(1))
    numbers = re.findall(r"\d+(?:\.\d+)?", path.stem)
    return float(numbers[-1]) if numbers else None

def _frame_index(path: Path) -> int | None:
    match = _FRAME_PATTERN.search(path.stem)
    return int(match.group(1)) if match else None

def discover_keyframes(root: str | Path) -> list[Keyframe]:
    root = Path(root)
    paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    frames = []
    for ordinal, image_path in enumerate(sorted(paths)):
        timestamp = _number_from_name(image_path)
        frames.append(Keyframe(str(image_path), timestamp if timestamp is not None else float(ordinal), _frame_index(image_path)))
    return sorted(frames, key=lambda frame: (frame.timestamp, frame.path))

